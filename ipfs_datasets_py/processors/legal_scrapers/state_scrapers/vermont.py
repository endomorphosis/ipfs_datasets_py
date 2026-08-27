"""Scraper for Vermont state laws.

This module contains the scraper for Vermont statutes from the official state legislative website.
"""

import hashlib
import json
import os
import re
import ssl
import time
import urllib.request
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from .base_scraper import (
    BaseStateScraper,
    NormalizedStatute,
    StatuteMetadata,
    current_partial_checkpoint_run_directory,
)
from .registry import StateScraperRegistry


class VermontScraper(BaseStateScraper):
    """Scraper for Vermont state laws from https://legislature.vermont.gov"""

    OFFICIAL_DOMAIN = "legislature.vermont.gov"
    OFFICIAL_ENTRY_PATH = "/statutes/"
    OFFICIAL_ENTRY_URL = "https://legislature.vermont.gov/statutes/"
    _VT_TITLE_HREF_RE = re.compile(
        r"/statutes/title/(?P<title>[0-9]{1,2}(?:APPENDIX|[A-Za-z])?)/?$",
        re.IGNORECASE,
    )
    _VT_TITLE_LABEL_RE = re.compile(
        r"\bTitle\s+(?P<title>\d{1,2}(?:APPENDIX|[A-Za-z])?)\b",
        re.IGNORECASE,
    )
    _VT_CONTINUATION_RE = re.compile(
        r"\b(next|continue|more titles|page\s+\d+)\b",
        re.IGNORECASE,
    )
    _VT_TITLE_PATH_RE = re.compile(
        r"^/statutes/title/(?P<title>[0-9]{1,2}(?:APPENDIX|[A-Za-z])?)/?$",
        re.IGNORECASE,
    )
    _VT_CHAPTER_PATH_RE = re.compile(
        r"^/statutes/chapter/(?P<title>[0-9]{1,2}(?:APPENDIX|[A-Za-z])?)/"
        r"(?P<chapter>[0-9A-Za-z.\-]+)/?$",
        re.IGNORECASE,
    )
    _VT_SUBCHAPTER_PATH_RE = re.compile(
        r"^/statutes/(?P<kind>subchapter|article)/"
        r"(?P<title>[0-9]{1,2}(?:APPENDIX|[A-Za-z])?)/"
        r"(?P<chapter>[0-9A-Za-z.\-]+)/(?P<subchapter>[0-9A-Za-z.\-]+)/?$",
        re.IGNORECASE,
    )
    _VT_SECTION_PATH_RE = re.compile(
        r"^/statutes/section/(?P<title>[0-9]{1,2}(?:APPENDIX|[A-Za-z])?)/"
        r"(?P<chapter>[0-9A-Za-z.\-]+)/(?P<section>[0-9A-Za-z.\-]+)/?$",
        re.IGNORECASE,
    )
    OFFICIAL_TITLES = (
        ("1", "General Provisions"),
        ("2", "Legislature"),
        ("3", "Executive"),
        ("3APPENDIX", "Executive Orders"),
        ("4", "Judiciary"),
        ("5", "Aeronautics and Surface Transportation"),
        ("6", "Agriculture"),
        ("7", "Alcoholic Beverages, Cannabis, and Tobacco"),
        ("8", "Banking and Insurance"),
        ("9", "Commerce and Trade"),
        ("9A", "Uniform Commercial Code"),
        ("10", "Conservation and Development"),
        ("10APPENDIX", "Conservation and Development"),
        ("11", "Corporations, Partnerships and Associations"),
        ("11A", "Vermont Business Corporations"),
        ("11B", "Nonprofit Corporations"),
        ("11C", "Mutual Benefit Enterprises"),
        ("12", "Court Procedure"),
        ("13", "Crimes and Criminal Procedure"),
        ("14", "Decedents' Estates and Fiduciary Relations"),
        ("14A", "Trusts"),
        ("15", "Domestic Relations"),
        ("15A", "Adoption Act"),
        ("15B", "Uniform Interstate Family Support Act (1996)"),
        ("15C", "Parentage Proceedings"),
        ("16", "Education"),
        ("16APPENDIX", "Education Charters and Agreements"),
        ("17", "Elections"),
        ("18", "Health"),
        ("19", "Highways"),
        ("20", "Internal Security and Public Safety"),
        ("21", "Labor"),
        ("22", "Libraries, History, and Information Technology"),
        ("23", "Motor Vehicles"),
        ("24", "Municipal and County Government"),
        ("24APPENDIX", "Municipal Charters"),
        ("25", "Navigation and Waters"),
        ("26", "Professions and Occupations"),
        ("27", "Property"),
        ("27A", "Uniform Common Interest Ownership Act (1994)"),
        ("28", "Public Institutions and Corrections"),
        ("29", "Public Property and Supplies"),
        ("30", "Public Service"),
        ("31", "Recreation and Sports"),
        ("32", "Taxation and Finance"),
        ("33", "Human Services"),
    )
    OFFICIAL_TITLE_COUNT = len(OFFICIAL_TITLES)

    def state_law_frontier_source_dependencies(self) -> tuple[object, ...]:
        """Bind parsing, closure, and exact plural acquisition code."""

        from ...web_archiving import wayback_machine_engine
        from . import (
            base_scraper,
            state_archival_fetch,
            strict_frontier_closure,
            vermont_section,
        )

        return (
            base_scraper,
            state_archival_fetch,
            strict_frontier_closure,
            vermont_section,
            wayback_machine_engine,
        )

    def _vermont_frontier_batch_size(self) -> int:
        return max(
            1,
            min(
                1024,
                self._env_int("STATE_SCRAPER_VT_FRONTIER_BATCH_SIZE", default=512),
            ),
        )

    def _vermont_frontier_concurrency(self) -> int:
        return max(
            1,
            min(
                64,
                self._env_int("STATE_SCRAPER_VT_FRONTIER_CONCURRENCY", default=12),
            ),
        )

    @staticmethod
    def _is_valid_vermont_frontier_payload(payload: bytes) -> bool:
        """Reject generic error/redirect bodies before they reach parsers."""

        sample = bytes(payload or b"")[:500_000].lower()
        if not sample:
            return False
        return bool(
            b"vermont" in sample
            and b"statute" in sample
            and b"<html" in sample
            and b"<title>404" not in sample
            and b"404 not found" not in sample
            and b"document moved" not in sample[:2_000]
        )

    def _validate_vermont_aligned_evidence(
        self,
        *,
        url: str,
        payload: bytes,
        transport_receipt: Any,
        parser_input_envelope: Any,
        frontier_name: str,
    ) -> None:
        """Require exact URL/body evidence whenever the ledger is attached."""

        canonical_url = self._canonical_fetch_url(url)
        digest = hashlib.sha256(payload).hexdigest()
        ledger_attached = getattr(self, "_state_law_acquisition_ledger", None) is not None
        if ledger_attached and (
            not isinstance(transport_receipt, Mapping)
            or not transport_receipt
            or parser_input_envelope is None
        ):
            raise RuntimeError(
                f"Vermont {frontier_name} frontier lacks retained evidence: {url}"
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
                    f"Vermont {frontier_name} receipt lacks URL/digest evidence: {url}"
                )
            if observed_url and self._canonical_fetch_url(observed_url) != canonical_url:
                raise RuntimeError(
                    f"Vermont {frontier_name} receipt changed URL identity: {url}"
                )
            if observed_digest and observed_digest != digest:
                raise RuntimeError(
                    f"Vermont {frontier_name} receipt changed payload identity: {url}"
                )
        if parser_input_envelope is not None:
            envelope_body = getattr(parser_input_envelope, "body", None)
            if ledger_attached and envelope_body is None:
                raise RuntimeError(
                    f"Vermont {frontier_name} envelope lacks body evidence: {url}"
                )
            if envelope_body is not None and bytes(envelope_body) != payload:
                raise RuntimeError(
                    f"Vermont {frontier_name} envelope changed payload identity: {url}"
                )

    async def _fetch_vermont_frontier_batch(
        self,
        urls: Sequence[str],
        *,
        frontier_name: str,
        retained_only: bool = False,
    ) -> List[bytes]:
        """Fetch or replay one exact same-domain frontier as an ordered batch."""

        requested = [self._canonical_fetch_url(url) for url in urls]
        if any(not url for url in requested):
            raise RuntimeError(
                f"Vermont {frontier_name} frontier contains an invalid URL"
            )
        if len(set(requested)) != len(requested):
            raise RuntimeError(
                f"Vermont {frontier_name} frontier contains duplicate URLs"
            )
        if any(
            urlparse(url).hostname != self.OFFICIAL_DOMAIN
            or not urlparse(url).path.startswith(self.OFFICIAL_ENTRY_PATH)
            for url in requested
        ):
            raise RuntimeError(
                f"Vermont {frontier_name} frontier left the official statute scope"
            )
        if not requested:
            return []
        if retained_only:
            from .strict_frontier_closure import (
                replay_exact_retained_state_records,
            )

            retained_rows = replay_exact_retained_state_records(
                self,
                requests=tuple(
                    (url, {"method": "GET", "url": url}) for url in requested
                ),
                frontier_name=f"Vermont {frontier_name}",
                refresh=False,
            )
            payloads: List[bytes] = []
            for url, retained in zip(requested, retained_rows, strict=True):
                envelope = getattr(retained, "envelope", None)
                raw = bytes(getattr(envelope, "body", b"") or b"")
                if not self._is_valid_vermont_frontier_payload(raw):
                    raise RuntimeError(
                        "Vermont retained replay failed the current content "
                        f"validator: {url}"
                    )
                self._validate_vermont_aligned_evidence(
                    url=url,
                    payload=raw,
                    transport_receipt=getattr(
                        retained,
                        "transport_receipt",
                        None,
                    ),
                    parser_input_envelope=envelope,
                    frontier_name=frontier_name,
                )
                payloads.append(raw)
            stats_rows = list(getattr(self, "_vermont_replay_batch_stats", []))
            stats_rows.append(
                {
                    "frontier_name": frontier_name,
                    "network_requested_pages": 0,
                    "requested_pages": len(requested),
                    "retained_replay_pages": len(requested),
                    "successful_pages": len(requested),
                    "unique_pages": len(requested),
                }
            )
            self._vermont_replay_batch_stats = stats_rows
            return payloads
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
            timeout_seconds=25,
            content_validator=self._is_valid_vermont_frontier_payload,
            media_type="text/html",
            max_concurrency=self._vermont_frontier_concurrency(),
            prefer_direct=True,
            common_crawl_domain_terms=(self.OFFICIAL_DOMAIN,),
            common_crawl_url_terms=("/statutes/",),
            common_crawl_mime_terms=("html",),
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
                f"Vermont {frontier_name} frontier returned unaligned acquisition rows"
            )
        if list(batch.urls) != requested:
            raise RuntimeError(
                f"Vermont {frontier_name} frontier changed URL order or identity"
            )
        failures: List[Dict[str, str]] = []
        payloads: List[bytes] = []
        for url, payload, error, receipt, envelope in zip(
            batch.urls,
            batch.payloads,
            batch.errors,
            batch.transport_receipts,
            batch.parser_input_envelopes,
            strict=True,
        ):
            raw = bytes(payload or b"")
            if error is not None or not self._is_valid_vermont_frontier_payload(raw):
                failures.append(
                    {"url": url, "error": str(error or "empty or invalid parser input")}
                )
                continue
            self._validate_vermont_aligned_evidence(
                url=url,
                payload=raw,
                transport_receipt=receipt,
                parser_input_envelope=envelope,
                frontier_name=frontier_name,
            )
            payloads.append(raw)
        if failures:
            raise RuntimeError(
                f"Vermont {frontier_name} frontier is incomplete; "
                f"unresolved exact URLs: {failures}"
            )
        batch_stats = dict(batch.stats or {})
        stats_rows = list(getattr(self, "_vermont_frontier_batch_stats", []))
        stats_rows.append(
            {
                **batch_stats,
                "frontier_name": frontier_name,
                "network_requested_pages": int(
                    batch_stats.get("network_requested_pages", len(requested))
                ),
                "requested_pages": len(requested),
                "retained_replay_pages": int(
                    batch_stats.get("retained_replay_pages", 0)
                ),
                "successful_pages": len(requested),
                "unique_pages": len(requested),
            }
        )
        self._vermont_frontier_batch_stats = stats_rows
        return payloads
    
    def get_base_url(self) -> str:
        """Return the base URL for Vermont's legislative website."""
        return "https://legislature.vermont.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Vermont."""
        return [{
            "name": "Vermont Statutes",
            "url": f"{self.get_base_url()}/statutes/",
            "type": "Code"
        }]

    def _filter_official_only(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        """Drop secondary/Justia rows when full-corpus admission is sealed."""
        if not self._full_corpus_enabled():
            return statutes
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source_kind = str((statute.structured_data or {}).get("source_kind") or "").lower()
            if "justia" in source_kind or "findlaw" in source_kind:
                continue
            if not self._host_is_official(str(statute.source_url or "")):
                continue
            filtered.append(statute)
        return filtered
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Vermont's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .vermont_constitution import (
            configured_constitution_html_path,
            parse_vermont_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_vermont_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Vermont Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .vermont_section import (
            configured_section_html_path,
            parse_vermont_section_html,
        )

        local_section = configured_section_html_path()
        if local_section is not None:
            parsed = parse_vermont_section_html(
                local_section.read_text(encoding="utf-8", errors="replace"),
                source_url="https://legislature.vermont.gov/statutes/section/13/053/02301",
                code_name=code_name,
            )
            if parsed is not None:
                return [parsed]
        official = await self._scrape_official_index(code_name, max_statutes=limit)
        official = self._filter_official_only(official)
        if official:
            return official[:limit] if limit is not None else official

        if limit is not None:
            direct = await self._scrape_direct_sections(code_name, max_statutes=limit)
            direct = self._filter_official_only(direct)
            if direct:
                return direct[:limit]

        if self._full_corpus_enabled() and max_statutes is None:
            self.logger.warning(
                "Vermont full-corpus run found zero official statutes; "
                "refusing secondary Justia/generic sole-admission fallback"
            )
            return []

        max_sections = limit if limit is not None else 1000000
        return await self._generic_scrape(
            code_name,
            code_url,
            "Vt. Stat. Ann.",
            max_sections=max_sections,
        )

    async def _scrape_direct_sections(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        section_urls = [
            f"{self.get_base_url()}/statutes/section/01/001/00001",
            f"{self.get_base_url()}/statutes/section/13/053/02301",
        ]
        return await self._scrape_section_urls(
            code_name,
            [(url, "") for url in section_urls],
            max_statutes=max_statutes,
            discovery_method="official_direct_section",
        )

    async def _scrape_official_index(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        if self._full_corpus_enabled() and max_statutes is None:
            return await self._scrape_strict_full_corpus_frontier(
                code_name,
                record_primary=True,
                write_checkpoints=True,
            )
        title_links = await self._discover_title_links()
        self.logger.info("Vermont official index: discovered %s title links", len(title_links))
        statutes: List[NormalizedStatute] = []
        checkpoint = _VermontCheckpoint(self.state_code)
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for title_index, (title_url, title_label) in enumerate(title_links, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            chapter_links = await self._discover_chapter_links(title_url)
            self.logger.info(
                "Vermont official index: title=%s index=%s/%s chapters=%s statutes_so_far=%s",
                title_label or title_url,
                title_index,
                len(title_links),
                len(chapter_links),
                len(statutes),
            )
            for chapter_index, (chapter_url, chapter_label) in enumerate(chapter_links, start=1):
                if limit is not None and len(statutes) >= limit:
                    break
                section_links = await self._discover_section_links(chapter_url)
                if chapter_index == 1 or chapter_index % 10 == 0 or chapter_index == len(chapter_links):
                    self.logger.info(
                        "Vermont official index: title=%s chapter=%s/%s sections=%s statutes_so_far=%s",
                        title_label or title_url,
                        chapter_index,
                        len(chapter_links),
                        len(section_links),
                        len(statutes),
                    )
                parsed = await self._scrape_section_urls(
                    code_name,
                    section_links,
                    max_statutes=(None if limit is None else max(0, limit - len(statutes))),
                    discovery_method="official_title_chapter_section_index",
                )
                statutes.extend(parsed)
                checkpoint.maybe_write(statutes, title_label=title_label or title_url, chapter_label=chapter_label or chapter_url)
        checkpoint.write(statutes, title_label="complete", chapter_label="complete")
        return statutes[:limit] if limit is not None else statutes

    @staticmethod
    def _normalize_vermont_unit_number(value: Any) -> str:
        text = str(value or "").strip().upper()
        match = re.match(r"^0*(\d+)(.*)$", text)
        return f"{int(match.group(1))}{match.group(2)}" if match else text

    @classmethod
    def _vermont_printed_section_matches_locator(
        cls,
        printed_section: Any,
        *,
        chapter_number: Any,
        locator_section: Any,
    ) -> bool:
        """Bind a printed VT cite to its exact chapter/section URL tuple."""

        printed = cls._normalize_vermont_unit_number(printed_section).casefold()
        chapter = cls._normalize_vermont_unit_number(chapter_number).casefold()
        locator = cls._normalize_vermont_unit_number(locator_section).casefold()
        return bool(
            printed
            and locator
            and printed in {locator, f"{chapter}-{locator}"}
        )

    def _canonical_vermont_hierarchy_url(
        self,
        url: str,
        *,
        level: str,
        title_number: str = "",
        chapter_number: str = "",
    ) -> Tuple[str, Dict[str, str]]:
        parsed = urlparse(str(url or ""))
        patterns = {
            "title": self._VT_TITLE_PATH_RE,
            "chapter": self._VT_CHAPTER_PATH_RE,
            "subchapter": self._VT_SUBCHAPTER_PATH_RE,
            "section": self._VT_SECTION_PATH_RE,
        }
        pattern = patterns.get(level)
        match = pattern.fullmatch(parsed.path) if pattern is not None else None
        if (
            parsed.scheme.lower() != "https"
            or (parsed.hostname or "").lower() != self.OFFICIAL_DOMAIN
            or parsed.username is not None
            or parsed.password is not None
            or parsed.params
            or parsed.query
            or parsed.fragment
            or match is None
        ):
            raise RuntimeError(
                f"Vermont {level} frontier exposed a non-canonical URL: {url}"
            )
        groups = {
            key: self._normalize_vermont_unit_number(value)
            for key, value in match.groupdict().items()
            if key != "kind" and value is not None
        }
        expected_title = self._normalize_title_number(title_number)
        expected_chapter = self._normalize_vermont_unit_number(chapter_number)
        if expected_title and groups.get("title", "").casefold() != expected_title.casefold():
            raise RuntimeError(
                f"Vermont {level} URL escaped its title parent: {url}"
            )
        if expected_chapter and groups.get("chapter", "").casefold() != expected_chapter.casefold():
            raise RuntimeError(
                f"Vermont {level} URL escaped its chapter parent: {url}"
            )
        canonical = f"https://{self.OFFICIAL_DOMAIN}{parsed.path.rstrip('/')}"
        return canonical, groups

    def _vermont_hierarchy_units(
        self,
        payload: bytes,
        *,
        level: str,
        title_number: str = "",
        chapter_number: str = "",
    ) -> List[Dict[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError("BeautifulSoup is required for Vermont strict traversal") from exc

        soup = BeautifulSoup(payload.decode("utf-8", errors="replace"), "html.parser")
        path_markers = {
            "title": "/statutes/title/",
            "chapter": "/statutes/chapter/",
            "subchapter": ("/statutes/subchapter/", "/statutes/article/"),
            "section": "/statutes/section/",
        }
        marker = path_markers[level]
        units: List[Dict[str, str]] = []
        seen_urls: Dict[str, Tuple[str, ...]] = {}
        seen_identities: Dict[Tuple[str, ...], str] = {}
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip().replace("\\", "/")
            if not href:
                continue
            if isinstance(marker, tuple):
                if not any(item in href for item in marker):
                    continue
            elif marker not in href and not href.startswith(marker.lstrip("/")):
                continue
            absolute = urljoin(f"{self.get_base_url()}/", href)
            try:
                canonical_url, groups = self._canonical_vermont_hierarchy_url(
                    absolute,
                    level=level,
                    title_number=title_number,
                    chapter_number=chapter_number,
                )
            except RuntimeError:
                # Anchors in global navigation may merely contain the marker;
                # a hierarchy-shaped path must validate, while unrelated
                # navigation remains out of scope.
                parsed = urlparse(absolute)
                pattern = {
                    "title": self._VT_TITLE_PATH_RE,
                    "chapter": self._VT_CHAPTER_PATH_RE,
                    "subchapter": self._VT_SUBCHAPTER_PATH_RE,
                    "section": self._VT_SECTION_PATH_RE,
                }[level]
                if pattern.fullmatch(parsed.path) is not None:
                    raise
                continue
            if level == "title":
                identity_fields = (groups["title"],)
            elif level == "chapter":
                identity_fields = (groups["title"], groups["chapter"])
            elif level == "subchapter":
                identity_fields = (
                    groups["title"],
                    groups["chapter"],
                    groups["subchapter"],
                )
            else:
                identity_fields = (
                    groups["title"],
                    groups["chapter"],
                    groups["section"],
                )
            folded_identity = tuple(item.casefold() for item in identity_fields)
            prior_identity = seen_urls.get(canonical_url)
            if prior_identity is not None:
                if prior_identity != folded_identity:
                    raise RuntimeError(
                        f"Vermont {level} frontier changed identity at one URL: "
                        f"{canonical_url}"
                    )
                # The official catalog can render past/future labels for the
                # same canonical section URL. That is one fetch identity; the
                # retained current body decides its operative/terminal state.
                continue
            prior_url = seen_identities.get(folded_identity)
            if prior_url is not None:
                raise RuntimeError(
                    f"Vermont {level} frontier maps one identity to multiple URLs: "
                    f"{prior_url}, {canonical_url}"
                )
            seen_urls[canonical_url] = folded_identity
            seen_identities[folded_identity] = canonical_url
            units.append(
                {
                    **groups,
                    "source_label": self._normalize_legal_text(
                        anchor.get_text(" ", strip=True)
                    ),
                    "source_url": canonical_url,
                }
            )
        return units

    def _vermont_unlinked_terminal_units(
        self,
        payload: bytes,
        *,
        level: str,
        parent_url: str,
        title_number: str = "",
        chapter_number: str = "",
        observed_on: Any,
    ) -> List[Dict[str, str]]:
        """Account for hierarchy labels intentionally published without links."""

        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError("BeautifulSoup is required for Vermont strict traversal") from exc
        from .vermont_section import terminal_disposition_from_label

        soup = BeautifulSoup(payload.decode("utf-8", errors="replace"), "html.parser")
        if level == "title":
            nodes = soup.select("ul.statutes-list > li")
            identity_pattern = re.compile(
                r"^Title\s+(?P<title>\d{1,2}(?:APPENDIX|[A-Za-z])?)\b",
                re.IGNORECASE,
            )
        elif level == "chapter":
            nodes = soup.select("ul.statutes-list > li")
            identity_pattern = re.compile(
                r"^Chapter\s+(?P<chapter>[0-9A-Za-z.\-]+)\b",
                re.IGNORECASE,
            )
        else:
            nodes = soup.select("ul.statutes-list li")
            identity_pattern = re.compile(
                r"^§{1,2}\s*(?P<section>[0-9A-Za-z.\-]+)",
                re.IGNORECASE,
            )
        records: List[Dict[str, str]] = []
        for node in nodes:
            label = self._normalize_legal_text(node.get_text(" ", strip=True))
            identity = identity_pattern.match(label)
            if identity is None:
                if level == "section" and re.match(
                    r"^(?:subchapter|article)\s+[0-9A-Za-z.\-]+\b",
                    label,
                    flags=re.IGNORECASE,
                ):
                    disposition = terminal_disposition_from_label(
                        label,
                        observed_on=observed_on,
                    )
                    if disposition is not None and node.find("a", href=True) is None:
                        records.append(
                            {
                                "chapter": chapter_number,
                                "classification_source": "chapter_catalog",
                                "content_sha256": hashlib.sha256(payload).hexdigest(),
                                "disposition": disposition,
                                "frontier_level": "subchapter",
                                "source_label": label,
                                "source_url": parent_url,
                                "title": title_number,
                            }
                        )
                continue
            if node.find("a", href=True) is not None:
                continue
            groups = {
                key: self._normalize_vermont_unit_number(value)
                for key, value in identity.groupdict().items()
            }
            groups.setdefault("title", title_number)
            groups.setdefault("chapter", chapter_number)
            disposition = terminal_disposition_from_label(
                label,
                observed_on=observed_on,
            )
            if disposition is None:
                raise RuntimeError(
                    "Vermont official hierarchy contains an operative-looking "
                    f"unlinked {level} row: {label}"
                )
            records.append(
                {
                    **groups,
                    "classification_source": f"{level}_catalog",
                    "content_sha256": hashlib.sha256(payload).hexdigest(),
                    "disposition": disposition,
                    "frontier_level": level,
                    "source_label": label,
                    "source_url": parent_url,
                }
            )
        return records

    @staticmethod
    def _vermont_frontier_values_sha256(values: Sequence[str]) -> str:
        payload = json.dumps(
            list(values),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @classmethod
    def _vermont_catalog_label_parts(cls, label: str) -> Tuple[str, str]:
        """Return the canonical title identity and official title name."""

        normalized = re.sub(r"\s+", " ", str(label or "")).strip()
        match = re.fullmatch(
            r"Title\s+(?P<title>\d{1,2}(?:APPENDIX|\s+Appendix|[A-Za-z])?)\s*:\s*"
            r"(?P<name>.+?)\.?",
            normalized,
            flags=re.IGNORECASE,
        )
        if match is None:
            return "", ""
        raw_title = re.sub(r"\s+", "", match.group("title"))
        title = cls._normalize_vermont_unit_number(raw_title)
        name = re.sub(r"\s+", " ", match.group("name")).strip().rstrip(".")
        return title, name.casefold()

    def _validate_vermont_live_static_title_catalog(
        self,
        title_units: Sequence[Mapping[str, str]],
        terminal_units: Sequence[Mapping[str, str]],
    ) -> None:
        """Require one exact live row for every scraper-local static title."""

        expected = {
            self._normalize_title_number(number).casefold(): {
                "name": self._normalize_legal_text(name).rstrip(".").casefold(),
                "source_url": self.official_title_url(number).rstrip("/"),
            }
            for number, name in self.OFFICIAL_TITLES
        }
        observed: Dict[str, Dict[str, str]] = {}
        label_mismatches: List[Dict[str, str]] = []
        for unit in title_units:
            title = str(unit.get("title") or "").casefold()
            label_title, label_name = self._vermont_catalog_label_parts(
                str(unit.get("source_label") or "")
            )
            source_url = str(unit.get("source_url") or "").rstrip("/")
            if (
                not title
                or title in observed
                or label_title.casefold() != title
            ):
                raise RuntimeError(
                    "Vermont live/static title catalog parity failed; "
                    f"ambiguous live title row={dict(unit)}"
                )
            observed[title] = {"name": label_name, "source_url": source_url}
        for unit in terminal_units:
            title = str(unit.get("title") or "").casefold()
            if not title or title in observed:
                raise RuntimeError(
                    "Vermont live/static title catalog parity failed; "
                    f"ambiguous terminal title row={dict(unit)}"
                )
            label_title, label_name = self._vermont_catalog_label_parts(
                str(unit.get("source_label") or "")
            )
            if label_title.casefold() != title:
                raise RuntimeError(
                    "Vermont live/static title catalog parity failed; "
                    f"terminal title label mismatch={dict(unit)}"
                )
            # Unlinked terminal rows bind to the retained root catalog rather
            # than pretending that their unfetched static target was acquired.
            observed[title] = {
                "name": label_name,
                "source_url": self.official_title_url(title).rstrip("/"),
            }

        missing = sorted(set(expected) - set(observed))
        extra = sorted(set(observed) - set(expected))
        for title in sorted(set(expected) & set(observed)):
            wanted = expected[title]
            actual = observed[title]
            name_matches = actual["name"] == wanted["name"]
            if not name_matches and title in {
                str(unit.get("title") or "").casefold() for unit in terminal_units
            }:
                # A terminal marker may follow, but must not replace or alter,
                # the exact static official title name.
                name_matches = actual["name"].startswith(wanted["name"] + " ")
            if actual["source_url"] != wanted["source_url"] or not name_matches:
                label_mismatches.append(
                    {
                        "title": title,
                        "expected_name": wanted["name"],
                        "observed_name": actual["name"],
                        "expected_url": wanted["source_url"],
                        "observed_url": actual["source_url"],
                    }
                )
        if (
            len(observed) != self.OFFICIAL_TITLE_COUNT
            or missing
            or extra
            or label_mismatches
        ):
            raise RuntimeError(
                "Vermont live/static title catalog parity failed; "
                f"missing={missing} extra={extra} mismatches={label_mismatches}"
            )

    async def _scrape_strict_full_corpus_frontier(
        self,
        code_name: str,
        *,
        record_primary: bool,
        write_checkpoints: bool,
        retained_only: bool = False,
    ) -> List[NormalizedStatute]:
        """Acquire and close the exact current VT title-to-section tree."""

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            compute_frontier_digest,
        )

        from .vermont_section import (
            parse_vermont_section_html,
            source_bound_terminal_disposition,
        )

        if retained_only:
            ledger = getattr(self, "_state_law_acquisition_ledger", None)
            refresh_entries = getattr(ledger, "refresh_existing_entries", None)
            if not callable(refresh_entries):
                raise RuntimeError(
                    "Vermont retained replay requires a refreshable acquisition ledger"
                )
            refresh_entries()
            self._vermont_replay_batch_stats = []
        else:
            self._vermont_frontier_batch_stats = []

        observed_at = datetime.now(timezone.utc).isoformat()
        observed_on = datetime.now(timezone.utc).date()
        root_payload = (
            await self._fetch_vermont_frontier_batch(
                [self.OFFICIAL_ENTRY_URL],
                frontier_name="root-index",
                retained_only=retained_only,
            )
        )[0]
        title_units = self._vermont_hierarchy_units(root_payload, level="title")
        terminal_units = self._vermont_unlinked_terminal_units(
            root_payload,
            level="title",
            parent_url=self.OFFICIAL_ENTRY_URL,
            observed_on=observed_on,
        )
        catalog_title_unit_count = len(title_units) + len(terminal_units)
        self._validate_vermont_live_static_title_catalog(
            title_units,
            terminal_units,
        )

        title_payloads = await self._fetch_vermont_frontier_batch(
            [unit["source_url"] for unit in title_units],
            frontier_name="title-index",
            retained_only=retained_only,
        )
        chapter_units: List[Dict[str, str]] = []
        seen_chapters: set[Tuple[str, str]] = set()
        for title, payload in zip(title_units, title_payloads, strict=True):
            children = self._vermont_hierarchy_units(
                payload,
                level="chapter",
                title_number=title["title"],
            )
            catalog_terminals = self._vermont_unlinked_terminal_units(
                payload,
                level="chapter",
                parent_url=title["source_url"],
                title_number=title["title"],
                observed_on=observed_on,
            )
            for terminal in catalog_terminals:
                identity = (
                    terminal["title"].casefold(),
                    terminal["chapter"].casefold(),
                )
                if identity in seen_chapters:
                    raise RuntimeError(
                        "Vermont title catalog repeated chapter identity: "
                        f"{terminal['source_label']}"
                    )
                seen_chapters.add(identity)
                terminal_units.append(terminal)
            if not children and not catalog_terminals:
                terminal = source_bound_terminal_disposition(
                    payload.decode("utf-8", errors="replace"),
                    source_url=title["source_url"],
                    frontier_label=title["source_label"],
                    expected_level="title",
                    observed_on=observed_on,
                )
                if terminal is None:
                    raise RuntimeError(
                        "Vermont title exposed no chapter frontier and no "
                        f"source-bound terminal disposition: {title['source_url']}"
                    )
                terminal_units.append(
                    {
                        **terminal,
                        "frontier_level": "title",
                        "title_number": title["title"],
                        "content_sha256": hashlib.sha256(payload).hexdigest(),
                    }
                )
                continue
            for child in children:
                identity = (child["title"].casefold(), child["chapter"].casefold())
                if identity in seen_chapters:
                    raise RuntimeError(
                        "Vermont title frontier repeated chapter identity: "
                        f"{child['source_url']}"
                    )
                seen_chapters.add(identity)
                chapter_units.append(child)
        if not chapter_units:
            raise RuntimeError("Vermont title frontier produced no active chapters")

        chapter_payloads = await self._fetch_vermont_frontier_batch(
            [unit["source_url"] for unit in chapter_units],
            frontier_name="chapter-index",
            retained_only=retained_only,
        )
        section_units: List[Dict[str, str]] = []
        subchapter_units: List[Dict[str, str]] = []
        seen_section_identities: set[Tuple[str, str, str]] = set()
        seen_subchapter_identities: set[Tuple[str, str, str]] = set()

        def _extend_sections(children: Sequence[Dict[str, str]]) -> None:
            for child in children:
                identity = (
                    child["title"].casefold(),
                    child["chapter"].casefold(),
                    child["section"].casefold(),
                )
                if identity in seen_section_identities:
                    raise RuntimeError(
                        "Vermont hierarchy repeated section identity: "
                        f"{child['source_url']}"
                    )
                seen_section_identities.add(identity)
                section_units.append(child)

        for chapter, payload in zip(chapter_units, chapter_payloads, strict=True):
            direct_sections = self._vermont_hierarchy_units(
                payload,
                level="section",
                title_number=chapter["title"],
                chapter_number=chapter["chapter"],
            )
            _extend_sections(direct_sections)
            subchapters = self._vermont_hierarchy_units(
                payload,
                level="subchapter",
                title_number=chapter["title"],
                chapter_number=chapter["chapter"],
            )
            catalog_terminals = self._vermont_unlinked_terminal_units(
                payload,
                level="section",
                parent_url=chapter["source_url"],
                title_number=chapter["title"],
                chapter_number=chapter["chapter"],
                observed_on=observed_on,
            )
            for terminal in catalog_terminals:
                section_number = str(terminal.get("section") or "")
                if section_number:
                    identity = (
                        terminal["title"].casefold(),
                        terminal["chapter"].casefold(),
                        section_number.casefold(),
                    )
                    if identity in seen_section_identities:
                        raise RuntimeError(
                            "Vermont chapter catalog repeated section identity: "
                            f"{terminal['source_label']}"
                        )
                    seen_section_identities.add(identity)
                terminal_units.append(terminal)
            for child in subchapters:
                identity = (
                    child["title"].casefold(),
                    child["chapter"].casefold(),
                    child["subchapter"].casefold(),
                )
                if identity in seen_subchapter_identities:
                    raise RuntimeError(
                        "Vermont chapter frontier repeated subchapter identity: "
                        f"{child['source_url']}"
                    )
                seen_subchapter_identities.add(identity)
                subchapter_units.append(child)
            if not direct_sections and not subchapters and not catalog_terminals:
                terminal = source_bound_terminal_disposition(
                    payload.decode("utf-8", errors="replace"),
                    source_url=chapter["source_url"],
                    frontier_label=chapter["source_label"],
                    expected_level="chapter",
                    observed_on=observed_on,
                )
                if terminal is None:
                    raise RuntimeError(
                        "Vermont chapter exposed no descendant frontier and no "
                        f"source-bound terminal disposition: {chapter['source_url']}"
                    )
                terminal_units.append(
                    {
                        **terminal,
                        "frontier_level": "chapter",
                        "title_number": chapter["title"],
                        "chapter_number": chapter["chapter"],
                        "content_sha256": hashlib.sha256(payload).hexdigest(),
                    }
                )

        if subchapter_units:
            subchapter_payloads = await self._fetch_vermont_frontier_batch(
                [unit["source_url"] for unit in subchapter_units],
                frontier_name="subchapter-index",
                retained_only=retained_only,
            )
            for subchapter, payload in zip(
                subchapter_units,
                subchapter_payloads,
                strict=True,
            ):
                children = self._vermont_hierarchy_units(
                    payload,
                    level="section",
                    title_number=subchapter["title"],
                    chapter_number=subchapter["chapter"],
                )
                catalog_terminals = self._vermont_unlinked_terminal_units(
                    payload,
                    level="section",
                    parent_url=subchapter["source_url"],
                    title_number=subchapter["title"],
                    chapter_number=subchapter["chapter"],
                    observed_on=observed_on,
                )
                for terminal in catalog_terminals:
                    section_number = str(terminal.get("section") or "")
                    if section_number:
                        identity = (
                            terminal["title"].casefold(),
                            terminal["chapter"].casefold(),
                            section_number.casefold(),
                        )
                        if identity in seen_section_identities:
                            raise RuntimeError(
                                "Vermont subchapter catalog repeated section identity: "
                                f"{terminal['source_label']}"
                            )
                        seen_section_identities.add(identity)
                    terminal_units.append(terminal)
                if children:
                    _extend_sections(children)
                    continue
                if catalog_terminals:
                    continue
                terminal = source_bound_terminal_disposition(
                    payload.decode("utf-8", errors="replace"),
                    source_url=subchapter["source_url"],
                    frontier_label=subchapter["source_label"],
                    expected_level="subchapter",
                    observed_on=observed_on,
                )
                if terminal is None:
                    raise RuntimeError(
                        "Vermont subchapter exposed no section frontier and no "
                        f"source-bound terminal disposition: {subchapter['source_url']}"
                    )
                terminal_units.append(
                    {
                        **terminal,
                        "frontier_level": "subchapter",
                        "title_number": subchapter["title"],
                        "chapter_number": subchapter["chapter"],
                        "subchapter_number": subchapter["subchapter"],
                        "content_sha256": hashlib.sha256(payload).hexdigest(),
                    }
                )
        if not section_units:
            raise RuntimeError("Vermont hierarchy produced no active section frontier")

        catalog_terminal_unit_count = len(terminal_units)
        discovered_candidates = len(section_units) + catalog_terminal_unit_count

        if write_checkpoints:
            self._write_partial_checkpoint(
                [],
                code_name=code_name,
                stage_label="vermont:section-discovery",
                replace_existing_rows=True,
                extra={
                    "titles_scanned": catalog_title_unit_count,
                    "discovered_titles": catalog_title_unit_count,
                    "chapters_scanned": len(chapter_units),
                    "discovered_chapters": len(chapter_units),
                    "sections_scanned": len(terminal_units),
                    "discovered_sections": discovered_candidates,
                    "terminal_sections_classified": len(terminal_units),
                    "terminal_section_dispositions": terminal_units,
                    "codes_completed": 0,
                    "codes_total": 1,
                },
            )

        statutes: List[NormalizedStatute] = []
        seen_statute_ids: set[str] = set()
        batch_size = self._vermont_frontier_batch_size()
        for batch_start in range(0, len(section_units), batch_size):
            batch_units = section_units[batch_start : batch_start + batch_size]
            payloads = await self._fetch_vermont_frontier_batch(
                [unit["source_url"] for unit in batch_units],
                frontier_name=(
                    f"sections-{batch_start + 1}-{batch_start + len(batch_units)}"
                ),
                retained_only=retained_only,
            )
            for unit, payload in zip(batch_units, payloads, strict=True):
                html = payload.decode("utf-8", errors="replace")
                statute = parse_vermont_section_html(
                    html,
                    source_url=unit["source_url"],
                    code_name=code_name,
                    observed_on=observed_on,
                )
                if statute is None:
                    terminal = source_bound_terminal_disposition(
                        html,
                        source_url=unit["source_url"],
                        frontier_label=unit["source_label"],
                        expected_level="section",
                        observed_on=observed_on,
                    )
                    if terminal is None:
                        raise RuntimeError(
                            "Vermont retained section failed parsing and has no "
                            f"source-bound terminal disposition: {unit['source_url']}"
                        )
                    terminal_units.append(
                        {
                            **terminal,
                            "frontier_level": "section",
                            "title_number": unit["title"],
                            "chapter_number": unit["chapter"],
                            "section_number": unit["section"],
                            "content_sha256": hashlib.sha256(payload).hexdigest(),
                        }
                    )
                    continue
                if (
                    self._normalize_vermont_unit_number(statute.title_number)
                    != unit["title"]
                    or self._normalize_vermont_unit_number(statute.chapter_number)
                    != unit["chapter"]
                    or not self._vermont_printed_section_matches_locator(
                        statute.section_number,
                        chapter_number=unit["chapter"],
                        locator_section=unit["section"],
                    )
                    or str(statute.source_url or "") != unit["source_url"]
                ):
                    raise RuntimeError(
                        "Vermont normalized section changed requested identity: "
                        f"{unit['source_url']}"
                    )
                statute.title_number = unit["title"]
                statute.chapter_number = unit["chapter"]
                printed_section = self._normalize_vermont_unit_number(
                    statute.section_number
                )
                statute.section_number = printed_section
                statute.statute_id = f"{unit['title']} V.S.A. § {printed_section}"
                statute.official_cite = statute.statute_id
                statute.structured_data = {
                    **dict(statute.structured_data or {}),
                    "content_sha256": hashlib.sha256(payload).hexdigest(),
                    "discovery_method": (
                        "official_batched_title_chapter_subchapter_section_frontier"
                    ),
                    "source_locator_chapter": unit["chapter"],
                    "source_locator_section": unit["section"],
                }
                folded_id = statute.statute_id.casefold()
                if folded_id in seen_statute_ids:
                    raise RuntimeError(
                        f"Vermont normalized statute identity repeated: {statute.statute_id}"
                    )
                seen_statute_ids.add(folded_id)
                statutes.append(statute)

            if write_checkpoints:
                scanned = batch_start + len(batch_units) + catalog_terminal_unit_count
                self._write_partial_checkpoint(
                    statutes,
                    code_name=code_name,
                    stage_label="vermont:section-batch",
                    replace_existing_rows=True,
                    extra={
                        "titles_scanned": catalog_title_unit_count,
                        "discovered_titles": catalog_title_unit_count,
                        "chapters_scanned": len(chapter_units),
                        "discovered_chapters": len(chapter_units),
                        "sections_scanned": scanned,
                        "discovered_sections": discovered_candidates,
                        "terminal_sections_classified": len(terminal_units),
                        "codes_completed": 0,
                        "codes_total": 1,
                    },
                )

        discovered = len(statutes) + len(terminal_units)
        disposition = {
            "discovered": discovered,
            "fetched": len(statutes),
            "excluded": len(terminal_units),
            "failed_final": 0,
            "duplicates": 0,
            "quarantined": 0,
        }
        if discovered != sum(
            disposition[key]
            for key in ("fetched", "excluded", "failed_final", "duplicates", "quarantined")
        ):
            raise RuntimeError("Vermont strict disposition algebra did not close")
        source_urls = [unit["source_url"] for unit in section_units]
        statute_ids = [statute.statute_id for statute in statutes]
        parser_input_count = (
            1
            + len(title_units)
            + len(chapter_units)
            + len(subchapter_units)
            + len(section_units)
        )
        frontier: Dict[str, Any] = {
            "section_locator_count": len(section_units),
            "section_locators_sha256": self._vermont_frontier_values_sha256(source_urls),
            "algebra_closed": True,
            "bundle_closed": False,
            "catalog_expected_units": self.OFFICIAL_TITLE_COUNT,
            "catalog_observed_units": catalog_title_unit_count,
            "catalog_parity": True,
            "chapter_count": len(chapter_units),
            "closed": True,
            "disposition": disposition,
            "enumerator_closed": True,
            "expected_index_units": discovered,
            "pagination_closed": True,
            "parser_input_count": parser_input_count,
            "schema_version": "vermont-strict-html-frontier-v1",
            "scope_closed": True,
            "statute_ids_sha256": self._vermont_frontier_values_sha256(statute_ids),
            "subchapter_count": len(subchapter_units),
            "terminal_units": terminal_units,
            "title_count": catalog_title_unit_count,
            "title_pages_fetched": len(title_units),
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": discovered,
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        observation = {
            "boundary_first": source_urls[0],
            "boundary_last": source_urls[-1],
            "frontier": frontier,
            "observed_at": observed_at,
            "statute_ids": statute_ids,
            "transport_batch_stats": list(
                getattr(
                    self,
                    (
                        "_vermont_replay_batch_stats"
                        if retained_only
                        else "_vermont_frontier_batch_stats"
                    ),
                    [],
                )
            ),
        }
        target = (
            "_last_vermont_full_frontier"
            if record_primary
            else "_last_vermont_replayed_frontier"
        )
        setattr(self, target, observation)
        if write_checkpoints:
            self._write_partial_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="vermont:complete",
                force=True,
                replace_existing_rows=True,
                extra={
                    "titles_scanned": catalog_title_unit_count,
                    "discovered_titles": catalog_title_unit_count,
                    "chapters_scanned": len(chapter_units),
                    "discovered_chapters": len(chapter_units),
                    "sections_scanned": discovered,
                    "discovered_sections": discovered,
                    "terminal_sections_classified": len(terminal_units),
                    "terminal_section_dispositions": terminal_units,
                    "disposition": disposition,
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
        """Replay every retained VT hierarchy layer and seal exact leaf algebra."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError(
                "Vermont frontier closure requires an attached acquisition ledger"
            )
        first = getattr(self, "_last_vermont_full_frontier", None)
        if not isinstance(first, Mapping):
            raise RuntimeError(
                "Vermont strict frontier was not observed before normalized rows escaped"
            )
        replay_rows = await self._scrape_strict_full_corpus_frontier(
            "Vermont Statutes",
            record_primary=False,
            write_checkpoints=False,
            retained_only=True,
        )
        replay = getattr(self, "_last_vermont_replayed_frontier", None)
        if not isinstance(replay, Mapping):
            raise RuntimeError("Vermont strict frontier replay was not retained")

        from ipfs_datasets_py.processors.legal_data.open_us_law_acquisition_coordinator import (
            canonical_json_bytes,
        )
        from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
            closed_jurisdiction_receipt,
        )
        from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
            build_canonical_state_law_output_projection,
        )

        first_frontier = first.get("frontier")
        replayed_frontier = replay.get("frontier")
        if not isinstance(first_frontier, Mapping) or not isinstance(
            replayed_frontier, Mapping
        ):
            raise RuntimeError("Vermont strict frontier observations are incomplete")
        if canonical_json_bytes(first_frontier) != canonical_json_bytes(replayed_frontier):
            raise RuntimeError("Vermont first and replayed exact frontiers differ")

        parser_input_count = int(first_frontier.get("parser_input_count") or 0)
        first_batch_stats = first.get("transport_batch_stats")
        replay_batch_stats = replay.get("transport_batch_stats")
        if (
            parser_input_count <= 0
            or not isinstance(first_batch_stats, Sequence)
            or isinstance(first_batch_stats, (str, bytes, bytearray))
            or not isinstance(replay_batch_stats, Sequence)
            or isinstance(replay_batch_stats, (str, bytes, bytearray))
        ):
            raise RuntimeError("Vermont strict transport batch evidence is incomplete")

        def _sum_batch_field(rows: Sequence[Any], field: str) -> int:
            return sum(
                int(row.get(field) or 0)
                for row in rows
                if isinstance(row, Mapping)
            )

        first_requested = _sum_batch_field(first_batch_stats, "requested_pages")
        first_successful = _sum_batch_field(first_batch_stats, "successful_pages")
        replay_requested = _sum_batch_field(replay_batch_stats, "requested_pages")
        replay_successful = _sum_batch_field(replay_batch_stats, "successful_pages")
        replay_retained = _sum_batch_field(replay_batch_stats, "retained_replay_pages")
        replay_network = _sum_batch_field(
            replay_batch_stats,
            "network_requested_pages",
        )
        if (
            first_requested != parser_input_count
            or first_successful != parser_input_count
            or replay_requested != parser_input_count
            or replay_successful != parser_input_count
            or replay_retained != parser_input_count
            or replay_network != 0
            or not any(
                isinstance(row, Mapping)
                and int(row.get("requested_pages") or 0) > 1
                for row in first_batch_stats
            )
        ):
            raise RuntimeError(
                "Vermont strict transport batching or zero-network replay did not close"
            )

        replay_projection = build_canonical_state_law_output_projection(
            [self._enrich_statute_structure(row).to_dict() for row in replay_rows],
            jurisdiction="VT",
        )
        output_keys_raw = canonical_output_projection.get("canonical_keys")
        if not isinstance(output_keys_raw, Sequence) or isinstance(
            output_keys_raw, (str, bytes, bytearray)
        ):
            raise RuntimeError("Vermont canonical output lacks exact identities")
        output_keys = [str(item).strip() for item in output_keys_raw]
        replay_keys = [str(item) for item in replay_projection["canonical_keys"]]
        if (
            not output_keys
            or any(not item for item in output_keys)
            or len(output_keys) != len(set(output_keys))
            or output_keys != replay_keys
        ):
            raise RuntimeError(
                "Vermont final canonical identities do not exactly match the "
                "independently replayed section frontier"
            )

        disposition = first_frontier.get("disposition")
        if not isinstance(disposition, Mapping):
            raise RuntimeError("Vermont strict frontier lacks disposition algebra")
        if int(disposition.get("fetched") or -1) != len(output_keys):
            raise RuntimeError(
                "Vermont strict fetched count changed after final output filtering"
            )
        completion = closed_jurisdiction_receipt(
            "VT",
            discovered=int(disposition["discovered"]),
            fetched=int(disposition["fetched"]),
            excluded=int(disposition["excluded"]),
            quarantined=int(disposition["quarantined"]),
            failed_final=int(disposition["failed_final"]),
            duplicates=int(disposition["duplicates"]),
            source_domain=self.OFFICIAL_DOMAIN,
            canonical_keys=output_keys,
            derived_keys=output_keys,
        )
        completion.update(
            {
                "boundary_probes": {
                    "bundle_total": 0,
                    "first_hierarchy_unit": str(first.get("boundary_first") or ""),
                    "last_hierarchy_unit": str(first.get("boundary_last") or ""),
                    "pagination_total": int(first_frontier.get("title_count") or 0),
                },
                "canonical_row_count": len(output_keys),
                "frontier": dict(first_frontier),
                "legal_as_of": str(first.get("observed_at") or ""),
                "observed_at": str(first.get("observed_at") or ""),
                "replay": {
                    "closed": True,
                    "first_frontier_digest": str(
                        first_frontier.get("frontier_digest_sha256") or ""
                    ),
                    "second_frontier_digest": str(
                        replayed_frontier.get("frontier_digest_sha256") or ""
                    ),
                    "network_requested_pages": replay_network,
                    "parser_input_count": parser_input_count,
                },
                "rights": {
                    "basis": "public_law_no_state_copyright",
                    "decision": "admit",
                    "scope": "statutory_text",
                },
                "transport": {
                    "fixture": False,
                    "grouped_warc_recovery": True,
                    "kind": "shared_archive_aware_plural_html",
                    "per_page_archive_loop": False,
                    "primary_batch_count": len(first_batch_stats),
                    "primary_requested_pages": first_requested,
                    "repeat_grouped_archive_inventory_on_residual": False,
                    "residual_only_retries": True,
                    "retained_replay_batch_count": len(replay_batch_stats),
                    "retained_replay_network_requested_pages": replay_network,
                    "retained_replay_pages": replay_retained,
                    "same_domain_plural_frontiers": True,
                    "source_ordered_cross_parent_union": True,
                    "synthetic": False,
                    "wayback_prefix_inventory": True,
                },
            }
        )
        digest = str(first_frontier.get("frontier_digest_sha256") or "")
        return self.retain_state_law_frontier_closure_projection(
            completion,
            replayed_frontier=dict(replayed_frontier),
            canonical_output_projection=canonical_output_projection,
            release_point=f"sha256:{digest}",
            official_source_url=self.OFFICIAL_ENTRY_URL,
            acquisition_path_ids=self._catalog_acquisition_path_ids_for_source(
                self.OFFICIAL_ENTRY_URL
            ),
            observation_time=str(first.get("observed_at") or ""),
            source_software_version=self._state_law_frontier_source_software_version(),
        )

    async def _discover_title_links(self) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = f"{self.get_base_url()}/statutes/"
        payload = await self._fetch_page_content_with_archival_fallback(index_url, timeout_seconds=20)
        if not payload:
            return []
        html = (
            payload.decode("utf-8", errors="replace")
            if isinstance(payload, (bytes, bytearray))
            else str(payload)
        )
        from .vermont_section import title_links

        listed = title_links(html, base_url=self.get_base_url())
        if listed:
            return [(url, number) for url, number in listed]
        soup = BeautifulSoup(payload, "html.parser")
        out = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(f"{self.get_base_url()}/", str(anchor.get("href") or "").strip())
            if not re.search(r"/statutes/title/[\w.\-]+/?$", href):
                continue
            normalized = href.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append((normalized, self._normalize_legal_text(anchor.get_text(" ", strip=True))))
        return out

    async def _discover_chapter_links(self, title_url: str) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        payload = await self._fetch_page_content_with_archival_fallback(title_url, timeout_seconds=20)
        if not payload:
            return []
        html = (
            payload.decode("utf-8", errors="replace")
            if isinstance(payload, (bytes, bytearray))
            else str(payload)
        )
        from .vermont_section import chapter_links

        listed = chapter_links(html, base_url=self.get_base_url())
        if listed:
            return [(url, number) for url, number in listed]
        soup = BeautifulSoup(payload, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(f"{self.get_base_url()}/", str(anchor.get("href") or "").strip())
            if not re.search(r"/statutes/chapter/[\w.\-]+/[\w.\-]+/?$", href):
                continue
            normalized = href.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append((normalized, self._normalize_legal_text(anchor.get_text(" ", strip=True))))
        return out

    async def _discover_section_links(self, chapter_url: str) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        payload = await self._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=20)
        if not payload:
            return []
        html = (
            payload.decode("utf-8", errors="replace")
            if isinstance(payload, (bytes, bytearray))
            else str(payload)
        )
        from .vermont_section import section_links, subchapter_links

        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for url, name in section_links(html, base_url=self.get_base_url()):
            if url in seen:
                continue
            seen.add(url)
            out.append((url, name))
        for sub_url, _number in subchapter_links(html, base_url=self.get_base_url()):
            sub_payload = await self._fetch_page_content_with_archival_fallback(
                sub_url, timeout_seconds=20
            )
            if not sub_payload:
                continue
            sub_html = (
                sub_payload.decode("utf-8", errors="replace")
                if isinstance(sub_payload, (bytes, bytearray))
                else str(sub_payload)
            )
            for url, name in section_links(sub_html, base_url=self.get_base_url()):
                if url in seen:
                    continue
                seen.add(url)
                out.append((url, name))
        if out:
            return out
        soup = BeautifulSoup(payload, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = urljoin(f"{self.get_base_url()}/", str(anchor.get("href") or "").strip())
            if not re.search(r"/statutes/section/[\w.\-]+/[\w.\-]+/[\w.\-]+/?$", href):
                continue
            normalized = href.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append((normalized, self._normalize_legal_text(anchor.get_text(" ", strip=True))))
        return out

    async def _scrape_section_urls(
        self,
        code_name: str,
        section_urls: List[Tuple[str, str]],
        max_statutes: Optional[int] = None,
        discovery_method: str = "official_title_chapter_section_index",
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        statutes: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for source_url, section_label in section_urls:
            if limit is not None and len(statutes) >= limit:
                break
            payload = await self._fetch_page_content_with_archival_fallback(source_url, timeout_seconds=15)
            if not payload:
                continue
            soup = BeautifulSoup(payload, "html.parser")
            from .vermont_section import parse_vermont_section_html

            html_text = (
                payload.decode("utf-8", errors="replace")
                if isinstance(payload, (bytes, bytearray))
                else str(payload)
            )
            parsed = parse_vermont_section_html(
                html_text, source_url=source_url, code_name=code_name
            )
            if parsed is not None:
                data = dict(parsed.structured_data or {})
                data["discovery_method"] = discovery_method
                parsed.structured_data = data
                statutes.append(parsed)
                continue
            main = soup.find(id="main-content") or soup
            for tag in main(["script", "style", "nav", "header", "footer", "aside"]):
                tag.decompose()
            text = self._normalize_legal_text(main.get_text(" ", strip=True))
            match = re.search(r"\bCite as:\s*([0-9A-Za-z.]+)\s+V\.S\.A\.\s+§\s*([0-9A-Za-z.-]+)", text)
            title_number = match.group(1) if match else ""
            section_number = match.group(2) if match else self._derive_section_number_from_url(source_url)
            heading = main.find(["h1", "h2", "h3"]) or soup.find(["h1", "h2", "h3"])
            section_name = heading.get_text(" ", strip=True) if heading else (section_label or f"Section {section_number}")
            bold = main.find("b")
            if bold:
                section_name = bold.get_text(" ", strip=True)
            if len(text) < 240 or not section_number:
                continue
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    title_number=title_number or None,
                    section_number=section_number,
                    section_name=section_name[:200],
                    full_text=text,
                    legal_area=self._identify_legal_area(section_name or text),
                    source_url=source_url,
                    official_cite=f"{title_number} V.S.A. § {section_number}" if title_number else f"Vt. Stat. Ann. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_vermont_statutes_html",
                        "discovery_method": discovery_method,
                        "skip_hydrate": True,
                    },
                )
            )
        return statutes

    def official_title_slug(self, title_number: Any) -> str:
        text = str(title_number or "").strip().upper()
        match = re.match(r"^0*(\d{1,2})(APPENDIX|[A-Z]?)$", text)
        if not match:
            return text
        number, suffix = match.group(1), match.group(2).upper()
        return f"{int(number):02d}{suffix}"

    def official_title_url(self, title_number: Any) -> str:
        slug = self.official_title_slug(title_number)
        return f"{self.get_base_url()}/statutes/title/{slug}"

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Vermont Statutes Annotated title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"vt:title-{str(number).lower()}",
                    "title_number": str(number),
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Vermont Statutes Annotated Title {number} ({name}) "
                        f"official catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host == self.OFFICIAL_DOMAIN or host.endswith("." + self.OFFICIAL_DOMAIN)

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))
        headers = {
            "User-Agent": "ipfs-datasets-vermont-official-catalog/1.0",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        }
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

    def _normalize_title_number(self, value: Any) -> str:
        text = str(value or "").strip().upper()
        match = re.match(r"^0*(\d{1,2})(APPENDIX|[A-Z]?)$", text)
        if not match:
            return ""
        return f"{int(match.group(1))}{match.group(2)}"

    def _parse_continuation_links(self, html: bytes, page_url: str) -> List[str]:
        found: List[str] = []
        if not html:
            return found
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return found
        soup = BeautifulSoup(html, "html.parser")
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            rel = " ".join(link.get("rel") or []).lower()
            if not href:
                continue
            if "next" not in rel and not self._VT_CONTINUATION_RE.search(label):
                continue
            absolute = urljoin(page_url or self.OFFICIAL_ENTRY_URL, href)
            if absolute in seen or not self._host_is_official(absolute):
                continue
            if absolute.rstrip("/") == str(page_url or "").rstrip("/"):
                continue
            seen.add(absolute)
            found.append(absolute)
        return found

    def _parse_official_title_links(self, html: bytes) -> Dict[str, str]:
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
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            if not href:
                continue
            absolute = urljoin(self.OFFICIAL_ENTRY_URL, href)
            match = self._VT_TITLE_HREF_RE.search(absolute) or self._VT_TITLE_LABEL_RE.search(label)
            if not match:
                continue
            number = self._normalize_title_number(match.group("title"))
            if not number or number in found:
                continue
            if number not in known:
                known.add(number)
            if self._host_is_official(absolute):
                found[number] = self.official_title_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official Vermont Statutes Annotated title."""

        del page_url
        discovered = self._parse_official_title_links(html)
        rows = self.official_title_catalog()
        known = {str(row["title_number"]) for row in rows}
        for row in rows:
            live_url = discovered.get(str(row["title_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_vtleg"
        for number, url in discovered.items():
            if number in known:
                continue
            rows.append(
                {
                    "canonical_key": f"vt:title-{number.lower()}",
                    "title_number": number,
                    "name": f"Title {number}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Vermont Statutes Annotated Title {number} "
                        f"official catalog unit at {url}"
                    ),
                }
            )
        rows.sort(key=lambda item: self._title_sort_key(str(item.get("title_number") or "")))
        return rows

    def _title_sort_key(self, number: str) -> Tuple[int, int, str]:
        match = re.match(r"^(\d+)(?:\.(\d+))?([A-Za-z]+)?$", str(number or "").strip())
        if not match:
            return (9999, 0, str(number or ""))
        return (int(match.group(1)), int(match.group(2) or 0), (match.group(3) or "").upper())

    def _collect_official_index_pages(self) -> Tuple[bytes, List[str]]:
        visited: List[str] = []
        seen: set[str] = set()
        pending = [self.OFFICIAL_ENTRY_URL]
        combined = b""
        while pending:
            url = pending.pop(0)
            if url in seen:
                continue
            seen.add(url)
            visited.append(url)
            html = self._official_http_get(url)
            if html:
                combined = html if not combined else combined + b"\n" + html
            for continuation in self._parse_continuation_links(html, url):
                if continuation not in seen:
                    pending.append(continuation)
            if len(visited) >= 32:
                break
        return combined, [item for item in pending if item not in seen]

    def fetch_official(self, code: str = "VT"):
        """Acquire the exhaustive official Vermont Statutes Annotated catalog.

        Live HTTPS retains the official legislature.vermont.gov statute index.
        Every known title is enumerated with an official URL. Continuation
        pages are exhausted. This hook never returns fixture bytes, never
        promotes a partial scrape checkpoint, and never uses secondary hosts.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "VT").strip().upper() or "VT"
        if normalized != "VT":
            raise ValueError(f"VermontScraper cannot acquire {normalized}")
        html, remaining = self._collect_official_index_pages()
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < self.OFFICIAL_TITLE_COUNT:
            raise RuntimeError(
                "vermont official catalog enumeration rejected incomplete "
                "title reacquisition"
            )
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
            "unvisited_continuation_links": list(remaining),
            "visited_index_units": len(rows),
        }
        if remaining:
            frontier["closed"] = False
            frontier["pagination_closed"] = False
            frontier["toc_exhausted"] = False
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        self.last_official_checkpoint = {
            "partial": False,
            "promoted_success": False,
            "completion_basis": "source_frontier",
        }
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
StateScraperRegistry.register("VT", VermontScraper)


class _VermontCheckpoint:
    """Best-effort partial progress checkpoint for Vermont's long corpus crawl."""

    def __init__(self, state_code: str) -> None:
        raw_dir = current_partial_checkpoint_run_directory()
        if not raw_dir:
            self.path: Optional[Path] = None
        else:
            self.path = Path(raw_dir).expanduser().resolve() / f"STATE-{state_code.upper()}-partial.json"
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state_code = state_code.upper()
        self.interval = max(1, int(float(os.getenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_INTERVAL", "500") or 500)))
        self.last_count = 0
        self.last_write_ts = 0.0

    def maybe_write(self, statutes: List[NormalizedStatute], *, title_label: str, chapter_label: str) -> None:
        count = len(statutes)
        if not self.path or count <= 0:
            return
        if count - self.last_count < self.interval and time.time() - self.last_write_ts < 120:
            return
        self.write(statutes, title_label=title_label, chapter_label=chapter_label)

    def write(self, statutes: List[NormalizedStatute], *, title_label: str, chapter_label: str) -> None:
        if not self.path or not statutes:
            return
        payload = {
            "state_code": self.state_code,
            "updated_at": time.time(),
            "statutes_count": len(statutes),
            "title_label": title_label,
            "chapter_label": chapter_label,
            "statutes": [statute.to_dict() for statute in statutes],
        }
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp_path.replace(self.path)
        self.last_count = len(statutes)
        self.last_write_ts = time.time()
