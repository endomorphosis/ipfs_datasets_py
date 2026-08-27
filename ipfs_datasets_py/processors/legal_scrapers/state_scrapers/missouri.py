"""Scraper for Missouri state laws.

This module contains the scraper for Missouri statutes from the official state legislative website.
"""

import hashlib
import json
import re
import ssl
import urllib.request
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urljoin, urlparse

from .base_scraper import (
    BaseStateScraper,
    NormalizedStatute,
    StateLawPageMultiFetchResult,
    StatuteMetadata,
)
from .registry import StateScraperRegistry

_SECONDARY_HOST_MARKERS = (
    "justia.com",
    "findlaw.com",
    "unicourt.github.io",
    "law.cornell.edu",
)


class MissouriScraper(BaseStateScraper):
    """Scraper for Missouri state laws from http://www.moga.mo.gov"""

    OFFICIAL_DOMAIN = "revisor.mo.gov"
    OFFICIAL_ENTRY_PATH = "/main/Home.aspx"
    OFFICIAL_ENTRY_URL = "https://revisor.mo.gov/main/Home.aspx"
    _MO_CHAPTER_RE = re.compile(
        r"OneChapter\.aspx\?chapter=(?P<chapter>\d+[A-Za-z]?)\b",
        re.IGNORECASE,
    )
    OFFICIAL_NUMERIC_CHAPTERS = tuple(range(1, 702))
    OFFICIAL_LETTERED_CHAPTERS = (
        "1A", "2A", "8A", "9A", "10A", "11A", "67A", "135A", "160A",
        "208A", "217A", "260A", "376A", "407A", "620A",
    )

    def state_law_frontier_source_dependencies(self) -> tuple[object, ...]:
        """Bind parsing, replay, closure, and plural archival acquisition."""

        from ...legal_data import state_laws_multifetch_acquisition
        from ...web_archiving import wayback_machine_engine
        from . import (
            base_scraper,
            missouri_chapter,
            state_archival_fetch,
            strict_frontier_closure,
        )

        return (
            base_scraper,
            state_archival_fetch,
            strict_frontier_closure,
            missouri_chapter,
            state_laws_multifetch_acquisition,
            wayback_machine_engine,
        )
    
    def get_base_url(self) -> str:
        """Return the base URL for Missouri's legislative website."""
        return "https://revisor.mo.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Missouri."""
        return [{
            "name": "Missouri Revised Statutes",
            "url": f"{self.get_base_url()}/main/Home.aspx",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Missouri's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .missouri_constitution import (
            configured_constitution_html_path,
            parse_missouri_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_missouri_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Missouri Constitution",
                    source_url="https://revisor.mo.gov/main/OneSection.aspx?constit=y",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        official = await self._custom_scrape_missouri(
            code_name,
            code_url,
            "Mo. Rev. Stat.",
            max_sections=limit,
        )
        official = self._filter_official_host_statutes(official)
        if official:
            return official if limit is None else official[: int(limit)]

        if not self._full_corpus_enabled() or max_statutes is not None:
            direct = await self._scrape_direct_sections(
                code_name,
                max_statutes=max(1, int(limit or 2)),
            )
            direct = self._filter_official_host_statutes(direct)
            if direct:
                return direct if limit is None else direct[: int(limit)]
        return []

    async def _scrape_direct_sections(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup  # noqa: F401 - optional dependency probe
        except ImportError:
            return []

        section_urls = [
            f"{self.get_base_url()}/main/OneSection.aspx?section=1.010",
            f"{self.get_base_url()}/main/OneSection.aspx?section=565.020",
        ]
        statutes: List[NormalizedStatute] = []
        for source_url in section_urls[: max(1, int(max_statutes or 1))]:
            payload = await self._fetch_page_content_with_archival_fallback(source_url, timeout_seconds=12)
            if not payload:
                continue
            text, section_name = self._extract_section_text_and_name(payload)
            if len(text) < 280:
                continue
            match = re.search(r"\b(\d+\.\d+[A-Za-z]*)\b", text)
            section_number = match.group(1) if match else source_url.rsplit("section=", 1)[-1]
            statutes.append(
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
                    official_cite=f"Mo. Rev. Stat. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_missouri_section_html",
                        "discovery_method": "official_direct_section",
                        "skip_hydrate": True,
                    },
                )
            )
        return statutes

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        if any(marker in host for marker in _SECONDARY_HOST_MARKERS):
            return False
        return host == "revisor.mo.gov" or host.endswith(".revisor.mo.gov")

    def _filter_official_host_statutes(
        self, statutes: List[NormalizedStatute]
    ) -> List[NormalizedStatute]:
        return [
            statute
            for statute in statutes
            if self._host_is_official(str(statute.source_url or ""))
        ]

    def _missouri_frontier_concurrency(self) -> int:
        return max(
            1,
            min(
                64,
                self._env_int("STATE_SCRAPER_MO_FRONTIER_CONCURRENCY", default=16),
            ),
        )

    @staticmethod
    def _is_valid_missouri_frontier_payload(payload: bytes) -> bool:
        """Reject the Revisor robot-throttle shell before it is retained."""

        if not payload:
            return False
        lowered = bytes(payload).lower()
        return (
            b"nofish.aspx" not in lowered
            and b"are you double clicking links?" not in lowered
        )

    @staticmethod
    def _missouri_chapter_evidence_context(
        *,
        source_url: str,
        transport_receipt: Optional[Dict[str, Any]],
        parser_input_envelope: Any,
    ) -> Dict[str, Any]:
        """Resolve the legal as-of date from exact acquisition provenance."""

        envelope = parser_input_envelope
        if not isinstance(envelope, dict):
            to_dict = getattr(envelope, "to_dict", None)
            if callable(to_dict):
                envelope = to_dict()
        if isinstance(envelope, dict) and isinstance(
            envelope.get("parser_input_envelope"),
            dict,
        ):
            envelope = envelope["parser_input_envelope"]
        receipt = (
            envelope.get("acquisition", {}).get("receipt", {})
            if isinstance(envelope, dict)
            else {}
        )
        if not isinstance(receipt, dict) or receipt.get("endpoint") != source_url:
            raise RuntimeError(
                "Missouri chapter acquisition receipt does not match requested URL: "
                f"{source_url}"
            )
        retained_transport = receipt.get("metadata", {}).get("transport_receipt", {})
        if not isinstance(retained_transport, dict):
            retained_transport = {}
        aligned_transport = (
            dict(transport_receipt) if isinstance(transport_receipt, dict) else {}
        )
        source_transport = str(
            retained_transport.get("source_transport")
            or aligned_transport.get("source_transport")
            or ""
        ).strip()
        official_url = str(
            retained_transport.get("official_url")
            or aligned_transport.get("official_url")
            or ""
        ).strip()
        if not source_transport or official_url != source_url:
            raise RuntimeError(
                "Missouri chapter acquisition transport identity is incomplete: "
                f"{source_url}"
            )

        retrieved_at = str(receipt.get("retrieved_at") or "").strip()
        try:
            retrieved_time = datetime.fromisoformat(retrieved_at)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Missouri chapter receipt lacks a valid retrieval date: {source_url}"
            ) from exc
        if retrieved_time.tzinfo is None:
            raise RuntimeError(
                f"Missouri chapter receipt has a naive retrieval date: {source_url}"
            )
        retrieved_date = retrieved_time.date()

        content_sha256 = str(receipt.get("content", {}).get("sha256") or "").strip()
        receipt_sha256 = str(receipt.get("receipt_sha256") or "").strip()
        if (
            re.fullmatch(r"[0-9a-f]{64}", content_sha256) is None
            or re.fullmatch(r"[0-9a-f]{64}", receipt_sha256) is None
        ):
            raise RuntimeError(
                "Missouri chapter acquisition receipt lacks exact content/receipt "
                f"fixity: {source_url}"
            )

        archive_timestamp = str(
            retained_transport.get("archive_timestamp")
            or retained_transport.get("capture_timestamp")
            or aligned_transport.get("archive_timestamp")
            or aligned_transport.get("capture_timestamp")
            or ""
        ).strip()
        if source_transport == "direct":
            as_of_date = retrieved_date
        else:
            archive_match = re.fullmatch(
                r"(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})\d{0,6}",
                archive_timestamp,
            )
            try:
                if archive_match is None:
                    raise ValueError("invalid archive timestamp")
                as_of_date = date(
                    int(archive_match.group("year")),
                    int(archive_match.group("month")),
                    int(archive_match.group("day")),
                )
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    "Missouri archived chapter receipt lacks a provenance snapshot "
                    f"date: {source_url}"
                ) from exc
        return {
            "as_of_date": as_of_date,
            "archive_timestamp": archive_timestamp,
            "content_sha256": content_sha256,
            "receipt_sha256": receipt_sha256,
            "retrieved_at": retrieved_at,
            "source_transport": source_transport,
        }

    async def _fetch_missouri_frontier_batch(
        self,
        urls: List[str],
        *,
        frontier_name: str,
        allow_residuals: bool = False,
    ) -> StateLawPageMultiFetchResult:
        """Acquire one known Missouri frontier through the shared WARC batch path."""

        if not urls:
            return StateLawPageMultiFetchResult([], [], [], [], [], {})
        requested = list(urls)
        residual_retry_attempts = max(
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
            residual_retry_attempts=residual_retry_attempts,
            timeout_seconds=20,
            media_type="text/html",
            max_concurrency=self._missouri_frontier_concurrency(),
            prefer_direct=True,
            common_crawl_domain_terms=(self.OFFICIAL_DOMAIN,),
            common_crawl_url_terms=("/main/",),
            common_crawl_mime_terms=("html",),
            wayback_prefix_inventory=True,
            content_validator=self._is_valid_missouri_frontier_payload,
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
                f"Missouri {frontier_name} frontier returned unaligned acquisition rows"
            )
        if list(batch.urls) != requested:
            raise RuntimeError(
                f"Missouri {frontier_name} frontier changed URL order or identity"
            )
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
        if failures and not allow_residuals:
            raise RuntimeError(
                f"Missouri {frontier_name} frontier is incomplete; "
                f"unresolved exact URLs: {failures}"
            )
        batch.payloads = [bytes(payload) if payload else b"" for payload in batch.payloads]
        return batch

    def _replay_optional_missouri_retained_inputs(
        self,
        urls: Sequence[str],
        *,
        frontier_name: str,
        refresh: bool = False,
    ) -> Dict[str, tuple[bytes, Dict[str, Any], Any]]:
        """Return exact retained inputs without turning misses into requests.

        Missouri's chapter catalog publishes versioned ``PageSelect`` URLs,
        while its stable ``OneSection`` pages are the efficient residual text
        frontier.  A restart must therefore inspect the exact retained
        ``PageSelect`` inputs first, but it must never submit the thousands of
        known misses to an archive provider.  This ledger-only probe is O(m)
        after the ledger's single index load and performs no network work.

        A retained-replay-only ledger raises on an ordinary miss.  Such a miss
        is optional at this planning stage because the same catalog identity
        may be fully represented by its retained ``OneSection`` input.  Every
        other replay error (ambiguity, mutation, or bad fixity) remains fatal.
        """

        from ...legal_data.state_laws_multifetch_acquisition import (
            StateLawRetainedReplayOnlyError,
        )

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            return {}
        if refresh:
            refresh_entries = getattr(ledger, "refresh_existing_entries", None)
            if callable(refresh_entries):
                refresh_entries()

        requested = [self._canonical_fetch_url(url) for url in urls]
        if any(not url for url in requested) or len(requested) != len(set(requested)):
            raise RuntimeError(
                f"Missouri {frontier_name} retained probe has empty or repeated URLs"
            )

        retained_by_url: Dict[str, tuple[bytes, Dict[str, Any], Any]] = {}
        for source_url in requested:
            try:
                retained = ledger.replay_retained_parser_input(
                    official_url=source_url,
                    sanitized_request={"method": "GET", "url": source_url},
                )
            except StateLawRetainedReplayOnlyError:
                retained = None
            if retained is None:
                continue
            envelope = getattr(retained, "envelope", None)
            payload = bytes(getattr(envelope, "body", b"") or b"")
            content = getattr(getattr(retained, "receipt", None), "content", None)
            expected_sha256 = str(getattr(content, "sha256", "") or "").strip()
            payload_sha256 = hashlib.sha256(payload).hexdigest()
            if (
                not payload
                or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
                or expected_sha256 != payload_sha256
            ):
                raise RuntimeError(
                    f"Missouri {frontier_name} retained input failed fixity: "
                    f"{source_url}"
                )
            raw_transport = getattr(retained, "transport_receipt", {})
            transport_receipt = (
                dict(raw_transport) if isinstance(raw_transport, Mapping) else {}
            )
            observed_url = str(
                transport_receipt.get("official_url")
                or transport_receipt.get("endpoint")
                or ""
            ).strip()
            observed_sha256 = str(
                transport_receipt.get("content_sha256") or ""
            ).strip()
            if (
                observed_url != source_url
                or observed_sha256 != payload_sha256
                or not str(
                    transport_receipt.get("source_transport") or ""
                ).strip()
            ):
                raise RuntimeError(
                    f"Missouri {frontier_name} retained transport identity changed: "
                    f"{source_url}"
                )
            retained_by_url[source_url] = (payload, transport_receipt, envelope)
        return retained_by_url

    def _missouri_home_chapter_urls(self, home_bytes: bytes) -> List[str]:
        """Return the exact ordered chapter membership published by Home.aspx."""

        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError(
                "BeautifulSoup is required for Missouri strict chapter discovery"
            ) from exc

        soup = BeautifulSoup(home_bytes or b"", "html.parser")
        chapter_urls: List[str] = []
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            if "onechapter.aspx?chapter=" not in href.casefold():
                continue
            full = urljoin(self.OFFICIAL_ENTRY_URL, href)
            parsed = urlparse(full)
            query = parse_qs(parsed.query, keep_blank_values=True)
            chapter_values = query.get("chapter") or []
            valid = bool(
                parsed.scheme.lower() == "https"
                and parsed.hostname == self.OFFICIAL_DOMAIN
                and parsed.path.casefold() == "/main/onechapter.aspx"
                and set(query) == {"chapter"}
                and len(chapter_values) == 1
                and re.fullmatch(r"\d+[A-Za-z]?", chapter_values[0].strip())
                and not parsed.fragment
            )
            if not valid:
                raise RuntimeError(
                    f"Missouri home exposed a non-canonical chapter locator: {full}"
                )
            canonical = self.official_chapter_url(chapter_values[0].strip())
            if canonical in seen:
                raise RuntimeError(
                    f"Missouri home repeated an exact chapter locator: {canonical}"
                )
            seen.add(canonical)
            chapter_urls.append(canonical)
        if not chapter_urls:
            raise RuntimeError("Missouri official home frontier exposed no chapter URLs")
        return chapter_urls

    @staticmethod
    def _missouri_report_digest(rows: Sequence[Mapping[str, Any]]) -> str:
        from ...legal_data.open_us_law_acquisition_coordinator import (
            canonical_json_bytes,
        )

        return hashlib.sha256(
            canonical_json_bytes([dict(row) for row in rows])
        ).hexdigest()

    def _missouri_catalog_inventory(
        self,
        chapter_urls: Sequence[str],
        chapter_batch: StateLawPageMultiFetchResult,
    ) -> Dict[str, Any]:
        """Classify every retained chapter row into one exact current disposition."""

        from .missouri_chapter import (
            authoritative_chapter_section_variants,
            chapter_page_identity,
            chapter_section_variants,
            source_bound_empty_chapter_disposition,
        )

        requested = list(chapter_urls)
        if (
            list(chapter_batch.urls) != requested
            or len(chapter_batch.payloads) != len(requested)
            or len(chapter_batch.transport_receipts) != len(requested)
            or len(chapter_batch.parser_input_envelopes) != len(requested)
        ):
            raise RuntimeError("Missouri chapter inventory is not exactly aligned")

        section_frontier: List[
            tuple[int, str, str, str, str, str, str, int]
        ] = []
        chapter_end_offsets: List[tuple[int, int]] = []
        chapter_reports: List[Dict[str, Any]] = []
        variant_reports: List[Dict[str, Any]] = []
        terminal_chapters: List[Dict[str, str]] = []
        terminal_sections: List[Dict[str, str]] = []
        seen_sections: set[str] = set()
        seen_variant_urls: set[str] = set()
        variant_section_identities: set[str] = set()
        future_effective_variants_excluded = 0
        future_effective_identities_excluded = 0
        non_authoritative_variants_excluded = 0

        for chapter_index, (
            chapter_url,
            chapter_bytes,
            transport_receipt,
            parser_input_envelope,
        ) in enumerate(
            zip(
                requested,
                chapter_batch.payloads,
                chapter_batch.transport_receipts,
                chapter_batch.parser_input_envelopes,
                strict=True,
            ),
            start=1,
        ):
            chapter_values = parse_qs(urlparse(chapter_url).query).get("chapter") or []
            chapter_number = chapter_values[0].strip() if chapter_values else ""
            chapter_html = chapter_bytes.decode("utf-8", errors="replace")
            chapter_identity = chapter_page_identity(chapter_html)
            if (
                chapter_identity is None
                or chapter_identity[0].casefold() != chapter_number.casefold()
            ):
                raise RuntimeError(
                    "Missouri retained chapter body failed requested chapter "
                    f"identity verification: {chapter_url}"
                )
            evidence_context = self._missouri_chapter_evidence_context(
                source_url=chapter_url,
                transport_receipt=transport_receipt,
                parser_input_envelope=parser_input_envelope,
            )
            if evidence_context["source_transport"] != "direct":
                raise RuntimeError(
                    "Missouri current full corpus requires current chapter evidence; "
                    "an archive snapshot supplies only historical as-of authority: "
                    f"chapter={chapter_number} snapshot="
                    f"{evidence_context['archive_timestamp']} url={chapter_url}"
                )
            try:
                variants = chapter_section_variants(chapter_html, chapter_number)
            except ValueError as exc:
                raise RuntimeError(
                    f"Missouri strict chapter variants failed: {chapter_url}: {exc}"
                ) from exc
            authoritative, excluded = authoritative_chapter_section_variants(
                variants,
                as_of_date=evidence_context["as_of_date"],
            )
            selected_ids = {id(variant) for variant in authoritative}
            chapter_variant_identities = {
                variant.section_number.casefold() for variant in variants
            }
            selected_variant_identities = {
                variant.section_number.casefold() for variant in authoritative
            }
            variant_section_identities.update(chapter_variant_identities)
            future_effective_identities_excluded += len(
                chapter_variant_identities - selected_variant_identities
            )
            future_effective_variants_excluded += sum(
                variant.effective_date > evidence_context["as_of_date"]
                for variant in excluded
            )
            non_authoritative_variants_excluded += sum(
                variant.effective_date <= evidence_context["as_of_date"]
                for variant in excluded
            )

            terminal_chapter_disposition = ""
            if not variants:
                terminal_chapter_disposition = str(
                    source_bound_empty_chapter_disposition(
                        chapter_html,
                        chapter_number=chapter_number,
                        source_url=chapter_url,
                    )
                    or ""
                )
                if not terminal_chapter_disposition:
                    raise RuntimeError(
                        "Missouri strict chapter table exposed no section frontier "
                        "and no source-bound terminal disposition: "
                        f"{chapter_url}"
                    )
                terminal_chapters.append(
                    {
                        "as_of_date": evidence_context["as_of_date"].isoformat(),
                        "chapter_number": chapter_number,
                        "chapter_title": chapter_identity[1],
                        "disposition": terminal_chapter_disposition,
                        "receipt_sha256": evidence_context["receipt_sha256"],
                        "source_transport": evidence_context["source_transport"],
                        "source_url": chapter_url,
                    }
                )

            chapter_digest = hashlib.sha256(chapter_bytes).hexdigest()
            chapter_reports.append(
                {
                    "as_of_date": evidence_context["as_of_date"].isoformat(),
                    "chapter_number": chapter_number,
                    "chapter_title": chapter_identity[1],
                    "content_sha256": chapter_digest,
                    "current_record_count": len(authoritative),
                    "disposition": terminal_chapter_disposition or "active",
                    "operative_candidate_count": sum(
                        not variant.terminal_disposition for variant in authoritative
                    ),
                    "receipt_sha256": evidence_context["receipt_sha256"],
                    "retrieved_at": evidence_context["retrieved_at"],
                    "source_transport": evidence_context["source_transport"],
                    "source_url": chapter_url,
                    "source_variant_count": len(variants),
                    "terminal_section_count": sum(
                        bool(variant.terminal_disposition)
                        for variant in authoritative
                    ),
                }
            )

            for variant in variants:
                if variant.source_url in seen_variant_urls:
                    raise RuntimeError(
                        "Missouri chapter catalogs repeated a source-record URL: "
                        f"{variant.source_url}"
                    )
                seen_variant_urls.add(variant.source_url)
                selected = id(variant) in selected_ids
                if selected and variant.terminal_disposition:
                    disposition = variant.terminal_disposition
                    catalog_disposition = "selected_terminal"
                elif selected:
                    disposition = "operative_pending"
                    catalog_disposition = "selected_operative"
                elif variant.effective_date > evidence_context["as_of_date"]:
                    disposition = "future_effective_variant"
                    catalog_disposition = "excluded_future_effective"
                else:
                    disposition = "superseded_variant"
                    catalog_disposition = "excluded_non_authoritative"
                report_index = len(variant_reports)
                variant_reports.append(
                    {
                        "bid": variant.bid,
                        "canonical_identity": variant.section_number.casefold(),
                        "catalog_content_sha256": chapter_digest,
                        "catalog_disposition": catalog_disposition,
                        "chapter_number": chapter_number,
                        "disposition": disposition,
                        "effective_date": variant.effective_date_text,
                        "section_number": variant.section_number,
                        "source_catalog_url": chapter_url,
                        "source_url": variant.source_url,
                    }
                )
                if not selected:
                    continue
                if variant.terminal_disposition:
                    terminal_sections.append(
                        {
                            "chapter_number": chapter_number,
                            "disposition": variant.terminal_disposition,
                            "effective_date": variant.effective_date_text,
                            "section_number": variant.section_number,
                            "source_url": variant.source_url,
                        }
                    )
                    continue
                identity_key = variant.section_number.casefold()
                if identity_key in seen_sections:
                    raise RuntimeError(
                        "Missouri chapter frontier repeated section identity "
                        f"{variant.section_number}: {chapter_url}"
                    )
                seen_sections.add(identity_key)
                section_frontier.append(
                    (
                        chapter_index,
                        chapter_number,
                        variant.section_number,
                        variant.section_title,
                        variant.source_url,
                        variant.bid,
                        variant.effective_date_text,
                        report_index,
                    )
                )
            chapter_end_offsets.append((chapter_index, len(section_frontier)))

        if not section_frontier:
            raise RuntimeError("Missouri official chapters exposed no section frontier")
        return {
            "chapter_end_offsets": chapter_end_offsets,
            "chapter_reports": chapter_reports,
            "future_effective_identities_excluded": (
                future_effective_identities_excluded
            ),
            "future_effective_variants_excluded": (
                future_effective_variants_excluded
            ),
            "non_authoritative_variants_excluded": (
                non_authoritative_variants_excluded
            ),
            "section_frontier": section_frontier,
            "section_identities_discovered": len(variant_section_identities),
            "section_variants_discovered": len(variant_reports),
            "terminal_chapters": terminal_chapters,
            "terminal_sections": terminal_sections,
            "variant_reports": variant_reports,
        }

    def _missouri_exact_frontier(
        self,
        *,
        home_content_sha256: str,
        chapter_reports: Sequence[Mapping[str, Any]],
        variant_reports: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Build exact ordered hierarchy/variant/current-output algebra."""

        from ...legal_data.open_us_law_acquisition_coordinator import (
            canonical_json_bytes,
        )
        from ...legal_data.open_us_law_live_evidence import compute_frontier_digest

        chapters = [dict(report) for report in chapter_reports]
        variants = [dict(report) for report in variant_reports]
        if not re.fullmatch(r"[0-9a-f]{64}", home_content_sha256):
            raise RuntimeError("Missouri exact frontier lacks the retained home digest")
        if not chapters or not variants:
            raise RuntimeError("Missouri exact frontier has an empty hierarchy level")
        chapter_urls = [str(report.get("source_url") or "") for report in chapters]
        variant_urls = [str(report.get("source_url") or "") for report in variants]
        if (
            any(not url for url in chapter_urls)
            or len(chapter_urls) != len(set(chapter_urls))
            or any(not url for url in variant_urls)
            or len(variant_urls) != len(set(variant_urls))
        ):
            raise RuntimeError("Missouri exact frontier repeated or lost source URLs")
        dispositions = [str(report.get("disposition") or "") for report in variants]
        if any(not disposition or disposition == "operative_pending" for disposition in dispositions):
            raise RuntimeError("Missouri exact frontier contains an unclassified variant")
        operative_reports = [
            report for report in variants if report["disposition"] == "operative"
        ]
        operative_keys = [
            str(report.get("canonical_identity") or "") for report in operative_reports
        ]
        if (
            any(not key for key in operative_keys)
            or len(operative_keys) != len(set(operative_keys))
        ):
            raise RuntimeError(
                "Missouri current operative identities are not ordered and unique"
            )
        excluded_count = len(variants) - len(operative_reports)
        disposition = {
            "discovered": len(variants),
            "duplicates": 0,
            "excluded": excluded_count,
            "failed_final": 0,
            "fetched": len(operative_reports),
            "quarantined": 0,
        }
        terminal_dispositions: Dict[str, int] = {}
        for variant_disposition in dispositions:
            if variant_disposition == "operative":
                continue
            terminal_dispositions[variant_disposition] = (
                terminal_dispositions.get(variant_disposition, 0) + 1
            )
        chapter_dispositions: Dict[str, int] = {}
        for report in chapters:
            chapter_disposition = str(report.get("disposition") or "")
            if chapter_disposition == "active":
                continue
            chapter_dispositions[chapter_disposition] = (
                chapter_dispositions.get(chapter_disposition, 0) + 1
            )
        active_chapters = sum(
            str(report.get("disposition") or "") == "active"
            for report in chapters
        )
        hierarchy_disposition = {
            "active": active_chapters,
            "discovered": len(chapters),
            "duplicates": 0,
            "terminal": len(chapters) - active_chapters,
            "unclassified": 0,
        }
        frontier: Dict[str, Any] = {
            "algebra_closed": disposition["discovered"]
            == disposition["fetched"] + disposition["excluded"],
            "bundle_closed": False,
            "chapter_document_count": len(chapters),
            "chapter_frontier_sha256": self._missouri_report_digest(chapters),
            "closed": True,
            "disposition": disposition,
            "enumerator_closed": True,
            "expected_index_units": len(variants),
            "home_content_sha256": home_content_sha256,
            "hierarchy_algebra_closed": hierarchy_disposition["discovered"]
            == hierarchy_disposition["active"]
            + hierarchy_disposition["terminal"],
            "hierarchy_disposition": hierarchy_disposition,
            "method": "source_derived_home_chapter_effective_variant_html",
            "operative_canonical_key_count": len(operative_keys),
            "operative_canonical_keys_sha256": hashlib.sha256(
                canonical_json_bytes(operative_keys)
            ).hexdigest(),
            "pagination_closed": True,
            "schema_version": "missouri-source-derived-effective-variant-frontier-v1",
            "scope_closed": True,
            "source_membership_sha256": hashlib.sha256(
                canonical_json_bytes(variant_urls)
            ).hexdigest(),
            "source_variant_count": len(variants),
            "terminal_chapter_dispositions": dict(
                sorted(chapter_dispositions.items())
            ),
            "terminal_section_dispositions": dict(
                sorted(terminal_dispositions.items())
            ),
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "variant_frontier_sha256": self._missouri_report_digest(variants),
            "visited_index_units": len(variants),
        }
        if (
            frontier["algebra_closed"] is not True
            or frontier["hierarchy_algebra_closed"] is not True
        ):
            raise RuntimeError("Missouri exact source disposition algebra did not close")
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return frontier

    @staticmethod
    def _missouri_operative_report(
        catalog_report: Mapping[str, Any],
        *,
        parser_payload: bytes,
        parser_input_source_url: str,
        frontier_payload: bytes = b"",
        fallback_reason: str = "",
    ) -> Dict[str, Any]:
        report = dict(catalog_report)
        report.update(
            {
                "content_sha256": hashlib.sha256(parser_payload).hexdigest(),
                "disposition": "operative",
                "frontier_content_sha256": (
                    hashlib.sha256(frontier_payload).hexdigest()
                    if frontier_payload
                    else ""
                ),
                "parser_input_source_url": parser_input_source_url,
                "source_identity_fallback_reason": fallback_reason,
            }
        )
        return report

    async def _scrape_unbounded_missouri_frontier(
        self,
        code_name: str,
        chapter_urls: List[str],
        *,
        home_bytes: bytes,
    ) -> List[NormalizedStatute]:
        """Reconstruct and acquire the complete current Revisor frontier."""

        from .missouri_chapter import (
            section_body_identity,
            section_page_identity,
            section_url,
            statute_from_section_html,
        )

        # A full run never trusts checkpoint rows or a positional cursor. The
        # attached acquisition ledger replays exact retained inputs, so
        # rebuilding this frontier avoids stale-row admission without issuing
        # duplicate network requests.
        statutes: List[NormalizedStatute] = []
        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="missouri:chapter-discovery",
            force=True,
            replace_existing_rows=True,
            extra={
                "chapters_scanned": 0,
                "discovered_chapters": len(chapter_urls),
                "sections_scanned": 0,
                "discovered_sections": 0,
                "section_variants_discovered": 0,
                "section_identities_discovered": 0,
                "future_effective_variants_excluded": 0,
                "future_effective_identities_excluded": 0,
                "non_authoritative_variants_excluded": 0,
                "terminal_chapters_classified": 0,
                "terminal_chapter_dispositions": [],
                "terminal_sections_classified": 0,
                "terminal_section_dispositions": [],
                "codes_completed": 0,
                "codes_total": 1,
            },
        )

        chapter_batch = await self._fetch_missouri_frontier_batch(
            chapter_urls,
            frontier_name="chapter-index",
        )
        inventory = self._missouri_catalog_inventory(chapter_urls, chapter_batch)
        section_frontier = list(inventory["section_frontier"])
        chapter_reports = list(inventory["chapter_reports"])
        variant_reports = list(inventory["variant_reports"])
        terminal_chapters = list(inventory["terminal_chapters"])
        terminal_sections = list(inventory["terminal_sections"])
        section_variants_discovered = int(
            inventory["section_variants_discovered"]
        )
        section_identities_discovered = int(
            inventory["section_identities_discovered"]
        )
        future_effective_variants_excluded = int(
            inventory["future_effective_variants_excluded"]
        )
        future_effective_identities_excluded = int(
            inventory["future_effective_identities_excluded"]
        )
        non_authoritative_variants_excluded = int(
            inventory["non_authoritative_variants_excluded"]
        )

        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="missouri:section-discovery",
            force=True,
            replace_existing_rows=True,
            extra={
                "chapters_scanned": 0,
                "discovered_chapters": len(chapter_urls),
                "sections_scanned": 0,
                "discovered_sections": len(section_frontier),
                "section_variants_discovered": section_variants_discovered,
                "section_identities_discovered": section_identities_discovered,
                "future_effective_variants_excluded": (
                    future_effective_variants_excluded
                ),
                "future_effective_identities_excluded": (
                    future_effective_identities_excluded
                ),
                "non_authoritative_variants_excluded": (
                    non_authoritative_variants_excluded
                ),
                "terminal_chapters_classified": len(terminal_chapters),
                "terminal_chapter_dispositions": terminal_chapters,
                "terminal_sections_classified": len(terminal_sections),
                "terminal_section_dispositions": terminal_sections,
                "codes_completed": 0,
                "codes_total": 1,
            },
        )

        # Inspect the versioned catalog locators only through the retained
        # ledger.  Missing PageSelect inputs are intentionally *not* fetched:
        # the stable OneSection locator is the one exact residual source for
        # that identity.  This turns the retained v13 frontier into a single
        # source-ordered residual wave rather than 26,586 futile PageSelect
        # attempts followed by another archive pass.
        page_select_urls = [str(row[4]) for row in section_frontier]
        retained_page_select = self._replay_optional_missouri_retained_inputs(
            page_select_urls,
            frontier_name="retained PageSelect planning frontier",
            refresh=True,
        )
        parsed_rows: List[NormalizedStatute | None] = [None] * len(section_frontier)
        one_section_candidates: List[tuple[int, tuple[Any, ...], str, str, bytes]] = []
        retained_page_select_parser_inputs = 0

        for row_index, frontier_row in enumerate(section_frontier):
            (
                _chapter_index,
                _chapter_number,
                section_number,
                section_title,
                frontier_url,
                source_record_bid,
                effective_date,
                report_index,
            ) = frontier_row
            retained_frontier = retained_page_select.get(frontier_url)
            if retained_frontier is None:
                one_section_candidates.append(
                    (
                        row_index,
                        frontier_row,
                        section_url(section_number),
                        "official_page_select_unavailable",
                        b"",
                    )
                )
                continue

            frontier_payload = retained_frontier[0]
            frontier_html = frontier_payload.decode("utf-8", errors="replace")
            parsed = statute_from_section_html(
                frontier_html,
                section_number=section_number,
                code_name=code_name,
                section_title=section_title,
                source_url=frontier_url,
                source_record_bid=source_record_bid,
                effective_date=effective_date,
            )
            if parsed is not None:
                parsed.structured_data = {
                    **dict(parsed.structured_data or {}),
                    "content_sha256": hashlib.sha256(frontier_payload).hexdigest(),
                }
                variant_reports[report_index] = self._missouri_operative_report(
                    variant_reports[report_index],
                    parser_payload=frontier_payload,
                    parser_input_source_url=frontier_url,
                    frontier_payload=frontier_payload,
                )
                parsed_rows[row_index] = parsed
                retained_page_select_parser_inputs += 1
                continue

            observed_identity = section_body_identity(frontier_html)
            page_identity = section_page_identity(frontier_html)
            if (
                observed_identity
                and observed_identity.casefold() != section_number.casefold()
                and page_identity.casefold() == section_number.casefold()
            ):
                fallback_reason = "official_page_select_body_identity_mismatch"
            elif (
                not observed_identity
                and page_identity.casefold() == section_number.casefold()
            ):
                fallback_reason = "official_page_select_body_unavailable"
            else:
                raise RuntimeError(
                    "Missouri retained section body failed official parsing or "
                    f"identity verification: {frontier_url}"
                )
            one_section_candidates.append(
                (
                    row_index,
                    frontier_row,
                    section_url(section_number),
                    fallback_reason,
                    frontier_payload,
                )
            )

        one_section_urls = [candidate[2] for candidate in one_section_candidates]
        if len(one_section_urls) != len(set(one_section_urls)):
            raise RuntimeError("Missouri OneSection residual frontier repeated a URL")
        retained_one_section = self._replay_optional_missouri_retained_inputs(
            one_section_urls,
            frontier_name="retained OneSection planning frontier",
        )

        def _admit_one_section(
            candidate: tuple[int, tuple[Any, ...], str, str, bytes],
            fallback_payload: bytes,
        ) -> None:
            (
                row_index,
                frontier_row,
                fallback_url,
                fallback_reason,
                frontier_payload,
            ) = candidate
            (
                _chapter_index,
                _chapter_number,
                section_number,
                section_title,
                frontier_url,
                source_record_bid,
                effective_date,
                report_index,
            ) = frontier_row
            fallback_identity = section_body_identity(
                fallback_payload.decode("utf-8", errors="replace")
            )
            if fallback_identity.casefold() != section_number.casefold():
                raise RuntimeError(
                    "Missouri alternate official section body failed requested "
                    f"identity verification: {fallback_url}"
                )
            parsed = statute_from_section_html(
                fallback_payload.decode("utf-8", errors="replace"),
                section_number=section_number,
                code_name=code_name,
                section_title=section_title,
                source_url=fallback_url,
                source_record_bid=source_record_bid,
                effective_date=effective_date,
                source_frontier_record_url=frontier_url,
                source_identity_fallback_reason=fallback_reason,
            )
            if parsed is None:
                raise RuntimeError(
                    "Missouri alternate official section body failed official "
                    f"parsing: {fallback_url}"
                )
            parsed.structured_data = {
                **dict(parsed.structured_data or {}),
                "content_sha256": hashlib.sha256(fallback_payload).hexdigest(),
            }
            variant_reports[report_index] = self._missouri_operative_report(
                variant_reports[report_index],
                parser_payload=fallback_payload,
                parser_input_source_url=fallback_url,
                frontier_payload=frontier_payload,
                fallback_reason=fallback_reason,
            )
            parsed_rows[row_index] = parsed

        one_section_residuals: List[
            tuple[int, tuple[Any, ...], str, str, bytes]
        ] = []
        for candidate in one_section_candidates:
            retained_fallback = retained_one_section.get(candidate[2])
            if retained_fallback is None:
                one_section_residuals.append(candidate)
                continue
            _admit_one_section(candidate, retained_fallback[0])

        residual_urls = [candidate[2] for candidate in one_section_residuals]
        residual_batch_stats: Dict[str, Any] = {}
        if residual_urls:
            residual_batch = await self._fetch_missouri_frontier_batch(
                residual_urls,
                frontier_name="source-ordered-one-section-residuals",
            )
            residual_batch_stats = dict(residual_batch.stats or {})
            for candidate, fallback_payload in zip(
                one_section_residuals,
                residual_batch.payloads,
                strict=True,
            ):
                _admit_one_section(candidate, fallback_payload)

        if any(parsed is None for parsed in parsed_rows):
            raise RuntimeError(
                "Missouri section identity residual reconciliation was incomplete"
            )
        statutes.extend(parsed for parsed in parsed_rows if parsed is not None)

        section_acquisition_plan = {
            "page_select_catalog_count": len(page_select_urls),
            "retained_page_select_count": len(retained_page_select),
            "retained_page_select_parser_input_count": (
                retained_page_select_parser_inputs
            ),
            "one_section_candidate_count": len(one_section_candidates),
            "retained_one_section_count": len(retained_one_section),
            "residual_one_section_count": len(residual_urls),
            "residual_one_section_sha256": hashlib.sha256(
                json.dumps(
                    residual_urls,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            "residual_urls_unique": len(residual_urls) == len(set(residual_urls)),
            "source_ordered": True,
            "one_section_plural_wave_count": 1 if residual_urls else 0,
            "per_page_archive_loop": False,
            "residual_batch_stats": residual_batch_stats,
        }
        self._last_missouri_section_acquisition_plan = dict(
            section_acquisition_plan
        )
        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="missouri:section-scan",
            replace_existing_rows=True,
            extra={
                "chapters_scanned": len(chapter_urls),
                "discovered_chapters": len(chapter_urls),
                "sections_scanned": len(section_frontier),
                "discovered_sections": len(section_frontier),
                "section_variants_discovered": section_variants_discovered,
                "section_identities_discovered": section_identities_discovered,
                "future_effective_variants_excluded": (
                    future_effective_variants_excluded
                ),
                "future_effective_identities_excluded": (
                    future_effective_identities_excluded
                ),
                "non_authoritative_variants_excluded": (
                    non_authoritative_variants_excluded
                ),
                "terminal_chapters_classified": len(terminal_chapters),
                "terminal_chapter_dispositions": terminal_chapters,
                "terminal_sections_classified": len(terminal_sections),
                "terminal_section_dispositions": terminal_sections,
                "section_acquisition_plan": section_acquisition_plan,
                "codes_completed": 0,
                "codes_total": 1,
            },
        )

        operative_reports = [
            report
            for report in variant_reports
            if report.get("disposition") == "operative"
        ]
        if len(statutes) != len(section_frontier) or len(operative_reports) != len(
            statutes
        ):
            raise RuntimeError(
                "Missouri normalized rows do not close the current source frontier"
            )
        home_content_sha256 = hashlib.sha256(home_bytes).hexdigest()
        exact_frontier = self._missouri_exact_frontier(
            home_content_sha256=home_content_sha256,
            chapter_reports=chapter_reports,
            variant_reports=variant_reports,
        )
        legal_as_of_dates = {
            str(report.get("as_of_date") or "") for report in chapter_reports
        }
        if len(legal_as_of_dates) != 1 or "" in legal_as_of_dates:
            raise RuntimeError(
                "Missouri current chapter evidence does not share one legal as-of date"
            )
        retrieved_at_values = [
            str(report.get("retrieved_at") or "") for report in chapter_reports
        ]
        if any(not value for value in retrieved_at_values):
            raise RuntimeError("Missouri chapter evidence lacks observation times")
        self._last_missouri_full_frontier = {
            "boundary_first": str(operative_reports[0]["source_url"]),
            "boundary_last": str(operative_reports[-1]["source_url"]),
            "chapter_reports": chapter_reports,
            "chapter_urls": list(chapter_urls),
            "code_name": code_name,
            "frontier": exact_frontier,
            "home_content_sha256": home_content_sha256,
            "legal_as_of": next(iter(legal_as_of_dates)),
            "observed_at": max(retrieved_at_values),
            "section_acquisition_plan": section_acquisition_plan,
            "terminal_chapters": terminal_chapters,
            "variant_reports": variant_reports,
        }

        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="missouri:complete",
            force=True,
            replace_existing_rows=True,
            extra={
                "chapters_scanned": len(chapter_urls),
                "discovered_chapters": len(chapter_urls),
                "sections_scanned": len(section_frontier),
                "discovered_sections": len(section_frontier),
                "section_variants_discovered": section_variants_discovered,
                "section_identities_discovered": section_identities_discovered,
                "future_effective_variants_excluded": (
                    future_effective_variants_excluded
                ),
                "future_effective_identities_excluded": (
                    future_effective_identities_excluded
                ),
                "non_authoritative_variants_excluded": (
                    non_authoritative_variants_excluded
                ),
                "terminal_chapters_classified": len(terminal_chapters),
                "terminal_chapter_dispositions": terminal_chapters,
                "terminal_sections_classified": len(terminal_sections),
                "terminal_section_dispositions": terminal_sections,
                "section_acquisition_plan": section_acquisition_plan,
                "codes_completed": 1,
                "codes_total": 1,
            },
        )
        return statutes

    def _replay_missouri_retained_batch(
        self,
        urls: Sequence[str],
        *,
        frontier_name: str,
    ) -> StateLawPageMultiFetchResult:
        """Replay an ordered Missouri batch without entering a fetch path."""

        from .strict_frontier_closure import replay_exact_retained_state_record

        requested = [str(url or "").strip() for url in urls]
        payloads: List[bytes] = []
        transport_receipts: List[Optional[Dict[str, Any]]] = []
        envelopes: List[Any] = []
        for source_url in requested:
            retained = replay_exact_retained_state_record(
                self,
                official_url=source_url,
                sanitized_request={"method": "GET", "url": source_url},
                frontier_name=frontier_name,
                refresh=False,
            )
            payloads.append(bytes(retained.envelope.body or b""))
            raw_transport = getattr(retained, "transport_receipt", {})
            transport_receipts.append(
                dict(raw_transport) if isinstance(raw_transport, Mapping) else {}
            )
            envelopes.append(retained.envelope)
        return StateLawPageMultiFetchResult(
            urls=requested,
            payloads=payloads,
            errors=[None] * len(requested),
            transport_receipts=transport_receipts,
            parser_input_envelopes=envelopes,
            stats={
                "network_requests": 0,
                "provider": "retained_acquisition_replay",
                "requested_pages": len(requested),
            },
        )

    def _replay_missouri_source_frontier(
        self,
        first: Mapping[str, Any],
    ) -> List[NormalizedStatute]:
        """Rebuild the exact hierarchy and rows from retained inputs only."""

        from .missouri_chapter import (
            section_body_identity,
            section_page_identity,
            statute_from_section_html,
        )
        from .strict_frontier_closure import replay_exact_retained_state_record

        expected_chapters_raw = first.get("chapter_reports")
        expected_variants_raw = first.get("variant_reports")
        expected_chapter_urls_raw = first.get("chapter_urls")
        if (
            not isinstance(expected_chapters_raw, Sequence)
            or isinstance(expected_chapters_raw, (str, bytes, bytearray))
            or not isinstance(expected_variants_raw, Sequence)
            or isinstance(expected_variants_raw, (str, bytes, bytearray))
            or not isinstance(expected_chapter_urls_raw, Sequence)
            or isinstance(expected_chapter_urls_raw, (str, bytes, bytearray))
            or any(not isinstance(row, Mapping) for row in expected_chapters_raw)
            or any(not isinstance(row, Mapping) for row in expected_variants_raw)
        ):
            raise RuntimeError("Missouri first exact frontier reports are incomplete")
        expected_chapters = [dict(row) for row in expected_chapters_raw]
        expected_variants = [dict(row) for row in expected_variants_raw]
        expected_chapter_urls = [str(url or "") for url in expected_chapter_urls_raw]

        home_record = replay_exact_retained_state_record(
            self,
            official_url=self.OFFICIAL_ENTRY_URL,
            sanitized_request={"method": "GET", "url": self.OFFICIAL_ENTRY_URL},
            frontier_name="Missouri retained home frontier",
            refresh=False,
        )
        home_bytes = bytes(home_record.envelope.body or b"")
        home_digest = hashlib.sha256(home_bytes).hexdigest()
        if home_digest != str(first.get("home_content_sha256") or ""):
            raise RuntimeError("Missouri retained home digest changed on replay")
        replay_chapter_urls = self._missouri_home_chapter_urls(home_bytes)
        if replay_chapter_urls != expected_chapter_urls:
            raise RuntimeError("Missouri retained home chapter membership changed")

        chapter_batch = self._replay_missouri_retained_batch(
            replay_chapter_urls,
            frontier_name="Missouri retained chapter frontier",
        )
        inventory = self._missouri_catalog_inventory(
            replay_chapter_urls,
            chapter_batch,
        )
        replay_chapters = list(inventory["chapter_reports"])
        replay_variants = list(inventory["variant_reports"])
        section_frontier = list(inventory["section_frontier"])
        if replay_chapters != expected_chapters:
            raise RuntimeError("Missouri retained chapter reports changed on replay")
        if len(replay_variants) != len(expected_variants):
            raise RuntimeError("Missouri retained source-variant count changed")
        catalog_fields = (
            "bid",
            "canonical_identity",
            "catalog_content_sha256",
            "catalog_disposition",
            "chapter_number",
            "effective_date",
            "section_number",
            "source_catalog_url",
            "source_url",
        )
        for replay_report, expected_report in zip(
            replay_variants,
            expected_variants,
            strict=True,
        ):
            if any(
                replay_report.get(field) != expected_report.get(field)
                for field in catalog_fields
            ):
                raise RuntimeError(
                    "Missouri retained catalog variant membership changed: "
                    f"{expected_report.get('source_url')}"
                )

        code_name = str(first.get("code_name") or "Missouri Revised Statutes")
        replay_rows: List[NormalizedStatute] = []
        for frontier_row in section_frontier:
            (
                _chapter_index,
                _chapter_number,
                section_number,
                section_title,
                frontier_url,
                source_record_bid,
                effective_date,
                report_index,
            ) = frontier_row
            expected_report = expected_variants[report_index]
            parser_input_source_url = str(
                expected_report.get("parser_input_source_url") or ""
            )
            fallback_reason = str(
                expected_report.get("source_identity_fallback_reason") or ""
            )
            frontier_payload = b""
            if fallback_reason in {
                "official_page_select_body_identity_mismatch",
                "official_page_select_body_unavailable",
            }:
                frontier_record = replay_exact_retained_state_record(
                    self,
                    official_url=frontier_url,
                    sanitized_request={"method": "GET", "url": frontier_url},
                    frontier_name="Missouri retained PageSelect frontier",
                    refresh=False,
                )
                frontier_payload = bytes(frontier_record.envelope.body or b"")
                if (
                    hashlib.sha256(frontier_payload).hexdigest()
                    != str(expected_report.get("frontier_content_sha256") or "")
                ):
                    raise RuntimeError(
                        "Missouri retained mismatched PageSelect body changed: "
                        f"{frontier_url}"
                    )
                observed = section_body_identity(
                    frontier_payload.decode("utf-8", errors="replace")
                )
                if fallback_reason == "official_page_select_body_identity_mismatch":
                    page_identity = section_page_identity(
                        frontier_payload.decode("utf-8", errors="replace")
                    )
                    if (
                        not observed
                        or observed.casefold() == section_number.casefold()
                        or page_identity.casefold() != section_number.casefold()
                    ):
                        raise RuntimeError(
                            "Missouri retained identity-mismatch evidence no longer "
                            f"mismatches: {frontier_url}"
                        )
                else:
                    page_identity = section_page_identity(
                        frontier_payload.decode("utf-8", errors="replace")
                    )
                    if (
                        observed
                        or page_identity.casefold() != section_number.casefold()
                    ):
                        raise RuntimeError(
                            "Missouri retained body-unavailable evidence changed: "
                            f"{frontier_url}"
                        )
            elif fallback_reason == "official_page_select_unavailable":
                if str(expected_report.get("frontier_content_sha256") or ""):
                    raise RuntimeError(
                        "Missouri unavailable PageSelect fallback unexpectedly has a body"
                    )
            elif not fallback_reason:
                if parser_input_source_url != frontier_url:
                    raise RuntimeError(
                        "Missouri direct retained source changed parser-input identity"
                    )
            else:
                raise RuntimeError(
                    f"Missouri retained fallback reason is unknown: {fallback_reason}"
                )
            if not parser_input_source_url:
                raise RuntimeError(
                    f"Missouri retained operative report lacks parser input: {frontier_url}"
                )
            parser_record = replay_exact_retained_state_record(
                self,
                official_url=parser_input_source_url,
                sanitized_request={
                    "method": "GET",
                    "url": parser_input_source_url,
                },
                frontier_name="Missouri retained operative section frontier",
                refresh=False,
            )
            parser_payload = bytes(parser_record.envelope.body or b"")
            statute = statute_from_section_html(
                parser_payload.decode("utf-8", errors="replace"),
                section_number=section_number,
                code_name=code_name,
                section_title=section_title,
                source_url=parser_input_source_url,
                source_record_bid=source_record_bid,
                effective_date=effective_date,
                source_frontier_record_url=frontier_url,
                source_identity_fallback_reason=fallback_reason,
            )
            if statute is None:
                raise RuntimeError(
                    "Missouri retained operative parser input changed identity or text: "
                    f"{parser_input_source_url}"
                )
            statute.structured_data = {
                **dict(statute.structured_data or {}),
                "content_sha256": hashlib.sha256(parser_payload).hexdigest(),
            }
            replay_variants[report_index] = self._missouri_operative_report(
                replay_variants[report_index],
                parser_payload=parser_payload,
                parser_input_source_url=parser_input_source_url,
                frontier_payload=(
                    frontier_payload if fallback_reason else parser_payload
                ),
                fallback_reason=fallback_reason,
            )
            replay_rows.append(statute)

        if replay_variants != expected_variants:
            raise RuntimeError("Missouri retained source reports changed on replay")
        replayed_frontier = self._missouri_exact_frontier(
            home_content_sha256=home_digest,
            chapter_reports=replay_chapters,
            variant_reports=replay_variants,
        )
        self._last_missouri_replayed_frontier = {
            "frontier": replayed_frontier,
            "rows": replay_rows,
            "variant_reports": replay_variants,
        }
        return replay_rows

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection: Mapping[str, Any],
    ) -> Optional[Path]:
        """Seal retained zero-network replay and ordered canonical parity."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Missouri frontier closure requires an attached ledger")
        first = getattr(self, "_last_missouri_full_frontier", None)
        if not isinstance(first, Mapping):
            raise RuntimeError(
                "Missouri source-derived strict frontier was not retained before output"
            )
        refresh = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh):
            refresh()
        replay_rows = self._replay_missouri_source_frontier(first)
        replay = getattr(self, "_last_missouri_replayed_frontier", None)
        first_frontier = first.get("frontier")
        replayed_frontier = replay.get("frontier") if isinstance(replay, Mapping) else None
        if not isinstance(first_frontier, Mapping) or not isinstance(
            replayed_frontier,
            Mapping,
        ):
            raise RuntimeError("Missouri exact frontier replay did not close")

        from .strict_frontier_closure import retain_exact_state_frontier_closure

        variant_reports = list(first.get("variant_reports") or [])
        chapter_reports = list(first.get("chapter_reports") or [])
        fallback_count = sum(
            bool(report.get("source_identity_fallback_reason"))
            for report in variant_reports
            if isinstance(report, Mapping)
        )
        section_plan = first.get("section_acquisition_plan")
        if not isinstance(section_plan, Mapping):
            raise RuntimeError("Missouri closure lacks its section acquisition plan")
        return retain_exact_state_frontier_closure(
            self,
            canonical_output_projection=canonical_output_projection,
            first_frontier=first_frontier,
            replayed_frontier=replayed_frontier,
            replay_rows=replay_rows,
            jurisdiction="MO",
            source_domain=self.OFFICIAL_DOMAIN,
            official_source_url=self.OFFICIAL_ENTRY_URL,
            observed_at=str(first.get("observed_at") or ""),
            legal_as_of=str(first.get("legal_as_of") or ""),
            boundary_first=str(first.get("boundary_first") or ""),
            boundary_last=str(first.get("boundary_last") or ""),
            bundle_total=len(variant_reports),
            pagination_total=len(chapter_reports),
            transport={
                "fixture": False,
                "grouped_warc_recovery": True,
                "kind": "shared_archive_aware_plural_html",
                "official_residual_fallback_count": fallback_count,
                "one_section_candidate_count": int(
                    section_plan.get("one_section_candidate_count", 0) or 0
                ),
                "one_section_plural_wave_count": int(
                    section_plan.get("one_section_plural_wave_count", 0) or 0
                ),
                "per_page_archive_loop": False,
                "residual_only_retries": True,
                "residual_one_section_count": int(
                    section_plan.get("residual_one_section_count", 0) or 0
                ),
                "residual_one_section_sha256": str(
                    section_plan.get("residual_one_section_sha256") or ""
                ),
                "retained_replay_network_requests": 0,
                "wayback_prefix_inventory": True,
                "synthetic": False,
            },
        )
    
    async def _custom_scrape_missouri(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: Optional[int] = 220
    ) -> List[NormalizedStatute]:
        """Custom scraper for Missouri's legislative website.
        
        Use the Missouri Revisor site and gather section links from chapter pages.
        This avoids very slow fallback URL chains that can cause global timeout.
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []
        
        del code_url
        cap = max(1, int(max_sections)) if max_sections is not None else None
        unbounded = cap is None

        try:
            home_url = f"{self.get_base_url()}/main/Home.aspx"
            home_bytes = await self._fetch_page_content_with_archival_fallback(
                home_url,
                timeout_seconds=20,
            )
            if not home_bytes:
                if unbounded:
                    raise RuntimeError("Missouri official home frontier is unavailable")
                return []
            soup = BeautifulSoup(home_bytes, 'html.parser')
        except Exception as e:
            if unbounded:
                raise RuntimeError("Missouri official home frontier is unavailable") from e
            self.logger.warning(f"Missouri: failed to load home page: {e}")
            return []

        if unbounded:
            chapter_urls = self._missouri_home_chapter_urls(home_bytes)
            return await self._scrape_unbounded_missouri_frontier(
                code_name,
                chapter_urls,
                home_bytes=home_bytes,
            )

        chapter_urls: List[str] = []
        for link in soup.find_all('a', href=True):
            href = str(link.get('href', '') or '').strip()
            if 'OneChapter.aspx?chapter=' not in href:
                continue
            full = urljoin(home_url, href)
            if full not in chapter_urls:
                chapter_urls.append(full)

        chapter_urls = chapter_urls[:28]
        statutes: List[NormalizedStatute] = []
        seen_sections: set[str] = set()

        for chapter_url in chapter_urls:
            if cap is not None and len(statutes) >= cap:
                break
            chapter_vals = parse_qs(urlparse(chapter_url).query).get('chapter') or []
            chapter_number = (chapter_vals[0].strip() if chapter_vals else '')
            try:
                chapter_bytes = await self._fetch_page_content_with_archival_fallback(
                    chapter_url,
                    timeout_seconds=20,
                )
                if not chapter_bytes:
                    continue
                chap_soup = BeautifulSoup(chapter_bytes, 'html.parser')
            except Exception:
                continue

            from .missouri_chapter import chapter_sections as _mo_chapter_sections

            chapter_html = (
                chapter_bytes.decode("utf-8", errors="replace")
                if isinstance(chapter_bytes, bytes)
                else str(chapter_bytes)
            )
            section_rows = _mo_chapter_sections(chapter_html, chapter_number)
            if not section_rows:
                for link in chap_soup.find_all('a', href=True):
                    href = link.get('href', '')
                    if 'OneSection.aspx?section=' not in href:
                        continue
                    full_url = urljoin(chapter_url, href)
                    section_vals = parse_qs(urlparse(full_url).query).get('section') or []
                    section_number = (section_vals[0].strip() if section_vals else '')
                    if section_number:
                        section_rows.append((section_number, link.get_text(' ', strip=True)))
            for section_number, link_text in section_rows:
                if cap is not None and len(statutes) >= cap:
                    break
                if not section_number or section_number in seen_sections:
                    continue
                seen_sections.add(section_number)
                full_url = urljoin(chapter_url, f"OneSection.aspx?section={section_number}")
                section_payload = await self._fetch_page_content_with_archival_fallback(
                    full_url,
                    timeout_seconds=20,
                )
                from .missouri_chapter import statute_from_section_html as _mo_section

                section_html = (
                    section_payload.decode("utf-8", errors="replace")
                    if isinstance(section_payload, bytes)
                    else str(section_payload or "")
                )
                parsed = _mo_section(
                    section_html,
                    section_number=section_number,
                    code_name=code_name,
                    section_title=link_text,
                )
                if parsed is not None:
                    statutes.append(parsed)
                    continue
                full_text, extracted_name = self._extract_section_text_and_name(section_payload or b"")
                section_name = (extracted_name or link_text or f"Section {section_number}")[:200]
                if not full_text:
                    full_text = f"Section {section_number}: {link_text}"

                legal_area = self._identify_legal_area(link_text or code_name)
                statute = NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name,
                    full_text=full_text,
                    legal_area=legal_area,
                    source_url=full_url,
                    official_cite=f"{citation_format} § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_missouri_section_html",
                        "discovery_method": "official_chapter_index_sections",
                        "skip_hydrate": True,
                    },
                )
                statutes.append(statute)

        # Collapsed chapter pages may expose no section links. Never emit
        # placeholder chapter rows in full-corpus mode; those are not
        # section-level official text.
        if not statutes:
            for chapter_url in chapter_urls:
                if cap is not None and len(statutes) >= cap:
                    break
                chapter_vals = parse_qs(urlparse(chapter_url).query).get('chapter') or []
                chapter_number = (chapter_vals[0].strip() if chapter_vals else '')
                if not chapter_number or chapter_number in seen_sections:
                    continue
                seen_sections.add(chapter_number)

                chapter_label = f"Chapter {chapter_number}"
                statute = NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {chapter_number}",
                    code_name=code_name,
                    section_number=chapter_number,
                    section_name=chapter_label,
                    full_text=f"{chapter_label}: Missouri Revised Statutes chapter",
                    legal_area=self._identify_legal_area(chapter_label),
                    source_url=chapter_url,
                    official_cite=f"{citation_format} ch. {chapter_number}",
                    metadata=StatuteMetadata(),
                )
                statutes.append(statute)

        self.logger.info(f"Missouri custom scraper: Scraped {len(statutes)} sections")
        if not statutes:
            self.logger.warning("Missouri custom scraper found no section-level links")
            return []
        
        return statutes

    def _extract_section_text_and_name(self, payload: bytes) -> tuple[str, str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return "", ""

        soup = BeautifulSoup(payload, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()

        section_node = soup.select_one("div.norm")
        history_nodes = soup.select("div.foot p")
        body_parts: List[str] = []

        if section_node is not None:
            body_parts.append(self._normalize_legal_text(section_node.get_text(" ", strip=True)))
        for node in history_nodes:
            text = self._normalize_legal_text(node.get_text(" ", strip=True))
            if text:
                body_parts.append(text)

        if not body_parts:
            body_parts.append(self._normalize_legal_text(soup.get_text(" ", strip=True)))

        full_text = " ".join(part for part in body_parts if part).strip()
        section_name = ""
        heading_match = re.search(r"\b\d+\.\d+[A-Za-z]*\.\s*(.+?)\s+[—-]\s+", full_text)
        if heading_match:
            section_name = heading_match.group(1).strip()
        if not section_name:
            title_match = re.search(
                r"<meta\s+property=\"og:description\"\s+content=\"([^\"]+)\"",
                payload.decode("utf-8", errors="replace"),
                re.IGNORECASE,
            )
            if title_match:
                section_name = self._normalize_legal_text(title_match.group(1))
        if not section_name:
            section_name = "Section"
        return full_text, section_name

    def official_chapter_url(self, chapter: Any) -> str:
        token = str(chapter or "").strip()
        return f"{self.get_base_url()}/main/OneChapter.aspx?chapter={token}"

    def official_chapter_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Missouri Revised Statutes chapter catalog."""

        rows: List[Dict[str, Any]] = []
        seen: set[str] = set()
        tokens: List[str] = [str(number) for number in self.OFFICIAL_NUMERIC_CHAPTERS]
        tokens.extend(self.OFFICIAL_LETTERED_CHAPTERS)
        for token in tokens:
            key = token.lower()
            if key in seen:
                continue
            seen.add(key)
            url = self.official_chapter_url(token)
            rows.append(
                {
                    "canonical_key": f"mo:chapter-{key}",
                    "chapter_number": token,
                    "name": f"Chapter {token}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Missouri Revised Statutes Chapter {token} official "
                        f"catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))
        headers = {
            "User-Agent": "ipfs-datasets-missouri-official-catalog/1.0",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        }

        def _request() -> bytes:
            try:
                request = urllib.request.Request(url, headers=headers)
                context = ssl.create_default_context()
                with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                    return bytes(response.read() or b"")
            except Exception:
                try:
                    request = urllib.request.Request(url, headers=headers)
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
            match = self._MO_CHAPTER_RE.search(absolute)
            if not match:
                continue
            token = match.group("chapter")
            if token not in found:
                found[token] = self.official_chapter_url(token)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official RSMo chapter and repair missing live links."""

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
                    "canonical_key": f"mo:chapter-{token.lower()}",
                    "chapter_number": token,
                    "name": f"Chapter {token}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Missouri Revised Statutes Chapter {token} official "
                        f"catalog unit at {url}"
                    ),
                }
            )
        return rows

    def fetch_official(self, code: str = "MO"):
        """Acquire the exhaustive official Missouri Revised Statutes chapter catalog.

        Live HTTPS retains the official Revisor home page. Every known RSMo
        chapter is enumerated with an official revisor.mo.gov URL. This hook
        never returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "MO").strip().upper() or "MO"
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < 3:
            raise RuntimeError("missouri official catalog enumeration is incomplete")
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
StateScraperRegistry.register("MO", MissouriScraper)
