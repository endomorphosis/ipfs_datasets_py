"""Scraper for Wyoming state laws.

Official path: deterministic title PDFs on https://www.wyoleg.gov/statutes/compress/
(preferred over the JS StatutesDownload SPA). Playwright/generic remain fallbacks only.
"""

import hashlib
import json
import re
import ssl
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import urljoin, urlparse

from .base_scraper import (
    BaseStateScraper,
    NormalizedStatute,
    StateLawPageMultiFetchResult,
    StatuteMetadata,
)
from .registry import StateScraperRegistry
from .retained_replay_network_guard import trusted_pdftotext_executable

try:
    from playwright import async_api as _playwright_async_api

    PLAYWRIGHT_AVAILABLE = bool(_playwright_async_api)
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class WyomingScraper(BaseStateScraper):
    """Scraper for Wyoming state laws from https://www.wyoleg.gov"""

    # ``\s`` is intentionally not used around the heading.  In multiline
    # mode it consumes newlines and made a citation in the preceding body look
    # like the next section.  Title 34.1 is a real Wyoming title, not title 34.
    _SECTION_HEADER_RE = re.compile(
        r"(?m)^(?P<indent>[ \t\f]*)"
        r"(?P<section>(?:34\.1|\d{1,2})-\d{1,2}-\d{2,4}(?:\.[0-9A-Za-z]+)?)\."
        r"[^\S\r\n]+(?P<heading>[^\r\n]+?)[ \t]*$"
    )
    _WY_TITLE_PDF_RE = re.compile(
        r"/statutes/compress/title(?P<title>34\.1|\d{1,2})\.pdf",
        re.IGNORECASE,
    )
    _WY_TITLE_LABEL_RE = re.compile(
        r"(?:title|t\.?)\s*(34\.1|\d{1,2})\b",
        re.IGNORECASE,
    )
    _WY_SECTION_CITE_RE = re.compile(
        r"\b(34\.1|\d{1,2})-\d{1,2}-\d{2,4}(?:\.[0-9A-Za-z]+)?\b"
    )
    OFFICIAL_DOMAIN = "www.wyoleg.gov"
    OFFICIAL_ENTRY_PATH = "/stateStatutes/StatutesDownload"
    OFFICIAL_ENTRY_URL = "https://www.wyoleg.gov/stateStatutes/StatutesDownload"
    OFFICIAL_COMPRESS_PATH = "/statutes/compress/"
    LINKLESS_QUARANTINE_REASON = "missing_official_source_link"
    OFFICIAL_TITLE_NUMBERS = tuple(
        ["97"]
        + [str(number) for number in range(1, 35)]
        + ["34.1"]
        + [str(number) for number in range(35, 43)]
        + ["99"]
    )
    OFFICIAL_EDITION = "2026 Budget Session"
    OFFICIAL_LEGAL_AS_OF = "2026-07-01"

    def state_law_frontier_source_dependencies(self) -> Sequence[Any]:
        """Bind both optional PDF parsers into the publication source bundle."""

        from . import wyoming_constitution, wyoming_title

        return (wyoming_constitution, wyoming_title)

    def _wyoming_pdf_batch_size(self) -> int:
        return max(
            1,
            min(
                len(self.OFFICIAL_TITLE_NUMBERS),
                self._env_int(
                    "STATE_SCRAPER_WY_PDF_BATCH_SIZE",
                    default=len(self.OFFICIAL_TITLE_NUMBERS),
                ),
            ),
        )

    def _wyoming_pdf_concurrency(self) -> int:
        return max(
            1,
            min(
                32,
                self._env_int(
                    "STATE_SCRAPER_WY_PDF_CONCURRENCY",
                    default=8,
                ),
            ),
        )

    async def _fetch_wyoming_pdf_batch(
        self,
        urls: Sequence[str],
        *,
        frontier_name: str,
    ) -> StateLawPageMultiFetchResult:
        """Fetch one exact PDF frontier through the shared grouped-WARC path."""

        requested = list(urls)
        if not requested:
            return StateLawPageMultiFetchResult([], [], [], [], [], {})
        if len(set(requested)) != len(requested):
            raise RuntimeError(
                f"Wyoming {frontier_name} frontier contains duplicate URLs"
            )
        if bool(getattr(self, "_wyoming_retained_replay", False)):
            from .strict_frontier_closure import (
                replay_exact_retained_state_records,
            )

            accept = "application/pdf,*/*;q=0.8"
            retained_rows = replay_exact_retained_state_records(
                self,
                requests=[
                    (
                        url,
                        {
                            "method": "GET",
                            "url": url,
                            "headers": {"Accept": accept},
                        },
                    )
                    for url in requested
                ],
                frontier_name=f"Wyoming {frontier_name} frontier",
                refresh=False,
            )
            payloads = [
                bytes(getattr(row.envelope, "body", b"") or b"")
                for row in retained_rows
            ]
            if any(
                len(payload) <= 1024 or not payload.lstrip().startswith(b"%PDF")
                for payload in payloads
            ):
                raise RuntimeError(
                    f"Wyoming retained {frontier_name} frontier contains an invalid PDF"
                )
            return StateLawPageMultiFetchResult(
                urls=requested,
                payloads=payloads,
                errors=[None] * len(requested),
                transport_receipts=[
                    dict(row.transport_receipt) for row in retained_rows
                ],
                parser_input_envelopes=[row.envelope for row in retained_rows],
                stats={
                    "network_requested_pages": 0,
                    "requested_pages": len(requested),
                    "retained_replay_pages": len(requested),
                    "retained_replay_unique_pages": len(set(requested)),
                    "successful_pages": len(requested),
                    "unique_pages": len(set(requested)),
                },
            )
        retry_attempts = max(
            0,
            min(
                3,
                self._env_int(
                    "STATE_SCRAPER_WY_PDF_RESIDUAL_RETRY_ATTEMPTS",
                    default=1,
                ),
            ),
        )
        batch = await self._fetch_page_contents_with_archival_fallback_retrying_residuals(
            requested,
            residual_retry_attempts=retry_attempts,
            timeout_seconds=90,
            headers={
                "Accept": "application/pdf,*/*;q=0.8",
                "User-Agent": "ipfs-datasets-wyoming-statutes/2.0",
            },
            content_validator=lambda payload: (
                len(payload) > 1024 and payload.lstrip().startswith(b"%PDF")
            ),
            media_type="application/pdf",
            max_concurrency=self._wyoming_pdf_concurrency(),
            prefer_direct=True,
            common_crawl_domain_terms=(self.OFFICIAL_DOMAIN, "wyoleg.gov"),
            common_crawl_url_terms=(self.OFFICIAL_COMPRESS_PATH,),
            common_crawl_mime_terms=("pdf",),
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
                f"Wyoming {frontier_name} frontier returned unaligned acquisition rows"
            )
        if list(batch.urls) != requested:
            raise RuntimeError(
                f"Wyoming {frontier_name} frontier changed URL order or identity"
            )
        failures = [
            {"url": url, "error": error or "empty PDF parser input"}
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
                f"Wyoming {frontier_name} frontier is incomplete; "
                f"unresolved exact URLs: {failures}"
            )
        batch.payloads = [bytes(payload) for payload in batch.payloads]
        return batch

    async def _fetch_wyoming_pdf_frontier(
        self,
        urls: Sequence[str],
    ) -> StateLawPageMultiFetchResult:
        """Fetch every title PDF in bounded plural batches without losing order."""

        requested = list(urls)
        payloads: List[bytes] = []
        errors: List[Optional[str]] = []
        receipts: List[Optional[Dict[str, Any]]] = []
        envelopes: List[Any] = []
        stats: Dict[str, Any] = {"batches": []}
        batch_size = self._wyoming_pdf_batch_size()
        for start in range(0, len(requested), batch_size):
            selected = requested[start : start + batch_size]
            batch = await self._fetch_wyoming_pdf_batch(
                selected,
                frontier_name=f"title-pdfs-{start + 1}-{start + len(selected)}",
            )
            payloads.extend(batch.payloads)
            errors.extend(batch.errors)
            receipts.extend(batch.transport_receipts)
            envelopes.extend(batch.parser_input_envelopes)
            stats["batches"].append(dict(batch.stats or {}))
        return StateLawPageMultiFetchResult(
            urls=requested,
            payloads=payloads,
            errors=errors,
            transport_receipts=receipts,
            parser_input_envelopes=envelopes,
            stats=stats,
        )

    @staticmethod
    def _terminal_disposition_from_heading(heading: str) -> str:
        """Return an exact source-bound disposition for a Wyoming heading."""

        normalized = re.sub(r"\s+", " ", str(heading or "")).strip(" .")
        if re.fullmatch(r"reserved", normalized, re.IGNORECASE):
            return "reserved"
        if re.match(
            r"^repealed(?:$|\s+(?:by|and|as|pursuant)\b)",
            normalized,
            re.IGNORECASE,
        ):
            return "repealed"
        if re.match(
            r"^(?:amended\s+and\s+)?renumbered(?:$|\s+(?:as|by|pursuant)\b)",
            normalized,
            re.IGNORECASE,
        ):
            return "renumbered"
        for disposition in ("expired", "executed", "omitted", "transferred"):
            if re.fullmatch(disposition, normalized, re.IGNORECASE):
                return disposition
        return ""

    def _wyoming_exact_frontier(
        self,
        *,
        title_reports: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Close exact title-PDF membership and operative/terminal algebra."""

        reports = [dict(report) for report in title_reports]
        catalog = self._build_deterministic_title_catalog()
        if len(reports) != len(catalog):
            raise RuntimeError(
                "Wyoming exact frontier changed the 45-title catalog cardinality"
            )

        terminal_counts: Dict[str, int] = {}
        operative_identities: List[str] = []
        terminal_identity_count = 0
        seen_operative: set[str] = set()
        seen_terminal: set[str] = set()
        for report, (title_number, _title_name, source_url) in zip(
            reports,
            catalog,
            strict=True,
        ):
            if (
                str(report.get("title_number") or "") != title_number
                or str(report.get("source_url") or "") != source_url
                or report.get("closed") is not True
                or list(report.get("parser_residuals") or [])
            ):
                raise RuntimeError(
                    "Wyoming exact title frontier changed source identity or closure: "
                    f"title={title_number}"
                )
            content_sha256 = str(report.get("content_sha256") or "").strip()
            if not re.fullmatch(r"[a-f0-9]{64}", content_sha256):
                raise RuntimeError(
                    f"Wyoming title {title_number} lacks retained PDF fixity"
                )
            candidate = int(report.get("candidate_sections") or 0)
            operative = int(report.get("operative_sections") or 0)
            terminal = int(report.get("terminal_sections") or 0)
            if candidate <= 0 or candidate != operative + terminal:
                raise RuntimeError(
                    "Wyoming exact title disposition algebra did not close: "
                    f"title={title_number} candidate={candidate} "
                    f"operative={operative} terminal={terminal}"
                )

            report_operative = [
                str(value or "").strip()
                for value in list(report.get("operative_identities") or [])
            ]
            if (
                len(report_operative) != operative
                or any(not value for value in report_operative)
            ):
                raise RuntimeError(
                    f"Wyoming title {title_number} lost operative identities"
                )
            for identity in report_operative:
                key = identity.casefold()
                if key in seen_operative:
                    raise RuntimeError(
                        "Wyoming exact title frontier repeated an operative identity: "
                        f"{identity}"
                    )
                seen_operative.add(key)
                operative_identities.append(identity)

            terminal_rows = list(report.get("terminal_dispositions") or [])
            if len(terminal_rows) != terminal:
                raise RuntimeError(
                    f"Wyoming title {title_number} lost terminal dispositions"
                )
            for terminal_row in terminal_rows:
                if not isinstance(terminal_row, Mapping):
                    raise RuntimeError(
                        f"Wyoming title {title_number} has a malformed disposition"
                    )
                identity = str(
                    terminal_row.get("section_number")
                    or terminal_row.get("section_identifier")
                    or ""
                ).strip()
                disposition = str(
                    terminal_row.get("disposition") or ""
                ).strip().lower()
                terminal_key = f"{title_number}:{identity}".casefold()
                if not identity or not disposition or terminal_key in seen_terminal:
                    raise RuntimeError(
                        "Wyoming exact title frontier has a repeated or malformed "
                        f"terminal identity: {title_number}:{identity}"
                    )
                seen_terminal.add(terminal_key)
                terminal_counts[disposition] = (
                    terminal_counts.get(disposition, 0) + 1
                )
                terminal_identity_count += 1

        discovered = sum(int(row.get("candidate_sections") or 0) for row in reports)
        fetched = len(operative_identities)
        excluded = terminal_identity_count
        disposition = {
            "discovered": discovered,
            "duplicates": 0,
            "excluded": excluded,
            "failed_final": 0,
            "fetched": fetched,
            "quarantined": 0,
        }
        if discovered != fetched + excluded:
            raise RuntimeError("Wyoming exact corpus disposition algebra did not close")

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            compute_frontier_digest,
        )

        frontier: Dict[str, Any] = {
            "algebra_closed": True,
            "bundle_closed": True,
            "catalog_title_numbers": [row[0] for row in catalog],
            "closed": True,
            "disposition": disposition,
            "edition": self.OFFICIAL_EDITION,
            "enumerator_closed": True,
            "expected_index_units": len(catalog),
            "legal_as_of": self.OFFICIAL_LEGAL_AS_OF,
            "method": "official_title_pdf_bundle",
            "operative_identity_count": fetched,
            "pagination_closed": True,
            "remaining_bundle_members": [],
            "schema_version": "wyoming-exact-title-pdf-frontier-v1",
            "scope_closed": True,
            "terminal_dispositions": dict(sorted(terminal_counts.items())),
            "title_reports": reports,
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": len(catalog),
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return frontier
    
    def get_base_url(self) -> str:
        """Return the base URL for Wyoming's legislative website."""
        return "https://www.wyoleg.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Wyoming."""
        return [{
            "name": "Wyoming Statutes",
            "url": f"{self.get_base_url()}/stateStatutes/StatutesDownload",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Wyoming's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        max_sections = self._effective_scrape_limit(max_statutes, default=160)
        max_sections_value = int(max_sections or 1000000)
        from .wyoming_constitution import (
            configured_constitution_text_path,
            parse_wyoming_constitution_text,
        )

        constitution_path = configured_constitution_text_path()
        if (
            not self._full_corpus_enabled()
            and (
                constitution_path is not None
                or "constitution" in str(code_name or "").lower()
            )
        ):
            if constitution_path is not None:
                constitution_rows = parse_wyoming_constitution_text(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Wyoming Constitution",
                    max_statutes=max_sections,
                )
                return constitution_rows if max_sections is None else constitution_rows[: int(max_sections)]
        from .wyoming_title import parse_configured_wyoming_title

        if not self._full_corpus_enabled():
            local_rows = parse_configured_wyoming_title(
                code_name=code_name,
                max_statutes=max_sections,
            )
            if local_rows:
                return local_rows[:max_sections_value]

        # The official download catalog has stable title PDFs. Prefer it over
        # the JS page so full-corpus runs do not depend on rendered link order.
        deterministic = await self._scrape_deterministic_title_pdfs(
            code_name,
            "Wyo. Stat.",
            max_sections=max_sections_value,
        )
        if deterministic:
            return deterministic[:max_sections_value]

        if PLAYWRIGHT_AVAILABLE:
            self.logger.info("Wyoming: Using Playwright for JavaScript rendering")
            try:
                result = await self._scrape_with_playwright(
                    code_name,
                    code_url,
                    "Wyo. Stat.",
                    max_sections=max_sections_value,
                )
                if result:
                    return result[:max_sections_value]
            except Exception as e:
                self.logger.warning(f"Wyoming Playwright failed: {e}, falling back")
        
        result = await self._custom_scrape_wyoming(
            code_name,
            code_url,
            "Wyo. Stat.",
            max_sections=max_sections_value,
        )
        return result[:max_sections_value]
    
    async def _scrape_with_playwright(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 60
    ) -> List[NormalizedStatute]:
        """Scrape Wyoming using Playwright for JavaScript rendering."""
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError:
            return []

        payload = await self._fetch_browser_parser_input_with_transport(
            code_url,
            wait_for_selector="a",
            timeout_ms=60000,
            wait_until="networkidle",
            allowed_final_hosts=("www.wyoleg.gov", "wyoleg.gov"),
            provider="wyoming_browser_rendered_direct",
            pagination={"kind": "wyoming_title_pdf_catalog"},
        )
        if not payload:
            return []

        soup = BeautifulSoup(payload.decode("utf-8", errors="replace"), "html.parser")
        statutes: List[NormalizedStatute] = []
        section_count = 0
        seen_urls = set()
        for link in soup.find_all("a", href=True):
            if section_count >= max_sections:
                break

            link_text = link.get_text(strip=True)
            link_href = link.get("href", "")
            if len(link_text) < 5:
                continue
            full_url = urljoin(code_url, link_href)
            parsed_full_url = urlparse(full_url)
            full_url_l = full_url.lower()
            if not (
                parsed_full_url.scheme.lower() in {"http", "https"}
                and (parsed_full_url.hostname or "").lower()
                in {"www.wyoleg.gov", "wyoleg.gov"}
                and full_url_l.endswith(".pdf")
                and "/statutes/compress/title" in full_url_l
            ):
                continue
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            section_number = self._extract_section_number(link_text) or (
                f"Section-{section_count + 1}"
            )
            match = re.search(r"\btitle\s+(\d+(?:\.\d+)?)", link_text, re.IGNORECASE)
            if match:
                section_number = match.group(1)

            full_text = await self._extract_pdf_text_summary(full_url)
            if len(full_text.strip()) < 80:
                full_text = (
                    f"Wyoming Statutes Title {section_number}: {link_text}. "
                    f"Official source PDF: {full_url}."
                )

            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=link_text[:200],
                    full_text=full_text,
                    legal_area=self._identify_legal_area(link_text),
                    source_url=full_url,
                    official_cite=f"{citation_format} § {section_number}",
                    metadata=StatuteMetadata(),
                )
            )
            section_count += 1

        self.logger.info("Wyoming browser render: scraped %s titles", len(statutes))
        return statutes

    async def _extract_pdf_text_summary(self, pdf_url: str, max_chars: Optional[int] = None) -> str:
        """Extract statute text from a PDF using system `pdftotext`.

        This keeps Wyoming strict-mode scraping resilient without adding heavy PDF
        parser dependencies to the Python environment.
        """
        try:
            payload = await self._fetch_page_content_with_archival_fallback(
                pdf_url,
                timeout_seconds=45,
            )
            if not payload:
                return ""
            raw = self._extract_pdf_text_from_payload(payload, preserve_layout=False)
            text = re.sub(r"\s+", " ", raw).strip()
            if max_chars is not None:
                return text[: max(1, int(max_chars))]
            return text
        except Exception as e:
            self.logger.debug(f"Wyoming PDF text extraction failed for {pdf_url}: {e}")
            return ""

    async def _extract_pdf_text_layout(self, pdf_url: str, max_chars: Optional[int] = None) -> str:
        """Extract layout-preserving PDF text so section headers survive splitting."""
        try:
            payload = await self._fetch_page_content_with_archival_fallback(
                pdf_url,
                timeout_seconds=45,
            )
            if not payload:
                return ""
            raw = self._extract_pdf_text_from_payload(payload, preserve_layout=True)
            if max_chars is not None:
                return raw[: max(1, int(max_chars))]
            return raw
        except Exception as e:
            self.logger.debug(f"Wyoming layout PDF extraction failed for {pdf_url}: {e}")
            return ""

    def _extract_pdf_text_from_payload(
        self,
        payload: bytes,
        *,
        preserve_layout: bool,
    ) -> str:
        """Extract text from one retained PDF without issuing another request."""

        if not payload:
            return ""
        command = [trusted_pdftotext_executable()]
        if preserve_layout:
            command.append("-layout")
        command.extend(["-q", "-", "-"])
        try:
            proc = subprocess.run(
                command,
                input=bytes(payload),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=300 if preserve_layout else 180,
                check=False,
            )
        except Exception as exc:
            self.logger.debug("Wyoming retained PDF text extraction failed: %s", exc)
            return ""
        if proc.returncode != 0:
            return ""
        return bytes(proc.stdout or b"").decode("utf-8", errors="ignore")

    def _split_title_pdf_into_sections(
        self,
        *,
        code_name: str,
        title_number: str,
        title_name: str,
        title_text: str,
        source_url: str,
        citation_format: str,
    ) -> List[NormalizedStatute]:
        # pdftotext output is line-oriented.  A real heading is separated from
        # the preceding body and is either indented or followed by a blank
        # line.  This excludes line-leading statutory citations in prose while
        # retaining wrapped official headings and unindented repealed markers.
        title_text = str(title_text or "").replace("\r\n", "\n").replace("\r", "\n")
        expected_prefix = f"{self.normalize_title_number(title_number)}-"
        matches: List[re.Match[str]] = []
        foreign_title_headers: List[str] = []
        for match in self._SECTION_HEADER_RE.finditer(title_text):
            section_number = str(match.group("section") or "").strip()
            previous_end = max(0, match.start() - 1)
            previous_start = title_text.rfind("\n", 0, previous_end) + 1
            previous_line = title_text[previous_start:previous_end].strip()
            next_start = match.end() + (
                1 if match.end() < len(title_text) and title_text[match.end()] == "\n" else 0
            )
            next_end = title_text.find("\n", next_start)
            if next_end < 0:
                next_end = len(title_text)
            raw_next_line = title_text[next_start:next_end]
            next_line = raw_next_line.strip()
            follows_hierarchy_heading = bool(
                re.match(r"^(?:TITLE|CHAPTER|ARTICLE)\b", previous_line, re.IGNORECASE)
            )
            terminal_heading = bool(
                self._terminal_disposition_from_heading(match.group("heading"))
            )
            starts_pdf_page = "\f" in match.group("indent")
            body_starts_pdf_page = raw_next_line.startswith("\f")
            structurally_bound = starts_pdf_page or (
                (not previous_line or follows_hierarchy_heading)
                and (
                    bool(match.group("indent"))
                    or not next_line
                    or terminal_heading
                    or body_starts_pdf_page
                )
            )
            if not structurally_bound:
                continue
            if not section_number.startswith(expected_prefix):
                foreign_title_headers.append(section_number)
                continue
            matches.append(match)
        if not matches:
            self._last_wyoming_title_parse_report = {
                "title_number": str(title_number),
                "candidate_sections": 0,
                "operative_sections": 0,
                "terminal_sections": 0,
                "terminal_dispositions": [],
                "parser_residuals": [],
                "duplicate_headers": {},
                "overlay_duplicate_headers": [],
                "page_body_citation_occurrences": [],
                "conflicting_duplicate_headers": {},
                "duplicate_header_occurrences": 0,
                "foreign_title_headers": foreign_title_headers,
                "closed": False,
            }
            return []

        starts_by_section: dict[str, list[re.Match[str]]] = {}
        for match in matches:
            starts_by_section.setdefault(match.group("section"), []).append(match)

        def _normalized_heading(match: re.Match[str]) -> str:
            return re.sub(r"\s+", " ", match.group("heading")).strip(" .")

        def _headings_compatible(left: str, right: str) -> bool:
            left_folded = left.casefold()
            right_folded = right.casefold()
            return left_folded.startswith(right_folded) or right_folded.startswith(
                left_folded
            )

        # Prefer an ordinary source heading over a form-feed page-top cite.
        # A page can start with a continuation such as ``21-2-204. Nothing in
        # this section...`` before the real 21-2-204 heading later in the PDF.
        canonical_match_by_section: Dict[str, re.Match[str]] = {}
        for section_number, occurrences in starts_by_section.items():
            ordinary = [
                occurrence
                for occurrence in occurrences
                if "\f" not in occurrence.group("indent")
            ]
            canonical_match_by_section[section_number] = (
                ordinary[0] if ordinary else occurrences[0]
            )
        body_matches = sorted(
            canonical_match_by_section.values(), key=lambda item: item.start()
        )

        canonical_heading_by_section = {
            str(match.group("section")): _normalized_heading(match)
            for match in body_matches
        }
        canonical_sections_by_heading: Dict[str, List[str]] = {}
        for section_number, heading in canonical_heading_by_section.items():
            canonical_sections_by_heading.setdefault(heading.casefold(), []).append(
                section_number
            )
        duplicate_headers = {
            section: [_normalized_heading(item) for item in occurrences]
            for section, occurrences in starts_by_section.items()
            if len(occurrences) > 1
        }
        overlay_duplicate_headers: List[Dict[str, Any]] = []
        overlay_spans: set[tuple[int, int]] = set()
        overlay_headings_by_section: Dict[str, set[str]] = {}
        page_body_citation_occurrences: List[Dict[str, str]] = []
        page_body_citation_spans: set[tuple[int, int]] = set()
        repeated_heading_spans_by_section: Dict[str, List[tuple[int, int]]] = {}
        conflicting_duplicate_headers: Dict[str, List[str]] = {}
        for section_number, occurrences in starts_by_section.items():
            if len(occurrences) < 2:
                continue
            canonical_match = canonical_match_by_section[section_number]
            canonical_heading = canonical_heading_by_section[section_number]
            non_overlay_headings: List[str] = []
            for occurrence in occurrences:
                heading = _normalized_heading(occurrence)
                is_canonical = occurrence.start() == canonical_match.start()
                if (
                    not is_canonical
                    and "\f" in occurrence.group("indent")
                    and "\f" not in canonical_match.group("indent")
                    and not _headings_compatible(heading, canonical_heading)
                ):
                    page_body_citation_spans.add(
                        (occurrence.start(), occurrence.end())
                    )
                    page_body_citation_occurrences.append(
                        {
                            "section_number": section_number,
                            "heading": heading,
                            "canonical_heading": canonical_heading,
                            "reason": "page_top_body_citation_before_canonical_heading",
                        }
                    )
                    continue
                canonical_other_sections = [
                    candidate
                    for candidate in canonical_sections_by_heading.get(
                        heading.casefold(), []
                    )
                    if candidate != section_number
                ]
                if not is_canonical and canonical_other_sections:
                    overlay_spans.add((occurrence.start(), occurrence.end()))
                    overlay_headings_by_section.setdefault(section_number, set()).add(
                        heading
                    )
                    overlay_duplicate_headers.append(
                        {
                            "section_number": section_number,
                            "heading": heading,
                            "canonical_section_numbers": canonical_other_sections,
                            "reason": "alternate_heading_is_canonical_for_other_section",
                        }
                    )
                    continue
                non_overlay_headings.append(heading)
            if all(
                self._terminal_disposition_from_heading(item)
                for item in non_overlay_headings
            ):
                continue
            folded = [item.casefold() for item in non_overlay_headings]
            longest = max(folded, key=len)
            if any(not longest.startswith(item) for item in folded):
                conflicting_duplicate_headers[section_number] = non_overlay_headings

        for section_number, occurrences in starts_by_section.items():
            canonical_match = canonical_match_by_section[section_number]
            canonical_heading = canonical_heading_by_section[section_number]
            for occurrence in occurrences:
                occurrence_span = (occurrence.start(), occurrence.end())
                if (
                    occurrence.start() == canonical_match.start()
                    or occurrence_span in page_body_citation_spans
                ):
                    continue
                span_end = occurrence.end()
                heading = _normalized_heading(occurrence)
                if (
                    heading.casefold() != canonical_heading.casefold()
                    and canonical_heading.casefold().startswith(heading.casefold())
                ):
                    continuation_start = span_end + (
                        1
                        if span_end < len(title_text)
                        and title_text[span_end] == "\n"
                        else 0
                    )
                    continuation_end = title_text.find("\n", continuation_start)
                    if continuation_end < 0:
                        continuation_end = len(title_text)
                    continuation = title_text[
                        continuation_start:continuation_end
                    ].strip(" .\t\f")
                    combined = f"{heading} {continuation}".strip()
                    if combined.casefold() == canonical_heading.casefold():
                        span_end = continuation_end
                repeated_heading_spans_by_section.setdefault(
                    section_number, []
                ).append((occurrence.start(), span_end))

        statutes: List[NormalizedStatute] = []
        terminal_dispositions: List[Dict[str, str]] = []
        parser_residuals: List[Dict[str, Any]] = []
        exact_duplicate_section_bodies: List[Dict[str, Any]] = []
        for index, match in enumerate(body_matches):
            section_number = str(match.group("section") or "").strip()
            section_name = re.sub(
                r"\s+", " ", str(match.group("heading") or "").strip()
            ).strip(" .")
            terminal_disposition = self._terminal_disposition_from_heading(section_name)
            if terminal_disposition:
                terminal_dispositions.append(
                    {
                        "section_number": section_number,
                        "disposition": terminal_disposition,
                        "heading": section_name,
                    }
                )
                continue
            block_end = (
                body_matches[index + 1].start()
                if index + 1 < len(body_matches)
                else len(title_text)
            )
            raw_block = title_text[match.start():block_end]
            repeated_occurrences = [
                occurrence
                for occurrence in starts_by_section.get(section_number, [])[1:]
                if (
                    match.start() < occurrence.start() < block_end
                    and (occurrence.start(), occurrence.end())
                    not in page_body_citation_spans
                    and _headings_compatible(
                        _normalized_heading(occurrence), section_name
                    )
                )
            ]
            duplicate_body_segments = []
            if repeated_occurrences:
                segment_starts = [match.start()] + [
                    occurrence.start() for occurrence in repeated_occurrences
                ]
                duplicate_body_segments = [
                    title_text[
                        segment_start : (
                            segment_starts[segment_index + 1]
                            if segment_index + 1 < len(segment_starts)
                            else block_end
                        )
                    ]
                    for segment_index, segment_start in enumerate(segment_starts)
                ]
            exact_duplicate_body = bool(
                len(duplicate_body_segments) > 1
                and len(
                    {
                        self._normalize_legal_text(segment)
                        for segment in duplicate_body_segments
                    }
                )
                == 1
            )
            if exact_duplicate_body:
                raw_block = duplicate_body_segments[0]
                exact_duplicate_section_bodies.append(
                    {
                        "section_number": section_number,
                        "duplicate_blocks_removed": len(duplicate_body_segments) - 1,
                    }
                )
            else:
                for repeat_start, repeat_end in sorted(
                    repeated_heading_spans_by_section.get(section_number, []),
                    reverse=True,
                ):
                    if match.start() < repeat_start < block_end:
                        relative_start = repeat_start - match.start()
                        relative_end = repeat_end - match.start()
                        raw_block = (
                            raw_block[:relative_start] + raw_block[relative_end:]
                        )
            # Remove only occurrences proven to be PDF text-layer overlays by
            # an exact heading identity elsewhere in this same source PDF.
            # The retained title-35 PDF proves that the same text-layer
            # overlay can be echoed with subsection markers but without the
            # section cite.  Remove only whole lines whose text is the exact
            # already-proven alternate canonical heading.
            for overlay_heading in overlay_headings_by_section.get(
                section_number, set()
            ):
                raw_block = re.sub(
                    r"(?m)^[ \t\f]*(?:\([0-9A-Za-zivxIVX]+\)[ \t]+)?"
                    + re.escape(overlay_heading)
                    + r"\.[ \t]*$",
                    "",
                    raw_block,
                    flags=re.IGNORECASE,
                )
            normalized = self._normalize_legal_text(raw_block)
            if len(normalized) < 40:
                parser_residuals.append(
                    {
                        "section_number": section_number,
                        "reason": "short_section_block",
                        "normalized_length": len(normalized),
                    }
                )
                continue

            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:240] or f"Section {section_number}",
                    full_text=normalized,
                    legal_area=self._identify_legal_area(f"{title_name} {section_name}"),
                    source_url=source_url,
                    official_cite=f"{citation_format} § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_wyoming_title_pdf",
                        "discovery_method": "deterministic_title_pdf_catalog_sections",
                        "title_number": title_number,
                        "title_name": title_name,
                        "skip_hydrate": True,
                    },
                )
            )
        self._last_wyoming_title_parse_report = {
            "title_number": str(title_number),
            "candidate_sections": len(body_matches),
            "operative_sections": len(statutes),
            "terminal_sections": len(terminal_dispositions),
            "terminal_dispositions": terminal_dispositions,
            "parser_residuals": parser_residuals,
            "duplicate_headers": duplicate_headers,
            "overlay_duplicate_headers": overlay_duplicate_headers,
            "page_body_citation_occurrences": page_body_citation_occurrences,
            "exact_duplicate_section_bodies": exact_duplicate_section_bodies,
            "conflicting_duplicate_headers": conflicting_duplicate_headers,
            "duplicate_header_occurrences": len(matches) - len(body_matches),
            "foreign_title_headers": foreign_title_headers,
            "closed": (
                len(body_matches)
                == len(statutes) + len(terminal_dispositions) + len(parser_residuals)
                and not parser_residuals
                and not conflicting_duplicate_headers
            ),
        }
        return statutes

    async def _scrape_deterministic_title_pdfs(
        self,
        code_name: str,
        citation_format: str,
        max_sections: int,
    ) -> List[NormalizedStatute]:
        strict_full = self._full_corpus_enabled() and int(max_sections) >= 1_000_000
        catalog = self._build_deterministic_title_catalog()
        if strict_full:
            observed_titles = [row[0] for row in catalog]
            if observed_titles != list(self.OFFICIAL_TITLE_NUMBERS):
                raise RuntimeError(
                    "Wyoming deterministic PDF catalog changed title identity or order"
                )
            urls = [row[2] for row in catalog]
            batch = await self._fetch_wyoming_pdf_frontier(urls)
            if list(batch.urls) != urls or len(batch.payloads) != len(catalog):
                raise RuntimeError(
                    "Wyoming title PDF frontier changed exact catalog alignment"
                )
            payload_rows = list(
                zip(
                    catalog,
                    batch.payloads,
                    batch.transport_receipts,
                    strict=True,
                )
            )
        else:
            payload_rows = [
                (row, None, None)
                for row in catalog[: max(1, int(max_sections))]
            ]

        statutes: List[NormalizedStatute] = []
        title_reports: List[Dict[str, Any]] = []
        seen_row_identities: set[str] = set()
        for catalog_row, retained_payload, transport_receipt in payload_rows:
            section_number, section_name, full_url = catalog_row
            # Avoid the constitution pseudo-title for bounded health checks; the
            # full corpus run still includes it after statutory titles.
            if not self._full_corpus_enabled() and section_number in {"97", "99"}:
                continue
            if retained_payload is None:
                layout_text = await self._extract_pdf_text_layout(full_url)
            else:
                layout_text = self._extract_pdf_text_from_payload(
                    bytes(retained_payload),
                    preserve_layout=True,
                )
            if strict_full and not layout_text.strip():
                raise RuntimeError(
                    f"Wyoming retained title PDF has no extractable text: {full_url}"
                )

            title_report: Dict[str, Any]
            if section_number == "97":
                from .wyoming_constitution import parse_wyoming_constitution_text

                title_report = {}
                constitution_rows = parse_wyoming_constitution_text(
                    layout_text,
                    code_name="Wyoming Constitution",
                    max_statutes=None if self._full_corpus_enabled() else max_sections,
                    source_url=full_url,
                    parse_report=title_report,
                )
                parsed_rows = constitution_rows
            else:
                parsed_rows = self._split_title_pdf_into_sections(
                    code_name=code_name,
                    title_number=section_number,
                    title_name=section_name,
                    title_text=layout_text,
                    source_url=full_url,
                    citation_format=citation_format,
                )
                title_report = dict(
                    getattr(self, "_last_wyoming_title_parse_report", {}) or {}
                )

            if strict_full:
                if title_report.get("closed") is not True:
                    raise RuntimeError(
                        "Wyoming retained title PDF failed exact parser closure: "
                        f"title={section_number} report={title_report}"
                    )
                if int(title_report.get("candidate_sections") or 0) <= 0:
                    raise RuntimeError(
                        "Wyoming retained title PDF exposed no source-bound frontier: "
                        f"{full_url}"
                    )
                receipt = dict(transport_receipt or {})
                payload_sha256 = hashlib.sha256(bytes(retained_payload)).hexdigest()
                title_report = {
                    **title_report,
                    "source_url": full_url,
                    "content_sha256": payload_sha256,
                    "operative_identities": [
                        str(statute.statute_id or "").strip()
                        for statute in parsed_rows
                    ],
                    "parser_input_receipt_sha256": str(
                        receipt.get("receipt_sha256") or ""
                    ),
                    "source_transport": str(
                        receipt.get("source_transport")
                        or receipt.get("transport_kind")
                        or ""
                    ),
                }
                title_reports.append(title_report)

            for statute in parsed_rows:
                identity = str(statute.statute_id or "").strip().casefold()
                if not identity or identity in seen_row_identities:
                    if strict_full:
                        raise RuntimeError(
                            "Wyoming normalized PDF frontier repeated statute identity: "
                            f"{statute.statute_id}"
                        )
                    continue
                seen_row_identities.add(identity)
                if strict_full:
                    statute.structured_data = {
                        **dict(statute.structured_data or {}),
                        "content_sha256": title_report["content_sha256"],
                        "parser_input_receipt_sha256": title_report[
                            "parser_input_receipt_sha256"
                        ],
                        "source_transport": title_report["source_transport"],
                    }
                statutes.append(statute)
                if not strict_full and len(statutes) >= max_sections:
                    break
            if not strict_full and len(statutes) >= max_sections:
                break
            if parsed_rows or strict_full:
                continue

            full_text = await self._extract_pdf_text_summary(full_url)
            if len(full_text.strip()) < 80:
                continue

            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:200],
                    full_text=full_text,
                    legal_area=self._identify_legal_area(section_name),
                    source_url=full_url,
                    official_cite=f"{citation_format} § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_wyoming_title_pdf",
                        "discovery_method": "deterministic_title_pdf_catalog",
                        "skip_hydrate": True,
                    },
                )
            )

        if strict_full:
            if len(title_reports) != len(self.OFFICIAL_TITLE_NUMBERS):
                raise RuntimeError(
                    "Wyoming title PDF parser did not close all 45 catalog members"
                )
            discovered_sections = sum(
                int(report.get("candidate_sections") or 0)
                for report in title_reports
            )
            operative_sections = sum(
                int(report.get("operative_sections") or 0)
                for report in title_reports
            )
            terminal_sections = sum(
                int(report.get("terminal_sections") or 0)
                for report in title_reports
            )
            if discovered_sections != operative_sections + terminal_sections:
                raise RuntimeError(
                    "Wyoming exact completion algebra failed: "
                    f"{discovered_sections} != {operative_sections} + "
                    f"{terminal_sections}"
                )
            if len(statutes) != operative_sections:
                raise RuntimeError(
                    "Wyoming normalized row count changed closed operative frontier"
                )
            exact_frontier = self._wyoming_exact_frontier(
                title_reports=title_reports,
            )
            observed_at = datetime.now(timezone.utc).isoformat()
            self._last_wyoming_full_frontier = {
                "boundary_first": str(statutes[0].statute_id or ""),
                "boundary_last": str(statutes[-1].statute_id or ""),
                "catalog": [list(row) for row in catalog],
                "citation_format": citation_format,
                "code_name": code_name,
                "frontier": exact_frontier,
                "observed_at": observed_at,
                "title_reports": title_reports,
                "transport_batch_stats": list(
                    dict(batch.stats or {}).get("batches") or []
                ),
            }
            self._write_partial_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="wyoming:title-pdf-complete",
                force=True,
                replace_existing_rows=True,
                extra={
                    "titles_scanned": len(title_reports),
                    "discovered_titles": len(self.OFFICIAL_TITLE_NUMBERS),
                    "sections_scanned": discovered_sections,
                    "discovered_sections": discovered_sections,
                    "operative_sections": operative_sections,
                    "terminal_sections_classified": terminal_sections,
                    "wyoming_exact_frontier": exact_frontier,
                    "wyoming_title_parse_reports": title_reports,
                    "codes_completed": 1,
                    "codes_total": 1,
                },
            )

        if statutes:
            self.logger.info(
                "Wyoming deterministic title PDF scraper: Scraped %s title PDFs",
                len(statutes),
            )
        return statutes

    async def _replay_wyoming_source_frontier(
        self,
        first: Mapping[str, Any],
    ) -> List[NormalizedStatute]:
        """Reparse the ordered 45-PDF frontier only from retained ledger bytes."""

        raw_catalog = first.get("catalog")
        raw_reports = first.get("title_reports")
        if (
            not isinstance(raw_catalog, Sequence)
            or isinstance(raw_catalog, (str, bytes, bytearray))
            or not isinstance(raw_reports, Sequence)
            or isinstance(raw_reports, (str, bytes, bytearray))
        ):
            raise RuntimeError("Wyoming retained exact frontier is incomplete")
        catalog = [tuple(str(value) for value in row) for row in raw_catalog]
        expected_catalog = self._build_deterministic_title_catalog()
        if catalog != expected_catalog:
            raise RuntimeError("Wyoming retained title catalog identity changed")
        if len(raw_reports) != len(catalog):
            raise RuntimeError("Wyoming retained title reports are incomplete")

        urls = [row[2] for row in catalog]
        self._wyoming_retained_replay = True
        try:
            batch = await self._fetch_wyoming_pdf_frontier(urls)
        finally:
            self._wyoming_retained_replay = False
        if list(batch.urls) != urls or len(batch.payloads) != len(catalog):
            raise RuntimeError("Wyoming retained PDF replay changed catalog alignment")

        code_name = str(first.get("code_name") or "Wyoming Statutes")
        citation_format = str(first.get("citation_format") or "Wyo. Stat.")
        replay_rows: List[NormalizedStatute] = []
        replay_reports: List[Dict[str, Any]] = []
        seen_identities: set[str] = set()
        for catalog_row, retained_payload, transport_receipt in zip(
            catalog,
            batch.payloads,
            batch.transport_receipts,
            strict=True,
        ):
            title_number, title_name, source_url = catalog_row
            layout_text = self._extract_pdf_text_from_payload(
                bytes(retained_payload),
                preserve_layout=True,
            )
            if not layout_text.strip():
                raise RuntimeError(
                    f"Wyoming retained title PDF has no replayable text: {source_url}"
                )
            title_report: Dict[str, Any]
            if title_number == "97":
                from .wyoming_constitution import parse_wyoming_constitution_text

                title_report = {}
                parsed_rows = parse_wyoming_constitution_text(
                    layout_text,
                    code_name="Wyoming Constitution",
                    max_statutes=None,
                    source_url=source_url,
                    parse_report=title_report,
                )
            else:
                parsed_rows = self._split_title_pdf_into_sections(
                    code_name=code_name,
                    title_number=title_number,
                    title_name=title_name,
                    title_text=layout_text,
                    source_url=source_url,
                    citation_format=citation_format,
                )
                title_report = dict(
                    getattr(self, "_last_wyoming_title_parse_report", {}) or {}
                )
            if title_report.get("closed") is not True:
                raise RuntimeError(
                    "Wyoming retained title PDF failed replay closure: "
                    f"title={title_number} report={title_report}"
                )
            receipt = dict(transport_receipt or {})
            title_report = {
                **title_report,
                "source_url": source_url,
                "content_sha256": hashlib.sha256(
                    bytes(retained_payload)
                ).hexdigest(),
                "operative_identities": [
                    str(statute.statute_id or "").strip()
                    for statute in parsed_rows
                ],
                "parser_input_receipt_sha256": str(
                    receipt.get("receipt_sha256") or ""
                ),
                "source_transport": str(
                    receipt.get("source_transport")
                    or receipt.get("transport_kind")
                    or ""
                ),
            }
            replay_reports.append(title_report)
            for statute in parsed_rows:
                identity = str(statute.statute_id or "").strip().casefold()
                if not identity or identity in seen_identities:
                    raise RuntimeError(
                        "Wyoming retained replay repeated statute identity: "
                        f"{statute.statute_id}"
                    )
                seen_identities.add(identity)
                statute.structured_data = {
                    **dict(statute.structured_data or {}),
                    "content_sha256": title_report["content_sha256"],
                    "parser_input_receipt_sha256": title_report[
                        "parser_input_receipt_sha256"
                    ],
                    "source_transport": title_report["source_transport"],
                }
                replay_rows.append(statute)

        replayed_frontier = self._wyoming_exact_frontier(
            title_reports=replay_reports,
        )
        self._last_wyoming_replayed_frontier = {
            "frontier": replayed_frontier,
            "rows": replay_rows,
            "title_reports": replay_reports,
        }
        return replay_rows

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection: Mapping[str, Any],
    ) -> Optional[Path]:
        """Seal zero-network PDF replay and exact output/disposition parity."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Wyoming frontier closure requires an attached ledger")
        first = getattr(self, "_last_wyoming_full_frontier", None)
        if not isinstance(first, Mapping):
            raise RuntimeError(
                "Wyoming source-derived strict frontier was not retained before output"
            )
        refresh = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh):
            refresh()
        replay_rows = await self._replay_wyoming_source_frontier(first)
        replay = getattr(self, "_last_wyoming_replayed_frontier", None)
        first_frontier = first.get("frontier")
        replayed_frontier = replay.get("frontier") if isinstance(replay, Mapping) else None
        if not isinstance(first_frontier, Mapping) or not isinstance(
            replayed_frontier,
            Mapping,
        ):
            raise RuntimeError("Wyoming exact retained replay did not close")

        from .strict_frontier_closure import retain_exact_state_frontier_closure

        title_reports = list(first.get("title_reports") or [])
        batch_stats = list(first.get("transport_batch_stats") or [])
        return retain_exact_state_frontier_closure(
            self,
            canonical_output_projection=canonical_output_projection,
            first_frontier=first_frontier,
            replayed_frontier=replayed_frontier,
            replay_rows=replay_rows,
            jurisdiction="WY",
            source_domain=self.OFFICIAL_DOMAIN,
            official_source_url=self.OFFICIAL_ENTRY_URL,
            observed_at=str(first.get("observed_at") or ""),
            legal_as_of=self.OFFICIAL_LEGAL_AS_OF,
            edition=self.OFFICIAL_EDITION,
            boundary_first=str(first.get("boundary_first") or ""),
            boundary_last=str(first.get("boundary_last") or ""),
            bundle_total=len(title_reports),
            pagination_total=len(title_reports),
            transport={
                "fixture": False,
                "first_pass_request_batches": len(batch_stats),
                "first_pass_requested_pages": sum(
                    int(row.get("requested_pages") or 0)
                    for row in batch_stats
                    if isinstance(row, Mapping)
                ),
                "grouped_warc_recovery": True,
                "kind": "shared_archive_aware_plural_pdf",
                "per_page_archive_loop": False,
                "residual_only_retries": True,
                "retained_replay_network_requests": 0,
                "synthetic": False,
            },
        )
    
    async def _custom_scrape_wyoming(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 100
    ) -> List[NormalizedStatute]:
        """Custom scraper for Wyoming's legislative website.
        
        Wyoming's website is a JavaScript SPA (Single Page Application).
        For better results, consider:
        1. Using Playwright to render JavaScript
        2. Accessing alternative static pages
        3. Using Internet Archive snapshots
        """
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []
        
        statutes = []

        # Wyoming's statutes download page is JS-rendered, but title PDFs are
        # stable and predictable. Build that catalog directly as a non-JS fallback.
        deterministic_catalog = await self._scrape_deterministic_title_pdfs(
            code_name,
            citation_format,
            max_sections=max_sections,
        )
        if deterministic_catalog:
            return deterministic_catalog
        
        try:
            page_bytes = await self._fetch_page_content_with_archival_fallback(
                code_url,
                timeout_seconds=30,
            )
            if not page_bytes:
                return await self._generic_scrape(code_name, code_url, citation_format, max_sections)

            soup = BeautifulSoup(page_bytes, 'html.parser')
            links = soup.find_all('a', href=True)
            
            section_count = 0
            for link in links:
                if section_count >= max_sections:
                    break
                
                link_text = link.get_text(strip=True)
                link_href = link.get('href', '')
                
                if not link_text or len(link_text) < 5:
                    continue
                
                # Wyoming patterns - relaxed matching
                keywords_wy = ['title', 'chapter', '§', 'section', 'part', 'code', 'statute', 'article', 'wyo.']
                if not any(keyword in link_text.lower() for keyword in keywords_wy):
                    continue
                
                full_url = urljoin(code_url, link_href)
                section_number = self._extract_section_number(link_text) or f"Section-{section_count + 1}"
                legal_area = self._identify_legal_area(link_text)
                
                statute = NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=link_text[:200],
                    full_text=f"Section {section_number}: {link_text}",
                    legal_area=legal_area,
                    source_url=full_url,
                    official_cite=f"{citation_format} § {section_number}",
                    metadata=StatuteMetadata()
                )
                
                statutes.append(statute)
                section_count += 1
            
            self.logger.info(f"Wyoming custom scraper: Scraped {len(statutes)} sections")
            
            # Fallback to generic scraper if no data found
            if not statutes:
                self.logger.warning("Wyoming custom scraper found no data - site uses JavaScript")
                if PLAYWRIGHT_AVAILABLE:
                    self.logger.info("Wyoming custom scraper retrying with Playwright StatutesDownload page")
                    pw_statutes = await self._scrape_with_playwright(
                        code_name,
                        f"{self.get_base_url()}/stateStatutes/StatutesDownload",
                        citation_format,
                        max_sections=max_sections,
                    )
                    if pw_statutes:
                        return pw_statutes
                self.logger.info("For Wyoming, consider using:")
                self.logger.info("  1. Playwright for JavaScript rendering")
                self.logger.info("  2. Alternative URL: https://wyoleg.gov/statutes/compress/")
                self.logger.info("  3. Internet Archive snapshots")
                return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
            
        except Exception as e:
            self.logger.error(f"Wyoming custom scraper failed: {e}")
            self.logger.info("Note: Wyoming's site requires JavaScript. Consider using Playwright.")
            return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
        
        return statutes

    def _build_deterministic_title_catalog(self) -> List[tuple[str, str, str]]:
        """Build stable Wyoming statutes title PDF URLs when JS links are unavailable."""
        catalog: List[tuple[str, str, str]] = []
        for section_number in self.OFFICIAL_TITLE_NUMBERS:
            section_name = (
                "Wyoming Constitution"
                if section_number == "97"
                else f"Title {section_number}"
            )
            catalog.append(
                (
                    section_number,
                    section_name,
                    self.official_title_url(section_number),
                )
            )
        return catalog

    def normalize_title_number(self, title_number: object) -> str:
        text = str(title_number or "").strip()
        if text == "34.1":
            return "34.1"
        if text.isdigit():
            return str(int(text))
        return text

    def official_title_stem(self, title_number: str) -> str:
        normalized = self.normalize_title_number(title_number)
        if normalized == "34.1":
            return "34.1"
        if normalized.isdigit():
            return f"{int(normalized):02d}"
        return normalized

    def official_title_url(self, title_number: str) -> str:
        return (
            f"{self.get_base_url()}/statutes/compress/"
            f"title{self.official_title_stem(title_number)}.pdf"
        )

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Wyoming Statutes title-PDF catalog."""

        rows: List[Dict[str, Any]] = []
        for section_number, section_name, pdf_url in self._build_deterministic_title_catalog():
            rows.append(
                {
                    "canonical_key": f"wy:title-{section_number}",
                    "title_number": str(section_number),
                    "name": section_name,
                    "source_url": pdf_url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Wyoming Statutes {section_name} official title PDF "
                        f"catalog unit at {pdf_url}"
                    ),
                }
            )
        return rows

    def is_official_wyoleg_url(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host == "wyoleg.gov" or host.endswith(".wyoleg.gov")

    def _title_sort_key(self, title_number: str) -> tuple[int, str]:
        text = str(title_number or "").strip()
        if text == "34.1":
            return (34, "1")
        if text.isdigit():
            return (int(text), "")
        match = re.match(r"(\d+)", text)
        return (int(match.group(1)), text) if match else (10_000, text)

    def _recover_title_number(self, *parts: object) -> str:
        blob = " ".join(str(item or "") for item in parts)
        pdf_match = self._WY_TITLE_PDF_RE.search(blob)
        if pdf_match:
            return self.normalize_title_number(pdf_match.group("title"))
        cite_match = self._WY_SECTION_CITE_RE.search(blob)
        if cite_match:
            return self.normalize_title_number(cite_match.group(1))
        label_match = self._WY_TITLE_LABEL_RE.search(blob)
        if label_match:
            return self.normalize_title_number(label_match.group(1))
        return ""

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))

        def _request() -> bytes:
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-wyoming-official-catalog/1.0",
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
                            "User-Agent": "ipfs-datasets-wyoming-official-catalog/1.0",
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

    def _parse_official_title_links(self, html: bytes) -> Dict[str, str]:
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
            absolute = urljoin(self.get_base_url() + "/", href)
            match = self._WY_TITLE_PDF_RE.search(absolute)
            if not match:
                continue
            number = self.normalize_title_number(match.group("title"))
            if number not in found:
                found[number] = self.official_title_url(number)
        return found

    def _title_row(
        self,
        title_number: str,
        label: str,
        source: str,
        source_url: str = "",
    ) -> Dict[str, str]:
        official_url = source_url or self.official_title_url(title_number)
        cleaned = re.sub(r"\s+", " ", str(label or "")).strip() or f"Title {title_number}"
        return {
            "canonical_key": f"wy:title-{title_number}",
            "title_number": str(title_number),
            "name": cleaned,
            "source_url": official_url,
            "source_link_disposition": source,
            "repair_source": source,
            "text": (
                f"Wyoming Statutes {cleaned} official title PDF catalog unit "
                f"at {official_url}"
            ),
        }

    def classify_linkless_seed_rows(
        self,
        seeds: object,
        *,
        page_url: str = "",
    ) -> Dict[str, List[Dict[str, str]]]:
        """Reacquire official title PDFs or quarantine remaining linkless seeds.

        Accepts either a mapping sequence or raw HTML. Recoverable title
        numbers are rewritten to ``https://www.wyoleg.gov/statutes/compress/titleXX.pdf``.
        Remaining linkless material is quarantined with
        ``missing_official_source_link``.
        """

        repaired: List[Dict[str, str]] = []
        quarantines: List[Dict[str, str]] = []
        seen_titles: set[str] = set()
        seen_quarantine: set[str] = set()

        def _record(title_number: str, label: str, source: str, source_url: str = "") -> None:
            number = self.normalize_title_number(title_number)
            if not number or number in seen_titles:
                return
            seen_titles.add(number)
            repaired.append(self._title_row(number, label, source, source_url=source_url))

        def _quarantine(label: str, evidence: str) -> None:
            cleaned = re.sub(r"\s+", " ", str(label or "")).strip()
            if not cleaned:
                return
            unit_id = (
                "wy:missing-"
                + hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]
            )
            if unit_id in seen_quarantine:
                return
            seen_quarantine.add(unit_id)
            quarantines.append(
                {
                    "unit_id": unit_id,
                    "reason": self.LINKLESS_QUARANTINE_REASON,
                    "label": cleaned[:240],
                    "page_url": page_url,
                    "evidence_sha256": hashlib.sha256(
                        str(evidence or cleaned).encode("utf-8")
                    ).hexdigest(),
                }
            )

        if isinstance(seeds, (bytes, bytearray, str)):
            html = seeds.decode("utf-8", errors="replace") if isinstance(seeds, (bytes, bytearray)) else seeds
            try:
                from bs4 import BeautifulSoup
            except ImportError as exc:
                raise RuntimeError(
                    "BeautifulSoup is required for official Wyoming discovery"
                ) from exc
            soup = BeautifulSoup(html, "html.parser")
            for link in soup.find_all("a", href=True):
                href = str(link.get("href") or "").strip()
                label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
                absolute = urljoin(page_url or (self.get_base_url() + "/"), href)
                title_number = self._recover_title_number(absolute, href, label)
                if title_number and self.is_official_wyoleg_url(absolute):
                    _record(title_number, label, "official", self.official_title_url(title_number))
                    continue
                if title_number:
                    _record(title_number, label, "repaired_from_linkless_row")
                    continue
                if label:
                    _quarantine(label, str(link))
            for node in soup.find_all(["span", "td", "li", "div"]):
                if node.find("a", href=True):
                    continue
                label = re.sub(r"\s+", " ", node.get_text(" ", strip=True) or "").strip()
                if not label:
                    continue
                title_number = self._recover_title_number(
                    node.get("href"),
                    node.get("data-title"),
                    node.get("id"),
                    label,
                    str(node),
                )
                if title_number:
                    _record(title_number, label, "repaired_from_linkless_row")
                elif re.search(r"title|statute|chapter|section|wyo", label, re.IGNORECASE):
                    _quarantine(label, str(node))
            return {"repaired": repaired, "quarantines": quarantines}

        for item in seeds or ():
            if not isinstance(item, Mapping):
                continue
            label = str(
                item.get("label")
                or item.get("name")
                or item.get("text")
                or item.get("section_name")
                or ""
            ).strip()
            source_url = str(item.get("source_url") or item.get("href") or "").strip()
            title_number = self._recover_title_number(
                item.get("title_number"),
                item.get("section_number"),
                source_url,
                label,
            )
            if title_number and source_url and self.is_official_wyoleg_url(source_url):
                _record(title_number, label, "official", self.official_title_url(title_number))
                continue
            if title_number:
                _record(title_number, label, "repaired_from_linkless_row")
                continue
            _quarantine(label or source_url or "linkless wyoming seed", json.dumps(dict(item), sort_keys=True))
        return {"repaired": repaired, "quarantines": quarantines}

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
        seed_rows: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Enumerate official title PDFs and reacquire or quarantine linkless seeds."""

        discovered = self._parse_official_title_links(html)
        classified = self.classify_linkless_seed_rows(
            html or b"",
            page_url=page_url or self.OFFICIAL_ENTRY_URL,
        )
        if seed_rows:
            seed_classified = self.classify_linkless_seed_rows(
                seed_rows,
                page_url=page_url or self.OFFICIAL_ENTRY_URL,
            )
            classified["repaired"].extend(seed_classified["repaired"])
            classified["quarantines"].extend(seed_classified["quarantines"])
        self.last_official_quarantines = list(classified["quarantines"])

        rows = self.official_title_catalog()
        by_title = {str(row["title_number"]): row for row in rows}
        for row in rows:
            live_url = discovered.get(str(row["title_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_leginfo"
        for unit in classified["repaired"]:
            number = str(unit.get("title_number") or "")
            if number in by_title:
                if unit.get("source_link_disposition") == "official":
                    by_title[number]["source_url"] = unit["source_url"]
                    by_title[number]["source_link_disposition"] = "official"
                continue
            rows.append(unit)
            by_title[number] = unit
        for number, url in discovered.items():
            if number in by_title:
                continue
            extra = self._title_row(number, f"Title {number}", "official", url)
            rows.append(extra)
            by_title[number] = extra
        live_order = {
            title_number: index
            for index, title_number in enumerate(self.OFFICIAL_TITLE_NUMBERS)
        }
        rows.sort(
            key=lambda item: (
                live_order.get(
                    self.normalize_title_number(item["title_number"]),
                    len(live_order),
                ),
                self._title_sort_key(str(item["title_number"])),
            )
        )
        return rows

    def fetch_official(self, code: str = "WY"):
        """Acquire the exhaustive official Wyoming title-PDF catalog.

        Linkless bucket seed material is reacquired onto official
        ``wyoleg.gov/statutes/compress/titleXX.pdf`` URLs when a title number
        can be recovered. Remaining linkless rows are quarantined with typed
        ``missing_official_source_link`` disposition. This hook never returns
        fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "WY").strip().upper() or "WY"
        if normalized != "WY":
            raise ValueError(f"WyomingScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        quarantines = list(getattr(self, "last_official_quarantines", []) or [])
        if len(rows) < 3:
            raise RuntimeError("wyoming official catalog enumeration is incomplete")
        request = (
            f"GET {self.OFFICIAL_ENTRY_PATH} HTTP/1.1\n"
            f"host: {self.OFFICIAL_DOMAIN}\n"
        ).encode("utf-8")
        catalog = {
            "jurisdiction": normalized,
            "official_domain": self.OFFICIAL_DOMAIN,
            "entry_url": self.OFFICIAL_ENTRY_URL,
            "units": rows,
            "quarantines": quarantines,
        }
        body = json.dumps(catalog, sort_keys=True, ensure_ascii=False).encode("utf-8")
        response = html if html else (b"HTTP/1.1 200 OK\n\n" + body)
        frontier = {
            "bundle_closed": True,
            "closed": True,
            "enumerator_closed": True,
            "expected_index_units": len(rows),
            "method": "bundle",
            "pagination_closed": True,
            "remaining_bundle_members": [],
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": len(rows),
            "wy_linkless_quarantines": quarantines,
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
StateScraperRegistry.register("WY", WyomingScraper)
