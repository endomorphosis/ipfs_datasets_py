"""Scraper for Minnesota state laws.

This module contains the scraper for Minnesota statutes from the official state legislative website.
"""

import hashlib
import json
import os
import re
import ssl
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import urlparse

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


# Chapter 73 is the official terminal representation for its obsolete,
# renumbered locators.  The source and record-set digests deliberately bind
# this exclusion to one retained official response: a changed catalog must be
# reviewed rather than inheriting the old terminal classification.
_EXACT_TERMINAL_CHAPTER_CATALOGS = {
    "https://www.revisor.mn.gov/statutes/cite/73": {
        "content_sha256": (
            "1694bd7d93b62f697f78748bda2286952d9c2ebd5bba42cddbbd96f824eb174b"
        ),
        "content_cid": (
            "bafkreiawss6x3e5wf5ux66durpncfbuvfwoc5pk3xjbm3w55s34cj2yxjm"
        ),
        "content_byte_size": 72407,
        "receipt_sha256": (
            "5bed9dfd540b0ac0e81ed2e6c84311c91d9d62c2ccf19d17b88eb5ac64f35341"
        ),
        "receipt_cid": (
            "bafkreic35wo72valblaoqhws43eegeojdwowfqwm6gorpoeowwwgj42tie"
        ),
        # This digest covers, in DOM order, every exact source href, source
        # section number, normalized catalog text, target href, and target
        # link text for 73.55 plus its 51 similarly renumbered rows.
        "terminal_record_count": 52,
        "terminal_records_sha256": (
            "3b80d01c1daf9b8ad8bf87f280e5141cba37c1315aaced33b7f7562427bb9833"
        ),
        "disposition": "renumbered",
    }
}


def _terminal_catalog_records_sha256(records: List[Dict[str, str]]) -> str:
    canonical = json.dumps(
        records,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _source_bound_terminal_sections_from_chapter_catalog_html(
    html: str,
    *,
    source_url: str,
) -> Dict[str, Dict[str, str]]:
    """Type exact renumbered section locators from one sealed MN catalog."""

    catalog_url = str(source_url or "").strip()
    expected = _EXACT_TERMINAL_CHAPTER_CATALOGS.get(catalog_url)
    if expected is None:
        return {}
    raw = str(html or "").encode("utf-8")
    if len(raw) != int(expected["content_byte_size"]):
        return {}
    if hashlib.sha256(raw).hexdigest() != expected["content_sha256"]:
        return {}

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return {}
    soup = BeautifulSoup(html or "", "html.parser")
    analysis = soup.find(id="chapter_analysis")
    table = analysis.find("table") if analysis is not None else None
    if table is None:
        return {}

    records: List[Dict[str, str]] = []
    for row in table.find_all("tr"):
        row_text = " ".join(row.get_text(" ", strip=True).split())
        if "Renumbered" not in row_text:
            continue
        cells = row.find_all("td", recursive=False)
        if row.attrs or len(cells) != 2:
            return {}
        if cells[0].attrs or cells[1].attrs != {"class": ["inactive"]}:
            return {}
        source_tags = cells[0].find_all(recursive=False)
        target_tags = cells[1].find_all(recursive=False)
        if len(source_tags) != 1 or len(target_tags) != 1:
            return {}
        source_link = source_tags[0]
        target_link = target_tags[0]
        if source_link.name != "a" or target_link.name != "a":
            return {}
        section_number = source_link.get_text("", strip=True)
        source_href = str(source_link.get("href") or "").strip()
        target_href = str(target_link.get("href") or "").strip()
        if source_link.attrs != {"href": source_href}:
            return {}
        if target_link.attrs != {"href": target_href}:
            return {}
        if source_href != f"/statutes/cite/{section_number}":
            return {}
        if not target_href.startswith("/statutes/cite/"):
            return {}
        catalog_text = " ".join(cells[1].get_text(" ", strip=True).split())
        catalog_text = re.sub(r"\s+\]", "]", catalog_text)
        target_text = " ".join(target_link.get_text(" ", strip=True).split())
        records.append(
            {
                "source_href": source_href,
                "section_number": section_number,
                "catalog_text": catalog_text,
                "target_href": target_href,
                "target_text": target_text,
            }
        )

    if len(records) != int(expected["terminal_record_count"]):
        return {}
    if len({record["source_href"] for record in records}) != len(records):
        return {}
    if (
        _terminal_catalog_records_sha256(records)
        != expected["terminal_records_sha256"]
    ):
        return {}

    base_url = "https://www.revisor.mn.gov"
    return {
        f"{base_url}{record['source_href']}": {
            "section_number": record["section_number"],
            "catalog_text": record["catalog_text"],
            "disposition": str(expected["disposition"]),
            "renumbered_to": f"{base_url}{record['target_href']}",
            "catalog_url": catalog_url,
            "catalog_content_sha256": str(expected["content_sha256"]),
        }
        for record in records
    }


class MinnesotaScraper(BaseStateScraper):
    """Scraper for Minnesota state laws from https://www.revisor.mn.gov"""

    _MN_CHAPTER_URL_RE = re.compile(r"/statutes/cite/([0-9A-Za-z]+)$", re.IGNORECASE)
    _MN_SECTION_URL_RE = re.compile(
        r"/statutes/cite/[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)+$",
        re.IGNORECASE,
    )
    _MN_SECTION_NUMBER_RE = re.compile(
        r"/statutes/cite/([0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)+)$",
        re.IGNORECASE,
    )
    _MN_SECTION_ROW_RE = re.compile(
        r"^(?P<section>[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)+)\s+"
        r"(?P<title>.+)$"
    )
    _MN_CHAPTER_RANGE_RE = re.compile(r"\b(?P<start>\d{1,3}[A-Za-z]?)\s*-\s*(?P<end>\d{1,3}[A-Za-z]?)\b")
    OFFICIAL_DOMAIN = "www.revisor.mn.gov"
    OFFICIAL_ENTRY_PATH = "/statutes/"
    OFFICIAL_ENTRY_URL = "https://www.revisor.mn.gov/statutes/"
    # Publication admission is deliberately pinned to the exact edition
    # exposed by the retained current Revisor root.  When Revisor advances the
    # statutes edition, this value and its source audit must be reviewed rather
    # than silently treating a historical archive tree as current law.
    OFFICIAL_EDITION = "2025 Minnesota Statutes"
    OFFICIAL_NUMERIC_CHAPTERS = tuple(range(1, 649))
    OFFICIAL_LETTERED_CHAPTERS = (
        "3A", "3C", "3D", "13A", "16A", "16B", "16C", "16D", "16E", "43A",
        "47A", "60A", "61A", "62A", "62J", "62Q", "65B", "72A", "79A", "80A",
        "82A", "84A", "89A", "97A", "97B", "97C", "103A", "103B", "103C",
        "103D", "103E", "103F", "103G", "103H", "103I", "115A", "115B", "116J",
        "116L", "135A", "136A", "136F", "144A", "144E", "144G", "145A", "147A",
        "148B", "148E", "149A", "168A", "169A", "171A", "216A", "216B", "216C",
        "245A", "245C", "245D", "245G", "252A", "253B", "253D", "256B", "256C",
        "256J", "256L", "256R", "260B", "260C", "260E", "270C", "289A", "290A",
        "297A", "297B", "297E", "297F", "297I", "325D", "325E", "325F", "325G",
        "325L", "325M", "325N", "336A", "462A", "473H", "501C", "508A", "515B",
        "518A", "518B", "518C", "518D", "523A", "609A", "611A", "626A",
    )

    def state_law_frontier_source_dependencies(self) -> Sequence[Any]:
        """Bind parsing, closure, and exact plural acquisition code."""

        from ...web_archiving import wayback_machine_engine
        from . import (
            base_scraper,
            minnesota_section,
            state_archival_fetch,
            strict_frontier_closure,
        )

        return (
            base_scraper,
            state_archival_fetch,
            strict_frontier_closure,
            minnesota_section,
            wayback_machine_engine,
        )

    @staticmethod
    def _minnesota_reports_sha256(reports: Sequence[Mapping[str, Any]]) -> str:
        payload = json.dumps(
            [dict(report) for report in reports],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _minnesota_payload_edition(payload: bytes | bytearray | str) -> str:
        from .minnesota_section import minnesota_statutes_edition_from_html

        html = (
            bytes(payload).decode("utf-8", errors="replace")
            if isinstance(payload, (bytes, bytearray))
            else str(payload or "")
        )
        return minnesota_statutes_edition_from_html(html)

    @classmethod
    def _minnesota_payload_matches_edition(
        cls,
        payload: bytes | bytearray | str,
        *,
        expected_edition: str,
    ) -> bool:
        expected = str(expected_edition or "").strip()
        return bool(expected) and cls._minnesota_payload_edition(payload) == expected

    @classmethod
    def _require_minnesota_payload_edition(
        cls,
        payload: bytes | bytearray | str,
        *,
        expected_edition: str,
        source_url: str,
    ) -> None:
        observed = cls._minnesota_payload_edition(payload)
        expected = str(expected_edition or "").strip()
        if not expected or observed != expected:
            raise RuntimeError(
                "Minnesota parser input has a missing or historical statutes "
                "edition; "
                f"url={source_url} expected={expected!r} observed={observed!r}"
            )

    def _minnesota_exact_frontier(
        self,
        *,
        catalog_report: Mapping[str, Any],
        toc_part_reports: Sequence[Mapping[str, Any]],
        chapter_reports: Sequence[Mapping[str, Any]],
        section_reports: Sequence[Mapping[str, Any]],
        terminal_dispositions: Mapping[str, int],
    ) -> Dict[str, Any]:
        """Build the source-derived root/chapter/leaf closure projection."""

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            compute_frontier_digest,
        )

        catalog_digest = str(catalog_report.get("content_sha256") or "")
        catalog_mode = str(catalog_report.get("catalog_mode") or "")
        edition = str(catalog_report.get("edition") or "").strip()
        if (
            re.fullmatch(r"[0-9a-f]{64}", catalog_digest) is None
            or not str(catalog_report.get("source_url") or "").strip()
            or catalog_mode not in {"direct_chapter_table", "toc_part_tables"}
            or edition != self.OFFICIAL_EDITION
        ):
            raise RuntimeError("Minnesota exact root report is not source-bound")
        if catalog_mode == "direct_chapter_table" and toc_part_reports:
            raise RuntimeError("Minnesota direct chapter table cannot have TOC parts")
        if catalog_mode == "toc_part_tables" and not toc_part_reports:
            raise RuntimeError("Minnesota TOC-part root retained no TOC parts")

        for label, reports, required in (
            ("TOC part", toc_part_reports, False),
            ("chapter", chapter_reports, True),
            ("section", section_reports, True),
        ):
            if required and not reports:
                raise RuntimeError(f"Minnesota exact {label} frontier is empty")
            source_urls = [str(report.get("source_url") or "") for report in reports]
            if (
                any(not source_url for source_url in source_urls)
                or len(source_urls) != len(set(source_urls))
                or any(
                    re.fullmatch(
                        r"[0-9a-f]{64}",
                        str(report.get("content_sha256") or ""),
                    )
                    is None
                    for report in reports
                )
                or any(
                    str(report.get("edition") or "").strip() != edition
                    for report in reports
                )
            ):
                raise RuntimeError(
                    f"Minnesota exact {label} frontier lost URL, digest, or "
                    "edition identity"
                )

        catalog_chapter_count = int(catalog_report.get("chapter_count") or 0)
        toc_chapter_count = sum(
            int(report.get("chapter_count") or 0) for report in toc_part_reports
        )
        chapter_section_count = sum(
            int(report.get("source_section_count") or 0)
            for report in chapter_reports
        )
        if (
            catalog_chapter_count != len(chapter_reports)
            or (
                catalog_mode == "toc_part_tables"
                and toc_chapter_count != len(chapter_reports)
            )
            or chapter_section_count != len(section_reports)
        ):
            raise RuntimeError(
                "Minnesota exact root/chapter/section membership did not reconcile"
            )

        report_dispositions = [
            str(report.get("disposition") or "") for report in section_reports
        ]
        if any(not disposition for disposition in report_dispositions):
            raise RuntimeError("Minnesota exact leaf disposition is missing")

        operative = sum(
            1
            for disposition in report_dispositions
            if disposition == "operative"
        )
        excluded = len(section_reports) - operative
        operative_identities = [
            str(report.get("canonical_identity") or "")
            for report in section_reports
            if str(report.get("disposition") or "") == "operative"
        ]
        if (
            any(not identity for identity in operative_identities)
            or len(operative_identities) != len(set(operative_identities))
        ):
            raise RuntimeError("Minnesota exact operative identities are not unique")
        terminal_total = 0
        for disposition, count in terminal_dispositions.items():
            if not str(disposition or "").strip() or isinstance(count, bool):
                raise RuntimeError("Minnesota terminal disposition is malformed")
            parsed_count = int(count)
            if parsed_count < 0:
                raise RuntimeError("Minnesota terminal disposition is negative")
            terminal_total += parsed_count
        if terminal_total != excluded:
            raise RuntimeError(
                "Minnesota terminal dispositions do not equal excluded leaves"
            )
        disposition = {
            "discovered": len(section_reports),
            "fetched": operative,
            "excluded": excluded,
            "quarantined": 0,
            "failed_final": 0,
            "duplicates": 0,
        }
        if disposition["discovered"] != disposition["fetched"] + disposition["excluded"]:
            raise RuntimeError("Minnesota exact section disposition did not close")
        frontier: Dict[str, Any] = {
            "algebra_closed": True,
            "bundle_closed": False,
            "catalog_content_sha256": catalog_digest,
            "catalog_mode": catalog_mode,
            "chapter_document_count": len(chapter_reports),
            "chapter_frontier_sha256": self._minnesota_reports_sha256(
                chapter_reports
            ),
            "closed": True,
            "disposition": disposition,
            "edition": edition,
            "enumerator_closed": True,
            "expected_index_units": len(section_reports),
            "pagination_closed": True,
            "schema_version": "minnesota-source-derived-html-frontier-v2",
            "scope_closed": True,
            "section_input_frontier_sha256": self._minnesota_reports_sha256(
                section_reports
            ),
            "source_section_count": len(section_reports),
            "terminal_dispositions": dict(sorted(terminal_dispositions.items())),
            "toc_exhausted": True,
            "toc_part_document_count": len(toc_part_reports),
            "toc_part_frontier_sha256": self._minnesota_reports_sha256(
                toc_part_reports
            ),
            "unvisited_continuation_links": [],
            "visited_index_units": len(section_reports),
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return frontier

    def _replay_minnesota_retained_inputs(
        self,
        urls: Sequence[str],
        *,
        frontier_name: str,
    ) -> List[bytes]:
        """Replay exact retained inputs locally without a network fallback."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Minnesota retained replay requires an attached ledger")
        payloads: List[bytes] = []
        for source_url in urls:
            url = self._canonical_fetch_url(source_url)
            retained = ledger.replay_retained_parser_input(
                official_url=url,
                sanitized_request={"method": "GET", "url": url},
            )
            if retained is None:
                raise RuntimeError(
                    f"Minnesota {frontier_name} retained replay is missing: {url}"
                )
            envelope = getattr(retained, "envelope", None)
            raw = bytes(getattr(envelope, "body", None) or b"")
            if not raw:
                raise RuntimeError(
                    f"Minnesota {frontier_name} retained replay is empty: {url}"
                )
            receipt = getattr(retained, "transport_receipt", None)
            if isinstance(receipt, Mapping):
                observed_url = str(
                    receipt.get("official_url") or receipt.get("endpoint") or ""
                ).strip()
                observed_digest = str(receipt.get("content_sha256") or "").strip()
                if observed_url and self._canonical_fetch_url(observed_url) != url:
                    raise RuntimeError(
                        "Minnesota retained replay changed URL identity: "
                        f"expected={url} observed={observed_url}"
                    )
                if observed_digest and observed_digest != hashlib.sha256(raw).hexdigest():
                    raise RuntimeError(
                        f"Minnesota {frontier_name} retained digest changed: {url}"
                    )
            payloads.append(raw)
        return payloads

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._MN_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for Minnesota's legislative website."""
        return "https://www.revisor.mn.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Minnesota."""
        return [{
            "name": "Minnesota Statutes",
            "url": f"{self.get_base_url()}/statutes/cite/609.02",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: int | None = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Minnesota's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        allow_justia = str(
            os.getenv("STATE_SCRAPER_MN_ALLOW_JUSTIA_FALLBACK", "0")
        ).strip().lower() in {"1", "true", "yes", "on"}
        limit = self._effective_scrape_limit(max_statutes, default=420)
        from .minnesota_constitution import (
            configured_constitution_html_path,
            parse_minnesota_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_minnesota_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Minnesota Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .minnesota_section import configured_section_html_path, parse_minnesota_section_html

        local_section = configured_section_html_path()
        if local_section is not None:
            parsed = parse_minnesota_section_html(
                local_section.read_text(encoding="utf-8", errors="replace"),
                source_url="https://www.revisor.mn.gov/statutes/cite/609.185",
                code_name=code_name,
            )
            if parsed is not None:
                return [parsed]
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/statutes/cite/609.02",
            f"{self.get_base_url()}/statutes/",
            f"{self.get_base_url()}/statutes/cite/645.44",
        ]
        # Secondary Justia mirrors are never sole full-corpus admission unless
        # explicitly re-enabled; bounded probes may still use them as last resort.
        if allow_justia or (not self._full_corpus_enabled()):
            candidate_urls.append("https://law.justia.com/codes/minnesota/")

        seen = set()
        merged: List[NormalizedStatute] = []
        merged_keys = set()
        limit = self._effective_scrape_limit(max_statutes, default=420)
        enough = min(80, limit or 80) if limit is not None else 80

        def _merge(items: List[NormalizedStatute]) -> None:
            for statute in items:
                if limit is not None and len(merged) >= limit:
                    return
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if not key or key in merged_keys:
                    continue
                merged_keys.add(key)
                merged.append(statute)

        if limit is not None and self._MN_SECTION_URL_RE.search(str(code_url or "")):
            direct_seed = await self._build_statute_from_section_page(code_name, code_url)
            if direct_seed is not None:
                _merge([direct_seed])
                if limit is not None and len(merged) >= enough:
                    return merged

        chapter_statutes = await self._scrape_chapter_sections(
            code_name,
            max_statutes=limit,
        )
        _merge(chapter_statutes)
        if len(merged) >= enough:
            # Prefer official revisor chapter tree; never sole-admit Justia.
            if self._full_corpus_enabled() and not allow_justia:
                merged = [
                    s for s in merged
                    if "justia.com" not in str(s.source_url or "").lower()
                ]
            return merged if limit is None else merged[: int(limit)]

        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)
            if self._full_corpus_enabled() and "justia.com" in str(candidate).lower() and not allow_justia:
                continue

            if self.has_playwright():
                try:
                    statutes = await self._playwright_scrape(
                        code_name,
                        candidate,
                        "Minn. Stat.",
                        max_sections=limit or 1000000,
                        wait_for_selector="a[href*='/statutes/cite/'], a[href*='/statutes/']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if self._full_corpus_enabled() and not allow_justia:
                        statutes = [
                            s for s in statutes
                            if "justia.com" not in str(s.source_url or "").lower()
                        ]
                    _merge(statutes)
                    if limit is not None and len(merged) >= enough:
                        return merged
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "Minn. Stat.", max_sections=limit or 1000000)
            statutes = self._filter_section_level(statutes)
            if self._full_corpus_enabled() and not allow_justia:
                statutes = [
                    s for s in statutes
                    if "justia.com" not in str(s.source_url or "").lower()
                ]
            _merge(statutes)
            if limit is not None and len(merged) >= enough:
                return merged

        return merged if limit is None else merged[: int(limit)]

    async def _scrape_chapter_sections(
        self,
        code_name: str,
        max_statutes: Optional[int],
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        if limit is None:
            self._minnesota_frontier_batch_stats: List[Dict[str, Any]] = []
            self._last_minnesota_discovery_input = None
            self._last_minnesota_statutes_edition = ""
        self._last_minnesota_catalog_terminal_sections: Dict[
            str, Dict[str, str]
        ] = {}
        self._last_minnesota_detail_terminal_sections: Dict[
            str, Dict[str, Any]
        ] = {}

        def _terminal_progress() -> Dict[str, Any]:
            terminal = {
                **dict(self._last_minnesota_catalog_terminal_sections),
                **dict(self._last_minnesota_detail_terminal_sections),
            }
            disposition_counts: Dict[str, int] = {}
            for record in terminal.values():
                disposition = str(record.get("disposition") or "").strip()
                if disposition:
                    disposition_counts[disposition] = (
                        disposition_counts.get(disposition, 0) + 1
                    )
            return {
                "terminal_sections_excluded": int(len(terminal)),
                "terminal_section_urls": sorted(terminal),
                "terminal_disposition_counts": disposition_counts,
            }

        chapter_budget = (
            None
            if limit is None
            else limit if self._full_corpus_enabled() else min(limit, 24)
        )
        chapter_urls = await self._discover_chapter_urls(
            max_chapters=(
                None if chapter_budget is None else max(1, int(chapter_budget))
            )
        )
        if not chapter_urls:
            if limit is None:
                raise RuntimeError(
                    "Minnesota official chapter frontier discovery returned no chapters"
                )
            chapter_urls = [
                f"{self.get_base_url()}/statutes/cite/609",
                f"{self.get_base_url()}/statutes/cite/645",
                f"{self.get_base_url()}/statutes/cite/518",
                f"{self.get_base_url()}/statutes/cite/518B",
                f"{self.get_base_url()}/statutes/cite/169A",
                f"{self.get_base_url()}/statutes/cite/8",
                f"{self.get_base_url()}/statutes/cite/13",
                f"{self.get_base_url()}/statutes/cite/144",
                f"{self.get_base_url()}/statutes/cite/325F",
            ]
        if limit is None and len(chapter_urls) != len(set(chapter_urls)):
            raise RuntimeError(
                "Minnesota official chapter frontier repeated a chapter URL"
            )
        expected_edition = str(
            getattr(self, "_last_minnesota_statutes_edition", "") or ""
        ).strip()
        if (
            limit is None
            and getattr(self, "_state_law_acquisition_ledger", None) is not None
            and expected_edition != self.OFFICIAL_EDITION
        ):
            raise RuntimeError(
                "Minnesota exact crawl lacks the pinned current statutes edition"
            )
        self.logger.info(
            "Minnesota chapter crawl: discovered_chapters=%s max_statutes=%s",
            len(chapter_urls),
            limit or "unbounded",
        )

        section_urls: List[str] = []
        seen_urls = set()
        chapters_scanned = 0
        chapter_reports: List[Dict[str, Any]] = []
        catalog_terminal_reports: List[Dict[str, Any]] = []

        def _record_chapter_payload(chapter_url: str, payload: Any) -> None:
            nonlocal chapters_scanned
            chapters_scanned += 1
            html = (
                payload.decode("utf-8", errors="replace")
                if isinstance(payload, (bytes, bytearray))
                else str(payload)
            )
            raw = (
                bytes(payload)
                if isinstance(payload, (bytes, bytearray))
                else html.encode("utf-8")
            )
            if limit is None and expected_edition:
                self._require_minnesota_payload_edition(
                    raw,
                    expected_edition=expected_edition,
                    source_url=chapter_url,
                )
            terminal: Dict[str, Dict[str, str]] = {}
            if limit is None:
                terminal = (
                    _source_bound_terminal_sections_from_chapter_catalog_html(
                        html,
                        source_url=chapter_url,
                    )
                )
                if terminal:
                    self._last_minnesota_catalog_terminal_sections.update(
                        terminal
                    )
            soup = BeautifulSoup(html, "html.parser")
            discovered_section_urls = self._extract_section_urls_from_chapter_page(
                soup
            )
            if limit is None:
                chapter_reports.append(
                    {
                        "content_sha256": hashlib.sha256(raw).hexdigest(),
                        "edition": expected_edition,
                        "source_section_count": len(discovered_section_urls),
                        "source_url": chapter_url,
                        "terminal_catalog_sections": len(terminal),
                    }
                )
            for section_url in discovered_section_urls:
                if section_url in terminal:
                    if limit is None:
                        record = dict(terminal[section_url])
                        catalog_terminal_reports.append(
                            {
                                "canonical_identity": "",
                                "content_sha256": str(
                                    record.get("catalog_content_sha256") or ""
                                ),
                                "disposition": str(
                                    record.get("disposition") or "renumbered"
                                ),
                                "edition": expected_edition,
                                "evidence_kind": "source_bound_chapter_catalog",
                                "evidence_source_url": chapter_url,
                                "section_number": str(
                                    record.get("section_number") or ""
                                ),
                                "source_url": section_url,
                            }
                        )
                    continue
                if section_url in seen_urls:
                    if limit is None:
                        raise RuntimeError(
                            "Minnesota official chapter frontier repeated a section URL: "
                            f"{section_url}"
                        )
                    continue
                seen_urls.add(section_url)
                section_urls.append(section_url)
                if limit is not None and len(section_urls) >= limit:
                    break

        if limit is None:
            chapter_payloads = await self._fetch_minnesota_frontier_in_chunks(
                chapter_urls,
                frontier_name="chapter-index",
                expected_edition=expected_edition,
            )
            for _chapter_url, payload in zip(
                chapter_urls,
                chapter_payloads,
                strict=True,
            ):
                _record_chapter_payload(_chapter_url, payload)
        else:
            for chapter_url in chapter_urls:
                if len(section_urls) >= limit:
                    break
                try:
                    payload = await self._fetch_page_content_with_archival_fallback(
                        chapter_url,
                        timeout_seconds=35,
                    )
                except Exception:
                    continue
                if not payload:
                    continue
                _record_chapter_payload(chapter_url, payload)

        if not section_urls:
            if limit is None:
                self._write_partial_checkpoint(
                    [],
                    code_name=code_name,
                    stage_label="minnesota:complete",
                    force=True,
                    extra={
                        "chapters_scanned": int(chapters_scanned),
                        "discovered_chapters": int(len(chapter_urls)),
                        "sections_scanned": 0,
                        "discovered_sections": 0,
                        "codes_completed": 1,
                        "codes_total": 1,
                        **_terminal_progress(),
                    },
                )
            return []

        statutes: List[NormalizedStatute] = []
        sections_scanned = 0
        if limit is None:
            from .minnesota_section import (
                classify_minnesota_terminal_section_html,
            )

            section_reports: List[Dict[str, Any]] = list(
                catalog_terminal_reports
            )
            terminal_counts: Dict[str, int] = {}
            for report in catalog_terminal_reports:
                disposition = str(report.get("disposition") or "renumbered")
                terminal_counts[disposition] = terminal_counts.get(disposition, 0) + 1
            seen_identities: set[str] = set()
            residual_sections: List[Dict[str, str]] = []
            batch_size = self._minnesota_frontier_batch_size()
            # Acquire the exact source-ordered cross-chapter union once.  The
            # bounded slices below are deliberately parsing/checkpoint units,
            # not acquisition units, so grouped archive inventory and WARC
            # reuse span the entire known leaf frontier.
            section_payloads = await self._fetch_minnesota_frontier_batch(
                section_urls,
                frontier_name="section",
                expected_edition=expected_edition,
            )
            for batch_start in range(0, len(section_urls), batch_size):
                batch_urls = section_urls[batch_start : batch_start + batch_size]
                batch_payloads = section_payloads[
                    batch_start : batch_start + batch_size
                ]
                for section_url, payload in zip(
                    batch_urls,
                    batch_payloads,
                    strict=True,
                ):
                    sections_scanned += 1
                    raw = bytes(payload)
                    decoded = raw.decode("utf-8", errors="replace")
                    content_sha256 = hashlib.sha256(raw).hexdigest()
                    if expected_edition:
                        self._require_minnesota_payload_edition(
                            raw,
                            expected_edition=expected_edition,
                            source_url=section_url,
                        )
                    result = self._build_statute_from_section_html(
                        code_name,
                        section_url,
                        decoded,
                        expected_edition=expected_edition,
                        strict_source_bound=True,
                    )
                    if result is not None:
                        expected_match = self._MN_SECTION_NUMBER_RE.search(
                            section_url
                        )
                        expected_number = (
                            expected_match.group(1) if expected_match else ""
                        )
                        identity = str(result.section_number or "").strip()
                        if (
                            not identity
                            or identity.casefold() in seen_identities
                            or identity.casefold() != expected_number.casefold()
                        ):
                            raise RuntimeError(
                                "Minnesota normalized section identity changed or repeated: "
                                f"url={section_url} parsed={identity!r}"
                            )
                        seen_identities.add(identity.casefold())
                        result.structured_data = {
                            **dict(result.structured_data or {}),
                            "content_sha256": content_sha256,
                        }
                        statutes.append(result)
                        section_reports.append(
                            {
                                "canonical_identity": identity.casefold(),
                                "content_sha256": content_sha256,
                                "disposition": "operative",
                                "edition": expected_edition,
                                "section_number": identity,
                                "source_url": section_url,
                            }
                        )
                    else:
                        terminal = classify_minnesota_terminal_section_html(
                            decoded,
                            source_url=section_url,
                            expected_edition=expected_edition,
                        )
                        if terminal is None:
                            residual_sections.append(
                                {
                                    "content_sha256": content_sha256,
                                    "source_url": section_url,
                                }
                            )
                        else:
                            disposition = str(terminal["disposition"])
                            terminal_counts[disposition] = (
                                terminal_counts.get(disposition, 0) + 1
                            )
                            self._last_minnesota_detail_terminal_sections[
                                section_url
                            ] = dict(terminal)
                            section_reports.append(
                                {
                                    "canonical_identity": "",
                                    "content_sha256": content_sha256,
                                    "disposition": disposition,
                                    "edition": expected_edition,
                                    "evidence_kind": "source_reference_page",
                                    "section_number": str(
                                        terminal.get("section_number") or ""
                                    ),
                                    "source_blocks": int(
                                        terminal.get("source_blocks") or 0
                                    ),
                                    "source_url": section_url,
                                }
                            )
                    if len(statutes) == 1 or len(statutes) % 25 == 0:
                        self.logger.info(
                            "Minnesota chapter crawl: "
                            "scanned_sections=%s/%s statutes_so_far=%s",
                            sections_scanned,
                            len(section_urls),
                            len(statutes),
                        )
                self._write_partial_checkpoint(
                    statutes,
                    code_name=code_name,
                    stage_label="minnesota:section-progress",
                    extra={
                        "chapters_scanned": int(chapters_scanned),
                        "discovered_chapters": int(len(chapter_urls)),
                        "sections_scanned": int(sections_scanned),
                        "discovered_sections": int(len(section_urls)),
                        "codes_completed": 0,
                        "codes_total": 1,
                        **_terminal_progress(),
                    },
                )
                if residual_sections:
                    raise RuntimeError(
                        "Minnesota official leaf frontier has unclassified residuals: "
                        f"{residual_sections[:10]}"
                    )
        else:
            for section_index, section_url in enumerate(
                section_urls[:limit],
                start=1,
            ):
                try:
                    result = await self._build_statute_from_section_page(
                        code_name,
                        section_url,
                    )
                except Exception:
                    continue
                sections_scanned = section_index
                if result is None:
                    continue
                statutes.append(result)
                if len(statutes) == 1 or len(statutes) % 25 == 0:
                    self.logger.info(
                        "Minnesota chapter crawl: "
                        "scanned_sections=%s/%s statutes_so_far=%s",
                        section_index,
                        min(len(section_urls), limit),
                        len(statutes),
                    )
                if len(statutes) >= limit:
                    break

        if limit is None:
            discovery = getattr(self, "_last_minnesota_discovery_input", None)
            if not isinstance(discovery, Mapping):
                if getattr(self, "_state_law_acquisition_ledger", None) is not None:
                    raise RuntimeError(
                        "Minnesota root/TOC discovery input was not retained"
                    )
            else:
                catalog_report = discovery.get("catalog_report")
                toc_part_reports = discovery.get("toc_part_reports")
                if not isinstance(catalog_report, Mapping) or not isinstance(
                    toc_part_reports, Sequence
                ):
                    raise RuntimeError(
                        "Minnesota retained root/TOC discovery report is incomplete"
                    )
                if len(section_reports) != len(section_urls) + len(
                    catalog_terminal_reports
                ):
                    raise RuntimeError(
                        "Minnesota source leaf membership did not reconcile"
                    )
                exact_frontier = self._minnesota_exact_frontier(
                    catalog_report=catalog_report,
                    toc_part_reports=[dict(row) for row in toc_part_reports],
                    chapter_reports=chapter_reports,
                    section_reports=section_reports,
                    terminal_dispositions=terminal_counts,
                )
                observed_at = datetime.now(timezone.utc).isoformat()
                self._last_minnesota_full_frontier = {
                    "boundary_first": str(section_urls[0]),
                    "boundary_last": str(section_urls[-1]),
                    "catalog_report": dict(catalog_report),
                    "chapter_reports": chapter_reports,
                    "code_name": code_name,
                    "edition": expected_edition,
                    "frontier": exact_frontier,
                    "observed_at": observed_at,
                    "section_reports": section_reports,
                    "toc_part_reports": [
                        dict(row) for row in toc_part_reports
                    ],
                    "transport_batch_stats": list(
                        self._minnesota_frontier_batch_stats
                    ),
                }
                self._last_minnesota_strict_closure = {
                    "chapter_documents": len(chapter_reports),
                    "closed": True,
                    "frontier": exact_frontier,
                    "observed_at": observed_at,
                    "operative_sections": len(statutes),
                    "schema": "minnesota-source-derived-strict-closure-v2",
                    "source_sections": len(section_reports),
                    "terminal_sections": len(section_reports) - len(statutes),
                    "unclassified_sections": 0,
                }
            self._write_partial_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="minnesota:complete",
                force=True,
                extra={
                    "chapters_scanned": int(chapters_scanned),
                    "discovered_chapters": int(len(chapter_urls)),
                    "sections_scanned": int(sections_scanned),
                    "discovered_sections": int(len(section_urls)),
                    "codes_completed": 1,
                    "codes_total": 1,
                    **_terminal_progress(),
                },
            )

        return statutes

    def _replay_minnesota_source_frontier(
        self,
        first: Mapping[str, Any],
    ) -> List[NormalizedStatute]:
        """Reparse the exact retained root, hierarchy, and leaf inputs."""

        from .minnesota_section import (
            chapter_table_rows,
            classify_minnesota_terminal_section_html,
            toc_part_rows,
        )

        catalog_report_raw = first.get("catalog_report")
        toc_reports_raw = first.get("toc_part_reports")
        chapter_reports_raw = first.get("chapter_reports")
        first_section_reports_raw = first.get("section_reports")
        if not isinstance(catalog_report_raw, Mapping):
            raise RuntimeError("Minnesota retained root report is incomplete")
        for label, reports in (
            ("TOC part", toc_reports_raw),
            ("chapter", chapter_reports_raw),
            ("section", first_section_reports_raw),
        ):
            if (
                not isinstance(reports, Sequence)
                or isinstance(reports, (str, bytes, bytearray))
                or any(not isinstance(row, Mapping) for row in reports)
            ):
                raise RuntimeError(
                    f"Minnesota retained {label} reports are incomplete"
                )
        catalog_report = dict(catalog_report_raw)
        expected_edition = str(catalog_report.get("edition") or "").strip()
        if expected_edition != self.OFFICIAL_EDITION:
            raise RuntimeError(
                "Minnesota retained root report lacks the pinned current edition"
            )
        expected_toc_reports = [dict(row) for row in toc_reports_raw]
        expected_chapter_reports = [dict(row) for row in chapter_reports_raw]
        expected_section_reports = [dict(row) for row in first_section_reports_raw]
        if not expected_chapter_reports or not expected_section_reports:
            raise RuntimeError("Minnesota retained source frontier is empty")

        root_url = str(catalog_report.get("source_url") or "")
        root_raw = self._replay_minnesota_retained_inputs(
            [root_url],
            frontier_name="root-index",
        )[0]
        root_digest = hashlib.sha256(root_raw).hexdigest()
        if root_digest != str(catalog_report.get("content_sha256") or ""):
            raise RuntimeError("Minnesota retained root digest changed")
        self._require_minnesota_payload_edition(
            root_raw,
            expected_edition=expected_edition,
            source_url=root_url,
        )
        root_html = root_raw.decode("utf-8", errors="replace")
        catalog_mode = str(catalog_report.get("catalog_mode") or "")

        replay_toc_reports: List[Dict[str, Any]] = []
        chapter_urls: List[str] = []
        if catalog_mode == "direct_chapter_table":
            chapter_urls = [url for _number, _name, url in chapter_table_rows(root_html)]
            if expected_toc_reports:
                raise RuntimeError(
                    "Minnesota direct root unexpectedly retained TOC part reports"
                )
        elif catalog_mode == "toc_part_tables":
            toc_rows = toc_part_rows(root_html)
            toc_urls = [url for url, _chapter_range, _name in toc_rows]
            expected_toc_urls = [
                str(report.get("source_url") or "")
                for report in expected_toc_reports
            ]
            if toc_urls != expected_toc_urls:
                raise RuntimeError("Minnesota retained TOC part membership changed")
            toc_payloads = self._replay_minnesota_retained_inputs(
                toc_urls,
                frontier_name="toc-parts",
            )
            seen_chapters: set[str] = set()
            for part_url, part_raw in zip(toc_urls, toc_payloads, strict=True):
                self._require_minnesota_payload_edition(
                    part_raw,
                    expected_edition=expected_edition,
                    source_url=part_url,
                )
                rows = chapter_table_rows(
                    part_raw.decode("utf-8", errors="replace")
                )
                replay_toc_reports.append(
                    {
                        "chapter_count": len(rows),
                        "content_sha256": hashlib.sha256(part_raw).hexdigest(),
                        "edition": expected_edition,
                        "source_url": part_url,
                    }
                )
                for _number, _name, chapter_url in rows:
                    if chapter_url in seen_chapters:
                        raise RuntimeError(
                            "Minnesota retained TOC replay repeated a chapter URL: "
                            f"{chapter_url}"
                        )
                    seen_chapters.add(chapter_url)
                    chapter_urls.append(chapter_url)
        else:
            raise RuntimeError(
                f"Minnesota retained root has unknown catalog mode: {catalog_mode!r}"
            )

        expected_chapter_urls = [
            str(report.get("source_url") or "")
            for report in expected_chapter_reports
        ]
        if chapter_urls != expected_chapter_urls:
            raise RuntimeError("Minnesota retained chapter membership changed")
        chapter_payloads = self._replay_minnesota_retained_inputs(
            chapter_urls,
            frontier_name="chapter-indexes",
        )

        from bs4 import BeautifulSoup

        replay_chapter_reports: List[Dict[str, Any]] = []
        catalog_terminal_reports: List[Dict[str, Any]] = []
        section_urls: List[str] = []
        seen_section_urls: set[str] = set()
        for chapter_url, raw in zip(chapter_urls, chapter_payloads, strict=True):
            self._require_minnesota_payload_edition(
                raw,
                expected_edition=expected_edition,
                source_url=chapter_url,
            )
            decoded = raw.decode("utf-8", errors="replace")
            terminal = _source_bound_terminal_sections_from_chapter_catalog_html(
                decoded,
                source_url=chapter_url,
            )
            discovered = self._extract_section_urls_from_chapter_page(
                BeautifulSoup(decoded, "html.parser")
            )
            replay_chapter_reports.append(
                {
                    "content_sha256": hashlib.sha256(raw).hexdigest(),
                    "edition": expected_edition,
                    "source_section_count": len(discovered),
                    "source_url": chapter_url,
                    "terminal_catalog_sections": len(terminal),
                }
            )
            for section_url in discovered:
                if section_url in terminal:
                    record = dict(terminal[section_url])
                    catalog_terminal_reports.append(
                        {
                            "canonical_identity": "",
                            "content_sha256": str(
                                record.get("catalog_content_sha256") or ""
                            ),
                            "disposition": str(
                                record.get("disposition") or "renumbered"
                            ),
                            "edition": expected_edition,
                            "evidence_kind": "source_bound_chapter_catalog",
                            "evidence_source_url": chapter_url,
                            "section_number": str(
                                record.get("section_number") or ""
                            ),
                            "source_url": section_url,
                        }
                    )
                    continue
                if section_url in seen_section_urls:
                    raise RuntimeError(
                        "Minnesota retained chapter replay repeated a section URL: "
                        f"{section_url}"
                    )
                seen_section_urls.add(section_url)
                section_urls.append(section_url)

        expected_leaf_urls = [
            str(report.get("source_url") or "")
            for report in expected_section_reports
            if str(report.get("evidence_kind") or "")
            != "source_bound_chapter_catalog"
        ]
        if section_urls != expected_leaf_urls:
            raise RuntimeError("Minnesota retained leaf membership changed")
        section_payloads = self._replay_minnesota_retained_inputs(
            section_urls,
            frontier_name="section-pages",
        )

        replay_rows: List[NormalizedStatute] = []
        replay_section_reports: List[Dict[str, Any]] = list(
            catalog_terminal_reports
        )
        terminal_counts: Dict[str, int] = {}
        for report in catalog_terminal_reports:
            disposition = str(report.get("disposition") or "renumbered")
            terminal_counts[disposition] = terminal_counts.get(disposition, 0) + 1
        seen_identities: set[str] = set()
        code_name = str(first.get("code_name") or "Minnesota Statutes")
        for section_url, raw in zip(section_urls, section_payloads, strict=True):
            self._require_minnesota_payload_edition(
                raw,
                expected_edition=expected_edition,
                source_url=section_url,
            )
            decoded = raw.decode("utf-8", errors="replace")
            content_sha256 = hashlib.sha256(raw).hexdigest()
            statute = self._build_statute_from_section_html(
                code_name,
                section_url,
                decoded,
                expected_edition=expected_edition,
                strict_source_bound=True,
            )
            if statute is not None:
                expected_match = self._MN_SECTION_NUMBER_RE.search(section_url)
                expected_number = expected_match.group(1) if expected_match else ""
                identity = str(statute.section_number or "").strip()
                if (
                    not identity
                    or identity.casefold() in seen_identities
                    or identity.casefold() != expected_number.casefold()
                ):
                    raise RuntimeError(
                        "Minnesota retained replay changed normalized identity: "
                        f"{section_url}"
                    )
                seen_identities.add(identity.casefold())
                statute.structured_data = {
                    **dict(statute.structured_data or {}),
                    "content_sha256": content_sha256,
                }
                replay_rows.append(statute)
                replay_section_reports.append(
                    {
                        "canonical_identity": identity.casefold(),
                        "content_sha256": content_sha256,
                        "disposition": "operative",
                        "edition": expected_edition,
                        "section_number": identity,
                        "source_url": section_url,
                    }
                )
                continue
            terminal = classify_minnesota_terminal_section_html(
                decoded,
                source_url=section_url,
                expected_edition=expected_edition,
            )
            if terminal is None:
                raise RuntimeError(
                    "Minnesota retained leaf replay left an unclassified residual: "
                    f"{section_url}"
                )
            disposition = str(terminal["disposition"])
            terminal_counts[disposition] = terminal_counts.get(disposition, 0) + 1
            replay_section_reports.append(
                {
                    "canonical_identity": "",
                    "content_sha256": content_sha256,
                    "disposition": disposition,
                    "edition": expected_edition,
                    "evidence_kind": "source_reference_page",
                    "section_number": str(
                        terminal.get("section_number") or ""
                    ),
                    "source_blocks": int(terminal.get("source_blocks") or 0),
                    "source_url": section_url,
                }
            )

        replay_catalog_report = {
            **catalog_report,
            "content_sha256": root_digest,
        }
        replayed_frontier = self._minnesota_exact_frontier(
            catalog_report=replay_catalog_report,
            toc_part_reports=replay_toc_reports,
            chapter_reports=replay_chapter_reports,
            section_reports=replay_section_reports,
            terminal_dispositions=terminal_counts,
        )
        self._last_minnesota_replayed_frontier = {
            "frontier": replayed_frontier,
            "section_reports": replay_section_reports,
        }
        return replay_rows

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection: Mapping[str, Any],
    ) -> Optional[Path]:
        """Replay retained Revisor inputs and seal exact publication parity."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Minnesota frontier closure requires an attached ledger")
        first = getattr(self, "_last_minnesota_full_frontier", None)
        if not isinstance(first, Mapping):
            raise RuntimeError(
                "Minnesota source-derived strict frontier was not retained before output"
            )
        refresh = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh):
            refresh()
        replay_rows = self._replay_minnesota_source_frontier(first)
        replay = getattr(self, "_last_minnesota_replayed_frontier", None)
        if not isinstance(replay, Mapping):
            raise RuntimeError("Minnesota retained source replay did not close")
        first_frontier = first.get("frontier")
        replayed_frontier = replay.get("frontier")
        if not isinstance(first_frontier, Mapping) or not isinstance(
            replayed_frontier, Mapping
        ):
            raise RuntimeError("Minnesota exact frontier observations are incomplete")

        from .strict_frontier_closure import retain_exact_state_frontier_closure

        observed_at = str(first.get("observed_at") or "")
        edition = str(first.get("edition") or "").strip()
        if edition != self.OFFICIAL_EDITION:
            raise RuntimeError(
                "Minnesota closure cannot stamp an unpinned statutes edition as current"
            )
        batch_stats = [
            dict(row) for row in first.get("transport_batch_stats") or []
        ]

        def _wave_count(frontier_name: str) -> int:
            return sum(
                str(row.get("frontier_name") or "") == frontier_name
                for row in batch_stats
            )

        return retain_exact_state_frontier_closure(
            self,
            canonical_output_projection=canonical_output_projection,
            first_frontier=first_frontier,
            replayed_frontier=replayed_frontier,
            replay_rows=replay_rows,
            jurisdiction="MN",
            source_domain=self.OFFICIAL_DOMAIN,
            official_source_url=self.OFFICIAL_ENTRY_URL,
            observed_at=observed_at,
            legal_as_of=observed_at[:10],
            edition=edition,
            boundary_first=str(first.get("boundary_first") or ""),
            boundary_last=str(first.get("boundary_last") or ""),
            bundle_total=len(list(first.get("chapter_reports") or [])),
            pagination_total=len(list(first.get("section_reports") or [])),
            transport={
                "fixture": False,
                "chapter_acquisition_wave_count": _wave_count("chapter-index"),
                "first_pass_request_batches": len(batch_stats),
                "first_pass_requested_pages": sum(
                    int(row.get("requested_pages") or 0) for row in batch_stats
                ),
                "first_pass_batch_stats": batch_stats,
                "grouped_warc_recovery": True,
                "historical_archive_edition_admission": False,
                "leaf_acquisition_wave_count": _wave_count("section"),
                "kind": "shared_archive_aware_plural_html",
                "per_page_archive_loop": False,
                "repeat_grouped_archive_inventory_on_residual": False,
                "residual_only_retries": True,
                "retained_replay_network_requests": 0,
                "source_ordered_cross_parent_union": True,
                "statutes_edition": edition,
                "statutes_edition_guard": True,
                "synthetic": False,
                "toc_part_acquisition_wave_count": _wave_count("toc-part"),
                "wayback_prefix_inventory": True,
            },
        )

    def _minnesota_frontier_batch_size(self) -> int:
        return max(
            1,
            min(
                512,
                int(
                    self._env_int(
                        "STATE_SCRAPER_MN_FRONTIER_BATCH_SIZE",
                        default=64,
                    )
                    or 64
                ),
            ),
        )

    def _minnesota_frontier_concurrency(self) -> int:
        return max(
            1,
            min(
                64,
                int(
                    self._env_int(
                        "STATE_SCRAPER_MN_FRONTIER_CONCURRENCY",
                        default=8,
                    )
                    or 8
                ),
            ),
        )

    async def _fetch_minnesota_frontier_batch(
        self,
        urls: List[str],
        *,
        frontier_name: str,
        expected_edition: str = "",
    ) -> List[bytes]:
        if not urls:
            return []
        requested = list(urls)
        canonical = [self._canonical_fetch_url(url) for url in requested]
        if (
            any(not url for url in canonical)
            or any(
                (urlparse(url).hostname or "").casefold()
                != self.OFFICIAL_DOMAIN.casefold()
                for url in canonical
            )
            or len(set(canonical)) != len(canonical)
        ):
            raise RuntimeError(
                f"Minnesota {frontier_name} frontier contains an invalid, "
                "off-domain, or duplicate exact URL"
            )
        residual_retry_attempts = max(
            0,
            min(
                3,
                self._env_int(
                    "STATE_SCRAPER_MN_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
                    default=self._env_int(
                        "STATE_SCRAPER_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
                        default=1,
                    ),
                ),
            ),
        )
        fetch_kwargs: Dict[str, Any] = {
            "timeout_seconds": 35,
            "media_type": "text/html",
            "max_concurrency": self._minnesota_frontier_concurrency(),
            "prefer_direct": True,
            "common_crawl_domain_terms": ("www.revisor.mn.gov",),
            "common_crawl_url_terms": ("/statutes/",),
            "common_crawl_mime_terms": ("html",),
            "wayback_prefix_inventory": True,
        }
        normalized_edition = str(expected_edition or "").strip()
        if normalized_edition:
            fetch_kwargs["content_validator"] = lambda payload: (
                self._minnesota_payload_matches_edition(
                    payload,
                    expected_edition=normalized_edition,
                )
            )
        batch = await self._fetch_page_contents_with_archival_fallback_retrying_residuals(
            requested,
            residual_retry_attempts=residual_retry_attempts,
            repeat_grouped_archive_inventory_on_residual=False,
            **fetch_kwargs,
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
                f"Minnesota {frontier_name} frontier returned unaligned acquisition rows"
            )
        if list(batch.urls) != requested:
            raise RuntimeError(
                f"Minnesota {frontier_name} frontier changed URL order or identity"
            )
        stats = dict(batch.stats or {})
        stats["frontier_name"] = str(frontier_name)
        batch_stats = getattr(self, "_minnesota_frontier_batch_stats", None)
        if isinstance(batch_stats, list):
            batch_stats.append(stats)
        failures: List[Dict[str, str]] = []
        for url, payload, error in zip(
            batch.urls,
            batch.payloads,
            batch.errors,
            strict=True,
        ):
            failure = str(error or "")
            if not payload and not failure:
                failure = "empty parser input"
            if (
                not failure
                and normalized_edition
                and not self._minnesota_payload_matches_edition(
                    payload,
                    expected_edition=normalized_edition,
                )
            ):
                observed = self._minnesota_payload_edition(payload)
                failure = (
                    "missing or historical Minnesota Statutes edition "
                    f"(expected {normalized_edition!r}, observed {observed!r})"
                )
            if failure:
                failures.append({"url": url, "error": failure})
        if failures:
            raise RuntimeError(
                f"Minnesota {frontier_name} frontier is incomplete; "
                f"unresolved exact URLs: {failures}"
            )
        return [bytes(payload) for payload in batch.payloads]

    async def _fetch_minnesota_frontier_in_chunks(
        self,
        urls: List[str],
        *,
        frontier_name: str,
        expected_edition: str = "",
    ) -> List[bytes]:
        """Acquire one exact, source-ordered frontier in one plural wave.

        The historical method name is retained for state-local compatibility.
        Exact frontier calls must not split a known same-domain union: doing so
        would repeat archive inventories and prevent cross-parent WARC reuse.
        Parsing/checkpoint work remains bounded independently.
        """

        return await self._fetch_minnesota_frontier_batch(
            list(urls),
            frontier_name=frontier_name,
            expected_edition=expected_edition,
        )

    async def _discover_chapter_urls(
        self,
        max_chapters: Optional[int],
    ) -> List[str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        limit = max(1, int(max_chapters)) if max_chapters is not None else None
        index_url = f"{self.get_base_url()}/statutes/"
        root_fetch_kwargs: Dict[str, Any] = {"timeout_seconds": 35}
        if limit is None:
            root_fetch_kwargs["content_validator"] = lambda body: (
                self._minnesota_payload_matches_edition(
                    body,
                    expected_edition=self.OFFICIAL_EDITION,
                )
            )
        try:
            payload = await self._fetch_page_content_with_archival_fallback(
                index_url,
                **root_fetch_kwargs,
            )
        except Exception as exc:
            if limit is None:
                raise RuntimeError(
                    "Minnesota official statutes index acquisition failed"
                ) from exc
            return []
        if not payload:
            if limit is None:
                raise RuntimeError(
                    "Minnesota official statutes index acquisition returned no parser input"
                )
            return []

        html = (
            payload.decode("utf-8", errors="replace")
            if isinstance(payload, (bytes, bytearray))
            else str(payload)
        )
        root_raw = (
            bytes(payload)
            if isinstance(payload, (bytes, bytearray))
            else html.encode("utf-8")
        )
        root_edition = self._minnesota_payload_edition(root_raw)

        def _activate_exact_edition() -> None:
            if limit is not None:
                return
            self._require_minnesota_payload_edition(
                root_raw,
                expected_edition=self.OFFICIAL_EDITION,
                source_url=index_url,
            )
            self._last_minnesota_statutes_edition = root_edition

        def _retain_discovery(
            chapter_urls: Sequence[str],
            *,
            catalog_mode: str,
            toc_part_reports: Sequence[Mapping[str, Any]] = (),
        ) -> None:
            if limit is not None:
                return
            self._last_minnesota_discovery_input = {
                "catalog_report": {
                    "catalog_mode": str(catalog_mode),
                    "chapter_count": len(chapter_urls),
                    "content_sha256": hashlib.sha256(root_raw).hexdigest(),
                    "edition": root_edition,
                    "source_url": index_url,
                },
                "chapter_urls": list(chapter_urls),
                "toc_part_reports": [dict(row) for row in toc_part_reports],
            }

        from .minnesota_section import chapter_table_rows, toc_part_rows

        listed = chapter_table_rows(html)
        if listed:
            _activate_exact_edition()
            chapter_urls = [url for _number, _name, url in listed]
            _retain_discovery(chapter_urls, catalog_mode="direct_chapter_table")
            return chapter_urls if limit is None else chapter_urls[:limit]
        parts = toc_part_rows(html)
        if parts:
            _activate_exact_edition()
            chapter_urls: List[str] = []
            seen = set()
            part_urls = [part_url for part_url, _range, _name in parts]
            if limit is not None:
                for part_url in part_urls:
                    if len(chapter_urls) >= limit:
                        break
                    part_payload = await self._fetch_page_content_with_archival_fallback(
                        part_url,
                        timeout_seconds=35,
                    )
                    if not part_payload:
                        continue
                    part_html = (
                        part_payload.decode("utf-8", errors="replace")
                        if isinstance(part_payload, (bytes, bytearray))
                        else str(part_payload)
                    )
                    for _number, _name, url in chapter_table_rows(part_html):
                        if url in seen:
                            continue
                        seen.add(url)
                        chapter_urls.append(url)
                        if len(chapter_urls) >= limit:
                            break
                if chapter_urls:
                    return chapter_urls
            else:
                part_payloads = await self._fetch_minnesota_frontier_in_chunks(
                    part_urls,
                    frontier_name="toc-part",
                    expected_edition=root_edition,
                )
                toc_part_reports: List[Dict[str, Any]] = []
                part_rows = zip(part_urls, part_payloads, strict=True)
                for _part_url, part_payload in part_rows:
                    part_html = part_payload.decode("utf-8", errors="replace")
                    chapter_rows = chapter_table_rows(part_html)
                    toc_part_reports.append(
                        {
                            "chapter_count": len(chapter_rows),
                            "content_sha256": hashlib.sha256(part_payload).hexdigest(),
                            "edition": root_edition,
                            "source_url": _part_url,
                        }
                    )
                    for _number, _name, url in chapter_rows:
                        if url in seen:
                            raise RuntimeError(
                                "Minnesota TOC parts repeated an official chapter URL: "
                                f"{url}"
                            )
                        seen.add(url)
                        chapter_urls.append(url)
                if chapter_urls:
                    _retain_discovery(
                        chapter_urls,
                        catalog_mode="toc_part_tables",
                        toc_part_reports=toc_part_reports,
                    )
                    return chapter_urls
        soup = BeautifulSoup(payload, "html.parser")
        chapter_urls = []
        seen = set()

        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            match = self._MN_CHAPTER_URL_RE.search(href)
            if not match:
                continue
            chapter_token = match.group(1)
            if "." in chapter_token:
                continue
            full_url = href if href.startswith("http") else f"{self.get_base_url()}{href}"
            if full_url in seen:
                continue
            seen.add(full_url)
            chapter_urls.append(full_url)
            if limit is not None and len(chapter_urls) >= limit:
                return chapter_urls

        page_text = "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())
        for match in self._MN_CHAPTER_RANGE_RE.finditer(page_text):
            for chapter_token in self._expand_chapter_range(match.group("start"), match.group("end")):
                full_url = f"{self.get_base_url()}/statutes/cite/{chapter_token}"
                if full_url in seen:
                    continue
                seen.add(full_url)
                chapter_urls.append(full_url)
                if limit is not None and len(chapter_urls) >= limit:
                    return chapter_urls

        if limit is None:
            raise RuntimeError(
                "Minnesota official statutes index exposed neither an exact "
                "chapter table nor an exact TOC-part table"
            )
        return chapter_urls

    def _expand_chapter_range(self, start_token: str, end_token: str) -> List[str]:
        def _split(token: str) -> tuple[int, str]:
            match = re.match(r"^(\d{1,3})([A-Za-z]?)$", str(token or "").strip())
            if not match:
                return 0, ""
            return int(match.group(1)), match.group(2).upper()

        start_num, start_suffix = _split(start_token)
        end_num, end_suffix = _split(end_token)
        if start_num <= 0 or end_num <= 0 or end_num < start_num:
            return []

        if start_num == end_num:
            suffixes = [""]
            if start_suffix or end_suffix:
                begin_ord = ord(start_suffix or "A")
                end_ord = ord(end_suffix or start_suffix or "A")
                suffixes = [chr(code) for code in range(begin_ord, end_ord + 1)]
                if start_suffix == "":
                    suffixes.insert(0, "")
            return [f"{start_num}{suffix}" for suffix in suffixes]

        out = [f"{start_num}{start_suffix}" if start_suffix else str(start_num)]
        for value in range(start_num + 1, end_num):
            out.append(str(value))
        out.append(f"{end_num}{end_suffix}" if end_suffix else str(end_num))
        return out

    def _extract_section_urls_from_chapter_page(self, soup) -> List[str]:
        urls: List[str] = []
        from .minnesota_section import chapter_analysis_section_rows

        html = str(soup)
        analysis_rows = chapter_analysis_section_rows(html)
        if analysis_rows:
            return [url for _number, _name, url in analysis_rows]

        # Minnesota chapter pages expose the authoritative section list in table rows,
        # which is more reliable than inferring coverage from the link structure alone.
        for row in soup.find_all("tr"):
            text = " ".join(row.get_text(" ", strip=True).split())
            if not text:
                continue
            match = self._MN_SECTION_ROW_RE.match(text)
            if not match:
                continue
            urls.append(f"{self.get_base_url()}/statutes/cite/{match.group('section')}")

        if urls:
            return urls

        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            if not href.startswith("/statutes/cite/"):
                continue
            full_url = href if href.startswith("http") else f"{self.get_base_url()}{href}"
            if self._MN_SECTION_URL_RE.search(full_url):
                urls.append(full_url)

        return urls

    async def _build_statute_from_section_page(
        self,
        code_name: str,
        section_url: str,
    ) -> NormalizedStatute | None:
        html_text = await self._request_text_direct(section_url, timeout=18)
        if not html_text:
            try:
                payload = await self._fetch_page_content_with_archival_fallback(
                    section_url,
                    timeout_seconds=35,
                )
            except Exception:
                return None
            if not payload:
                return None
            html_text = (
                payload.decode("utf-8", errors="replace")
                if isinstance(payload, bytes)
                else str(payload)
            )
        if not html_text:
            return None
        return self._build_statute_from_section_html(
            code_name,
            section_url,
            html_text,
        )

    def _build_statute_from_section_html(
        self,
        code_name: str,
        section_url: str,
        html_text: str,
        *,
        expected_edition: str = "",
        strict_source_bound: bool = False,
    ) -> NormalizedStatute | None:
        """Parse one already-retained official Minnesota section page."""

        if not html_text:
            return None
        from .minnesota_section import parse_minnesota_section_html

        parsed = parse_minnesota_section_html(
            html_text,
            source_url=section_url,
            code_name=code_name,
            expected_edition=expected_edition,
            require_source_identity=strict_source_bound,
        )
        if parsed is not None:
            return parsed
        if strict_source_bound:
            # Exact publication treats the Revisor's source-bound ``.section``
            # DOM as the sole operative-law grammar.  Long ``.sr`` terminal
            # notices must reach the lifecycle classifier below rather than a
            # generic whole-page text fallback.
            return None

        match = self._MN_SECTION_NUMBER_RE.search(section_url)
        section_number = match.group(1) if match else section_url.rsplit("/", 1)[-1]
        text = self._extract_best_content_text(html_text)
        heading_pattern = re.compile(
            rf"\b{re.escape(section_number)}\b\s+[A-Z][A-Z0-9 ,;:'()\-/&]+\.",
            re.IGNORECASE,
        )
        heading_match = heading_pattern.search(text)
        if heading_match:
            text = text[heading_match.start():]
        text = re.split(r"\bHistory:\b", text, maxsplit=1)[0].strip()
        text = re.split(r"\b(?:Official Publication of the State of Minnesota|About the Legislature|General Contact|Get Connected)\b", text, maxsplit=1)[0].strip()
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < 160:
            return None

        heading = f"Minnesota Statutes {section_number}"
        title_match = re.search(r"\b%s\b\s+([A-Z][A-Z0-9 ,;:'()\-/&]{4,120})\." % re.escape(section_number), text)
        if title_match:
            heading = f"{section_number} {title_match.group(1).title()}"

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=heading[:200],
            full_text=text,
            source_url=section_url,
            legal_area=self._identify_legal_area(heading),
            official_cite=f"Minn. Stat. § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_minnesota_statutes_html",
                "discovery_method": "official_seed_or_section_page",
                "skip_hydrate": True,
            },
        )

    async def _request_text_direct(self, url: str, timeout: int = 18) -> str:
        try:
            payload = await self._fetch_parser_input_with_transport(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout_seconds=max(1, int(timeout)),
                allow_archival_fallback=True,
                media_type="text/html",
                provider="minnesota_direct_section",
            )
        except Exception:
            return ""
        return payload.decode("utf-8", errors="replace") if payload else ""

    def official_chapter_url(self, chapter: Any) -> str:
        token = str(chapter or "").strip()
        return f"{self.get_base_url()}/statutes/cite/{token}"

    def official_chapter_tokens(self) -> List[str]:
        tokens: List[str] = [str(number) for number in self.OFFICIAL_NUMERIC_CHAPTERS]
        tokens.extend(self.OFFICIAL_LETTERED_CHAPTERS)
        return tokens

    def official_chapter_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Minnesota Statutes chapter catalog."""

        rows: List[Dict[str, Any]] = []
        for token in self.official_chapter_tokens():
            url = self.official_chapter_url(token)
            rows.append(
                {
                    "canonical_key": f"mn:chapter-{token.lower()}",
                    "chapter_number": token,
                    "name": f"Chapter {token}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Minnesota Statutes Chapter {token} official catalog "
                        f"unit at {url}"
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
                        "User-Agent": "ipfs-datasets-minnesota-official-catalog/1.0",
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
                            "User-Agent": "ipfs-datasets-minnesota-official-catalog/1.0",
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
            match = self._MN_CHAPTER_URL_RE.search(href)
            if not match:
                continue
            token = match.group(1)
            if "." in token:
                continue
            if token not in found:
                found[token] = self.official_chapter_url(token)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official Minnesota Statutes chapter and repair links."""

        del page_url
        discovered = self._parse_official_chapter_links(html)
        rows = self.official_chapter_catalog()
        seen = {str(row["chapter_number"]).lower() for row in rows}
        for row in rows:
            live_url = discovered.get(str(row["chapter_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_leginfo"
        for token, url in discovered.items():
            if token.lower() in seen:
                continue
            rows.append(
                {
                    "canonical_key": f"mn:chapter-{token.lower()}",
                    "chapter_number": token,
                    "name": f"Chapter {token}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Minnesota Statutes Chapter {token} official catalog "
                        f"unit at {url}"
                    ),
                }
            )
        return rows

    def fetch_official(self, code: str = "MN"):
        """Acquire the exhaustive official Minnesota Statutes chapter catalog.

        Live HTTPS retains the official statutes index. Every known chapter is
        enumerated with an official revisor.mn.gov URL. This hook never
        returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "MN").strip().upper() or "MN"
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < 3:
            raise RuntimeError("minnesota official catalog enumeration is incomplete")
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
StateScraperRegistry.register("MN", MinnesotaScraper)
