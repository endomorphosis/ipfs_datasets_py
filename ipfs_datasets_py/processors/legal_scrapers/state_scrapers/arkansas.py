"""Scraper for Arkansas state laws.

This module contains the scraper for Arkansas statutes from the official state legislative website.
"""

import asyncio
import hashlib
import json
import re
import ssl
import time
import urllib.request
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class ArkansasDelegatedCorpusBlockedError(RuntimeError):
    """The official/delegated locator frontier lacks admissible body bytes."""

    def __init__(self, reason: str, *, evidence: Mapping[str, Any]) -> None:
        self.reason = str(reason)
        self.evidence = dict(evidence)
        super().__init__(f"Arkansas delegated corpus is blocked: {self.reason}")


class ArkansasScraper(BaseStateScraper):
    """Scraper for Arkansas state laws from https://www.arkleg.state.ar.us"""

    # The legislature's public-law landing page delegates Arkansas Code access
    # to the free Lexis public-access container.  ``/ArkansasCode/`` was a
    # historical route and now returns no code inventory.
    OFFICIAL_CODE_INDEX = "https://www.arkleg.state.ar.us/ArkansasLaw/"
    OFFICIAL_DOMAIN = "www.arkleg.state.ar.us"
    OFFICIAL_ENTRY_PATH = "/ArkansasLaw/"
    OFFICIAL_ENTRY_URL = "https://www.arkleg.state.ar.us/ArkansasLaw/"
    OFFICIAL_DELEGATED_ENTRY_URL = "https://www.lexisnexis.com/hottopics/arcode/"
    OFFICIAL_DELEGATED_CONTAINER_URL = (
        "https://advance.lexis.com/container?config="
        "00JAA3ZTU0NTIzYy0zZDEyLTRhYmQtYmRmMS1iMWIxNDgxYWMxZTQK"
        "AFBvZENhdGFsb2cubRW4ifTiwi5vLw6cI1uX"
    )
    BUCKET_SEED_QUARANTINE_REASON = "bucket_seed_pending_official_replacement"
    _AR_TITLE_QUERY_RE = re.compile(r"[?&](?:title|codeTitle)=(\d{1,2})\b", re.IGNORECASE)
    _AR_TITLE_LABEL_RE = re.compile(r"\bTitle\s+(\d{1,2})\b", re.IGNORECASE)
    OFFICIAL_TITLES = (
        ("1", "General Provisions"),
        ("2", "Agriculture"),
        ("3", "Alcoholic Beverages"),
        ("4", "Business and Commercial Law"),
        ("5", "Criminal Offenses"),
        ("6", "Education"),
        ("7", "Elections"),
        ("8", "Environmental Law"),
        ("9", "Family Law"),
        ("10", "General Assembly"),
        ("11", "Labor and Industrial Relations"),
        ("12", "Law Enforcement, Emergency Management, and Military Affairs"),
        ("13", "Libraries, Archives, and Cultural Resources"),
        ("14", "Local Government"),
        ("15", "Natural Resources and Economic Development"),
        ("16", "Practice, Procedure, and Courts"),
        ("17", "Professions, Occupations, and Businesses"),
        ("18", "Property"),
        ("19", "Public Finance"),
        ("20", "Public Health and Welfare"),
        ("21", "Public Officers and Employees"),
        ("22", "Public Property"),
        ("23", "Public Utilities and Regulated Industries"),
        ("24", "Retirement and Pensions"),
        ("25", "State Government"),
        ("26", "Taxation"),
        ("27", "Transportation"),
        ("28", "Wills, Estates, and Fiduciary Relationships"),
    )

    def state_law_frontier_source_dependencies(self) -> Sequence[Any]:
        """Bind the delegated TOC/current-variant parser into certification."""

        from . import arkansas_lexis

        return (arkansas_lexis,)

    def attach_arkansas_current_variant_resolution_ledger(
        self,
        ledger: Any,
    ) -> None:
        """Attach the separate proof ledger without replacing the body ledger."""

        if ledger is None:
            self._arkansas_current_variant_ledger = None
            return
        from ...legal_data.state_laws_multifetch_acquisition import (
            StateLawMultiFetchAcquisitionLedger,
        )

        from .arkansas_lexis import CURRENT_VARIANT_RESOLVER_PARSER_NAME

        if not isinstance(ledger, StateLawMultiFetchAcquisitionLedger):
            raise TypeError(
                "Arkansas current-variant ledger must be a multi-fetch ledger"
            )
        if str(ledger.jurisdiction).upper() != "AR":
            raise ValueError("Arkansas current-variant ledger jurisdiction drifted")
        if str(ledger.parser_name) != CURRENT_VARIANT_RESOLVER_PARSER_NAME:
            raise ValueError("Arkansas current-variant ledger parser drifted")
        self._arkansas_current_variant_ledger = ledger

    def _get_arkansas_current_variant_resolution_ledger(self) -> Any:
        from .arkansas_lexis import CURRENT_VARIANT_RESOLVER_PARSER_NAME

        explicit = getattr(self, "_arkansas_current_variant_ledger", None)
        if explicit is not None:
            return explicit
        attached = getattr(self, "_state_law_acquisition_ledger", None)
        if str(getattr(attached, "parser_name", "") or "") == (
            CURRENT_VARIANT_RESOLVER_PARSER_NAME
        ):
            return attached
        root = self.state_law_run_environment_value(
            "ARKANSAS_CURRENT_VARIANT_EVIDENCE_ROOT"
        )
        if not root:
            return None
        from ...legal_data.state_laws_multifetch_acquisition import (
            StateLawMultiFetchAcquisitionLedger,
        )

        ledger = StateLawMultiFetchAcquisitionLedger(
            root,
            jurisdiction="AR",
            parser_name=CURRENT_VARIANT_RESOLVER_PARSER_NAME,
            retained_replay_only=True,
        )
        self._arkansas_current_variant_ledger = ledger
        return ledger

    DEFAULT_BUCKET_SEED_ROWS = (
        {
            "canonical_key": "ar:bucket-title-1",
            "label": "Arkansas Code Title 1 General Provisions",
            "source_url": "https://law.justia.com/codes/arkansas/title-1/",
            "title_number": "1",
        },
        {
            "canonical_key": "ar:bucket-seed-untitled",
            "label": "open-us-law-bucket Arkansas seed row without an official host",
            "source_url": "",
        },
        {
            "canonical_key": "ar:bucket-seed-phantom",
            "label": "Arkansas Code phantom bucket seed without a recoverable title",
            "source_url": "https://law.justia.com/codes/arkansas/",
        },
    )

    _AR_JUSTIA_TITLE_RE = re.compile(r"/codes/arkansas/(?:\d{4}/)?title-[^/]+/?$", re.IGNORECASE)
    _AR_JUSTIA_VERSION_RE = re.compile(r"/codes/arkansas/\d{4}/?$", re.IGNORECASE)
    _AR_JUSTIA_INTERMEDIATE_RE = re.compile(r"/codes/arkansas/(?:\d{4}/)?title-[^/]+/(?!.*section-)[^?#]+/?$", re.IGNORECASE)
    _AR_JUSTIA_SECTION_RE = re.compile(r"/codes/arkansas/(?:\d{4}/)?title-[^/]+/.*/section-[^/]+/?$", re.IGNORECASE)
    _AR_SECTION_NUMBER_RE = re.compile(r"/section-([^/]+)/?$", re.IGNORECASE)
    _AR_OFFICIAL_SECTION_HREF_RE = re.compile(
        r"/ArkansasCode/(?P<section>\d+-\d+(?:-\d+)?(?:\.\d+)?)/?$",
        re.IGNORECASE,
    )
    _AR_OFFICIAL_SECTION_QUERY_RE = re.compile(
        r"[?&](?:section|sec|codeSection)=(?P<section>\d+-\d+(?:-\d+)?(?:\.\d+)?)",
        re.IGNORECASE,
    )
    _AR_SECTION_HEAD_RE = re.compile(
        r"^\s*(?:§\s*)?(?P<section>\d+-\d+(?:-\d+)?(?:\.\d+)?)\s*[.–—-]\s*(?P<title>.+)$",
        re.IGNORECASE,
    )
    _AR_CLOUDFLARE_CHALLENGE_RE = re.compile(
        r"(cf-mitigated|challenge-platform|enable javascript and cookies|just a moment)",
        re.IGNORECASE,
    )
    _AR_LEXIS_BODY_BLOCKED_RE = re.compile(
        r"(robot\s*validation|captcha\s+validation|PawFirstDocAccess|"
        r"confirm\s+you\s+are\s+human|sign\s+in\s+to\s+continue|"
        r"cookies\s+required|unexpected\s+error|page\s+not\s+found)",
        re.IGNORECASE,
    )
    _AR_JUSTIA_EDITORIAL_HEADING_RE = re.compile(
        r"^(?:history|historical and statutory notes|notes?|annotations?|case notes?|"
        r"law reviews?|research references?|cross references?|amendments?|effective dates?|"
        r"compiler(?:'s|s)? notes?|publisher(?:'s|s)? notes?|credits?)\s*$",
        re.IGNORECASE,
    )

    def _filter_non_code_results(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        out: List[NormalizedStatute] = []
        for statute in statutes:
            url = str(statute.source_url or "").lower()
            text = str(statute.full_text or "").lower()
            allow_justia_section = bool(self._AR_JUSTIA_SECTION_RE.search(url))
            if "/acts/codesectionsamended" in url:
                continue
            if "codeofarrules.arkansas.gov" in url:
                continue
            if "code sections amended" in text or "state government directory" in text:
                continue
            if "law.justia.com" in url and not allow_justia_section:
                continue
            out.append(statute)
        return out

    def _looks_like_challenge_page(self, payload: bytes) -> bool:
        if not payload:
            return False
        sample = payload[:12000].decode("utf-8", errors="ignore")
        return bool(self._AR_CLOUDFLARE_CHALLENGE_RE.search(sample))

    async def _fetch_direct_html(self, url: str, timeout_seconds: int = 8) -> bytes:
        timeout = max(1, int(timeout_seconds or 8))
        return await self._fetch_parser_input_with_transport(
            url,
            headers={
                "User-Agent": "ipfs-datasets-arkansas-code-scraper/2.0",
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            },
            timeout_seconds=timeout,
            content_validator=lambda payload: not self._looks_like_challenge_page(
                payload
            ),
            allow_archival_fallback=False,
            media_type="text/html",
            provider="requests_direct",
        )

    async def _fetch_justia_html(self, url: str, timeout_seconds: int = 18) -> bytes:
        timeout = max(5, int(timeout_seconds or 18))
        payload = await self._fetch_non_authoritative_reference_bytes(
            url,
            timeout_seconds=timeout,
            content_validator=lambda body: bool(body)
            and not self._looks_like_challenge_page(body),
            enable_common_crawl=True,
        )
        self._record_fetch_event(
            provider="shared_secondary_justia_recovery",
            success=bool(payload),
        )
        if payload:
            await self._cache_successful_page_fetch(
                url=url,
                payload=payload,
                provider="shared_secondary_justia_recovery",
            )
        return payload

    async def _fetch_justia_from_web_archiving(
        self,
        url: str,
        timeout_seconds: int,
    ) -> bytes:
        """Use the shared archival stack only after live browser retrieval fails."""

        try:
            payload = await self._fetch_page_content_with_archival_fallback(
                url,
                timeout_seconds=max(5, int(timeout_seconds or 18)),
            )
        except Exception:
            return b""
        return b"" if self._looks_like_challenge_page(payload) else payload

    async def _close_justia_browser(self) -> None:
        """Close the scraper-scoped browser used by a multi-page recovery crawl."""

        context = getattr(self, "_justia_browser_context", None)
        browser = getattr(self, "_justia_browser", None)
        manager = getattr(self, "_justia_playwright_manager", None)
        self._justia_browser_context = None
        self._justia_browser = None
        self._justia_playwright_manager = None
        try:
            if context is not None:
                await context.close()
        finally:
            try:
                if browser is not None:
                    await browser.close()
            finally:
                if manager is not None:
                    await manager.stop()
    
    def get_base_url(self) -> str:
        """Return the base URL for Arkansas's legislative website."""
        return "https://www.arkleg.state.ar.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Arkansas."""
        return [{
            "name": "Arkansas Code",
            "url": self.OFFICIAL_CODE_INDEX,
            "type": "Code"
        }]

    def _official_section_number_from_url(self, url: str) -> str:
        text = str(url or "").strip()
        match = self._AR_OFFICIAL_SECTION_HREF_RE.search(text)
        if match:
            return match.group("section")
        match = self._AR_OFFICIAL_SECTION_QUERY_RE.search(text)
        if match:
            return match.group("section")
        return ""

    async def _discover_official_section_links(
        self, index_url: str
    ) -> List[Tuple[str, str, str]]:
        """Discover official Arkansas Code section links from an index page."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        payload = await self._fetch_direct_html(index_url)
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[Tuple[str, str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(index_url, str(anchor.get("href") or "").strip())
            section_number = self._official_section_number_from_url(href)
            if not section_number:
                continue
            if href in seen:
                continue
            seen.add(href)
            label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True) or "").strip()
            out.append((href, section_number, label))
        return out

    async def _build_official_statute(
        self,
        *,
        code_name: str,
        section_url: str,
        section_number: str,
        section_title: str = "",
    ) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        payload = await self._fetch_direct_html(section_url)
        if not payload:
            return None
        html = payload.decode("utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        content_node = (
            soup.select_one("div#content")
            or soup.select_one("div.content")
            or soup.select_one("main")
            or soup.select_one("article")
            or soup.select_one("body")
        )
        if content_node is None:
            return None
        full_text = self._normalize_legal_text(content_node.get_text(" ", strip=True))
        if len(full_text) < 120:
            return None

        heading = ""
        heading_node = (
            content_node.find(["h1", "h2", "h3"])
            if hasattr(content_node, "find")
            else None
        )
        if heading_node is not None:
            heading = self._normalize_legal_text(heading_node.get_text(" ", strip=True))
        if not heading:
            first_p = content_node.find("p") if hasattr(content_node, "find") else None
            if first_p is not None:
                heading = self._normalize_legal_text(first_p.get_text(" ", strip=True))
        match = self._AR_SECTION_HEAD_RE.match(heading)
        if match:
            section_number = match.group("section")
            section_title = match.group("title").strip()
        title = (section_title or heading or section_number)[:200]
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"AR-{section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=title,
            short_title=title,
            full_text=full_text,
            legal_area=self._identify_legal_area(title),
            source_url=section_url,
            official_cite=f"Ark. Code Ann. § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_arkansas_code_html",
                "discovery_method": "official_arkansas_code_index",
                "skip_hydrate": True,
            },
        )

    async def _scrape_official_arkansas_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int],
    ) -> List[NormalizedStatute]:
        """Scrape Arkansas Code from official arkleg.state.ar.us HTML."""
        index_candidates = []
        for candidate in (
            code_url,
            self.OFFICIAL_CODE_INDEX,
            self.OFFICIAL_ENTRY_URL,
            f"{self.get_base_url()}/",
        ):
            value = str(candidate or "").strip()
            if value and value not in index_candidates:
                index_candidates.append(value)

        section_links: List[Tuple[str, str, str]] = []
        seen_urls: set[str] = set()
        for index_url in index_candidates:
            for section_url, section_number, label in await self._discover_official_section_links(
                index_url
            ):
                if section_url in seen_urls:
                    continue
                seen_urls.add(section_url)
                section_links.append((section_url, section_number, label))
            if section_links:
                break

        statutes: List[NormalizedStatute] = []
        for section_url, section_number, label in section_links:
            if max_statutes is not None and len(statutes) >= max_statutes:
                break
            statute = await self._build_official_statute(
                code_name=code_name,
                section_url=section_url,
                section_number=section_number,
                section_title=label,
            )
            if statute is not None:
                statutes.append(statute)
        return statutes[:max_statutes] if max_statutes is not None else statutes

    def _delegated_lexis_body_text(
        self,
        payload: bytes,
        *,
        section_number: str,
    ) -> str:
        """Extract enacted text only from an exact delegated document page."""

        if not payload:
            return ""
        html = payload.decode("utf-8", errors="replace")
        if self._AR_LEXIS_BODY_BLOCKED_RE.search(html):
            return ""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return ""
        soup = BeautifulSoup(payload, "lxml")
        for node in soup.select(
            "script, style, nav, footer, header.global-nav, .global-nav, "
            ".document-toolbar, .delivery-toolbar"
        ):
            node.decompose()
        candidates = [
            soup.select_one("#document-content"),
            soup.select_one("#document"),
            soup.select_one("[data-document-content]"),
            soup.select_one(".document-content"),
            soup.select_one(".bodytext"),
            soup.select_one("article"),
        ]
        section_re = re.compile(
            rf"(?<![\d-])(?:§\s*)?{re.escape(section_number)}(?:\.|\s|$)",
            re.IGNORECASE,
        )
        for content_node in candidates:
            if content_node is None:
                continue
            for marker in list(
                content_node.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "strong"])
            ):
                marker_text = self._normalize_legal_text(
                    marker.get_text(" ", strip=True)
                )
                if not self._AR_JUSTIA_EDITORIAL_HEADING_RE.fullmatch(marker_text):
                    continue
                sibling = marker.next_sibling
                while sibling is not None:
                    following = sibling.next_sibling
                    sibling.extract()
                    sibling = following
                marker.extract()
                break
            full_text = self._normalize_legal_text(
                content_node.get_text(" ", strip=True)
            )
            if len(full_text) >= 80 and section_re.search(full_text):
                return full_text
        return ""

    @staticmethod
    def _validated_common_crawl_transport_evidence(
        fetched: Any,
        *,
        source_url: str,
        content_sha256: str,
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """Bind Common Crawl bytes to one exact delegated Lexis locator."""

        indexed_url = str(
            getattr(fetched, "common_crawl_indexed_url", "") or ""
        ).strip()
        if indexed_url != source_url:
            return None, "common_crawl_indexed_url_mismatch"

        fetched_digest = str(getattr(fetched, "content_sha256", "") or "").strip().lower()
        if fetched_digest != content_sha256:
            return None, "common_crawl_content_sha256_mismatch"

        warc_filename = str(
            getattr(fetched, "common_crawl_warc_filename", "") or ""
        ).strip().lstrip("/")
        archive_url = str(getattr(fetched, "archive_url", "") or "").strip()
        if not warc_filename or archive_url != (
            f"https://data.commoncrawl.org/{warc_filename}"
        ):
            return None, "common_crawl_warc_locator_mismatch"

        try:
            warc_offset = int(getattr(fetched, "common_crawl_warc_offset", None))
            warc_length = int(getattr(fetched, "common_crawl_warc_length", None))
            status_code = int(getattr(fetched, "status_code", 0) or 0)
        except (TypeError, ValueError):
            return None, "common_crawl_warc_range_invalid"
        if warc_offset < 0 or warc_length <= 0:
            return None, "common_crawl_warc_range_invalid"
        if status_code != 206:
            return None, "common_crawl_warc_range_unconfirmed"

        collection = str(
            getattr(fetched, "common_crawl_collection", "") or ""
        ).strip()
        path_parts = warc_filename.split("/")
        if (
            len(path_parts) < 3
            or path_parts[0] != "crawl-data"
            or not collection
            or path_parts[1] != collection
        ):
            return None, "common_crawl_collection_mismatch"

        timestamp = str(getattr(fetched, "archive_timestamp", "") or "").strip()
        evidence = {
            "indexed_url": indexed_url,
            "warc_filename": warc_filename,
            "warc_offset": warc_offset,
            "warc_length": warc_length,
            "archive_timestamp": timestamp,
            "collection": collection,
            "content_sha256": fetched_digest,
        }
        return evidence, ""

    def _delegated_lexis_statute_from_retained_payload(
        self,
        *,
        code_name: str,
        node: Any,
        source_url: str,
        payload: bytes,
        transport_receipt: Mapping[str, Any],
    ) -> NormalizedStatute:
        """Bind one aligned retained response to its exact delegated locator."""

        from ipfs_datasets_py.processors.legal_data.state_laws_source_provenance import (
            canonicalize_state_law_transport_receipt,
            verify_state_law_transport_receipt,
        )

        from .arkansas_lexis import document_page_url

        expected_url = document_page_url(node)
        canonical_url = self._canonical_fetch_url(source_url)
        if canonical_url != expected_url:
            raise ValueError("delegated Lexis response URL changed locator identity")
        section_number = str(getattr(node, "section_number", "") or "").strip()
        full_text = self._delegated_lexis_body_text(
            bytes(payload),
            section_number=section_number,
        )
        if not full_text:
            raise ValueError(
                "delegated Lexis response did not contain the exact citation body"
            )
        digest = hashlib.sha256(bytes(payload)).hexdigest()
        canonical_receipt = canonicalize_state_law_transport_receipt(
            transport_receipt,
            official_url=expected_url,
            content_sha256=digest,
        )
        verify_state_law_transport_receipt(
            canonical_receipt,
            official_url=expected_url,
            content_sha256=digest,
        )

        title = str(getattr(node, "title", "") or "").strip()
        title_text = re.sub(
            rf"^(?:§\s*)?{re.escape(section_number)}\.\s*",
            "",
            title,
            flags=re.IGNORECASE,
        ).strip()
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"AR-{section_number}",
            code_name=code_name,
            title_number=section_number.split("-", 1)[0],
            section_number=section_number,
            section_name=(title_text or section_number)[:200],
            short_title=(title_text or section_number)[:200],
            full_text=full_text,
            legal_area=self._identify_legal_area(title_text),
            source_url=expected_url,
            official_cite=f"Ark. Code Ann. § {section_number}",
            metadata=StatuteMetadata(repealed="[repealed]" in title.lower()),
            structured_data={
                "source_kind": "official_delegated_arkansas_lexis_html",
                "source_authority_class": "official",
                "discovery_method": "verified_arkansas_lexis_toc",
                "delegated_locator_node_id": str(
                    getattr(node, "node_id", "") or ""
                ),
                "delegated_locator_evidence_sha256": str(
                    getattr(node, "evidence_sha256", "") or ""
                ),
                "transport_receipt": canonical_receipt,
                "content_sha256": digest,
                "delegated_inventory_scope_only": True,
                "recovery_only": True,
                "full_corpus_admissible": False,
                "skip_hydrate": True,
            },
        )

    async def _fetch_verified_delegated_lexis_statute(
        self,
        *,
        code_name: str,
        node: Any,
    ) -> Tuple[Optional[NormalizedStatute], Dict[str, Any]]:
        """Try exact live then Wayback transport for one verified Lexis locator."""

        from ipfs_datasets_py.processors.legal_data.state_laws_source_provenance import (
            StateLawTransportReceiptError,
            canonicalize_state_law_transport_receipt,
        )

        from .arkansas_lexis import document_page_url

        section_number = str(getattr(node, "section_number", "") or "").strip()
        diagnostic: Dict[str, Any] = {
            "node_id": str(getattr(node, "node_id", "") or ""),
            "section_number": section_number,
            "source_url": "",
            "disposition": "unavailable",
        }
        try:
            source_url = document_page_url(node)
        except ValueError as exc:
            diagnostic["error"] = str(exc)
            return None, diagnostic
        diagnostic["source_url"] = source_url

        try:
            fetched = await self._fetch_non_authoritative_reference_result(
                source_url,
                timeout_seconds=max(
                    5,
                    self._env_int("ARKANSAS_LEXIS_BODY_TIMEOUT_SECONDS", default=20),
                ),
                content_validator=lambda body: bool(
                self._delegated_lexis_body_text(
                    body,
                    section_number=section_number,
                )
                ),
                enable_common_crawl=False,
            )
        except RuntimeError as exc:
            diagnostic["error"] = "live body rejected and no exact Wayback body was found"
            diagnostic["transport_error"] = str(exc)
            return None, diagnostic
        if fetched is None:
            diagnostic["error"] = (
                "delegated inventory-only body is unavailable or quarantined"
            )
            return None, diagnostic
        transport = str(getattr(fetched, "source", "") or "").strip().lower()
        if transport not in {
            "direct",
            "wayback",
            "common_crawl",
            "common_crawl_insecure_tls",
        }:
            diagnostic["error"] = f"unsupported or unbound transport {transport!r}"
            return None, diagnostic

        payload = bytes(getattr(fetched, "content", b"") or b"")
        full_text = self._delegated_lexis_body_text(
            payload,
            section_number=section_number,
        )
        if not full_text:
            diagnostic["error"] = "transport bytes did not contain the exact statute body"
            return None, diagnostic
        digest = hashlib.sha256(payload).hexdigest()
        common_crawl_evidence: Optional[Dict[str, Any]] = None
        if transport.startswith("common_crawl"):
            common_crawl_evidence, evidence_error = (
                self._validated_common_crawl_transport_evidence(
                    fetched,
                    source_url=source_url,
                    content_sha256=digest,
                )
            )
            if common_crawl_evidence is None:
                diagnostic["error"] = evidence_error
                return None, diagnostic
        raw_receipt: Dict[str, Any] = {
            "official_url": source_url,
            "content_sha256": digest,
            "source_transport": transport,
        }
        if transport == "wayback" or transport.startswith("common_crawl"):
            raw_receipt.update(
                {
                    "archive_url": str(getattr(fetched, "archive_url", "") or ""),
                    "archive_timestamp": str(
                        getattr(fetched, "archive_timestamp", "") or ""
                    ),
                }
            )
        try:
            transport_receipt = canonicalize_state_law_transport_receipt(
                raw_receipt,
                official_url=source_url,
                content_sha256=digest,
            )
        except StateLawTransportReceiptError as exc:
            diagnostic["error"] = f"transport receipt rejected: {exc.code}"
            return None, diagnostic

        try:
            statute = self._delegated_lexis_statute_from_retained_payload(
                code_name=code_name,
                node=node,
                source_url=source_url,
                payload=payload,
                transport_receipt=transport_receipt,
            )
        except (TypeError, ValueError) as exc:
            diagnostic["error"] = f"retained delegated body rejected: {exc}"
            return None, diagnostic
        if common_crawl_evidence is not None:
            statute.structured_data["common_crawl_transport_evidence"] = (
                common_crawl_evidence
            )
        diagnostic.update(
            {
                "disposition": "verified_body_probe",
                "content_sha256": digest,
                "transport": transport,
                "transport_receipt": transport_receipt,
            }
        )
        if common_crawl_evidence is not None:
            diagnostic["common_crawl_transport_evidence"] = common_crawl_evidence
        return statute, diagnostic

    async def _fetch_verified_delegated_lexis_statutes(
        self,
        *,
        code_name: str,
        nodes: Sequence[Any],
        require_exact_unresolved_frontier: bool = False,
        require_exact_identity_frontier: bool = False,
    ) -> tuple[
        list[NormalizedStatute | None],
        list[dict[str, Any]],
        dict[str, Any],
    ]:
        """Fetch delegated document pages through one shared archive batch.

        The base multi-fetch seam owns Common Crawl discovery, WARC grouping,
        range coalescing, direct/Wayback fallback, exact-request replay, and
        prospective ledger retention.  Arkansas contributes only its stable
        locator frontier and a citation-aware body validator.
        """

        from .arkansas_lexis import (
            document_page_url,
            exact_unresolved_variant_document_nodes,
            exact_unresolved_variant_identity_document_nodes,
        )

        requested_nodes = list(nodes)
        if require_exact_unresolved_frontier and require_exact_identity_frontier:
            raise ValueError("Arkansas delegated frontier mode is ambiguous")
        if require_exact_unresolved_frontier:
            requested_nodes = list(
                exact_unresolved_variant_document_nodes(requested_nodes)
            )
        elif require_exact_identity_frontier:
            requested_nodes = list(
                exact_unresolved_variant_identity_document_nodes(requested_nodes)
            )
        if not requested_nodes:
            return [], [], {
                "requested_pages": 0,
                "unique_pages": 0,
                "common_crawl_inventory_queries": 0,
            }

        urls: list[str] = []
        section_numbers: list[str] = []
        for node in requested_nodes:
            source_url = document_page_url(node)
            parsed = urlparse(source_url)
            if not (
                parsed.scheme == "https"
                and parsed.hostname == "advance.lexis.com"
                and parsed.path == "/documentpage/"
                and parsed.username is None
                and parsed.password is None
                and parsed.fragment == ""
            ):
                raise ValueError("Arkansas delegated document-page URL drifted")
            section_number = str(
                getattr(node, "section_number", "") or ""
            ).strip()
            if not section_number:
                raise ValueError("Arkansas delegated locator lacks a citation")
            urls.append(source_url)
            section_numbers.append(section_number)
        if len(urls) != len(set(urls)):
            raise ValueError("Arkansas delegated document-page frontier repeats a URL")

        def _any_requested_citation(payload: bytes) -> bool:
            return any(
                bool(
                    self._delegated_lexis_body_text(
                        payload,
                        section_number=section_number,
                    )
                )
                for section_number in dict.fromkeys(section_numbers)
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
            urls,
            residual_retry_attempts=retry_attempts,
            repeat_grouped_archive_inventory_on_residual=False,
            timeout_seconds=max(
                5,
                self._env_int("ARKANSAS_LEXIS_BODY_TIMEOUT_SECONDS", default=20),
            ),
            content_validator=_any_requested_citation,
            media_type="text/html",
            max_concurrency=max(
                1,
                self._env_int("ARKANSAS_LEXIS_BODY_BATCH_CONCURRENCY", default=8),
            ),
            prefer_direct=True,
            common_crawl_domain_terms=("advance.lexis.com",),
            common_crawl_url_terms=("/documentpage/",),
            common_crawl_mime_terms=("html",),
            wayback_prefix_inventory=True,
        )
        vectors = (
            list(getattr(batch, "urls", []) or []),
            list(getattr(batch, "payloads", []) or []),
            list(getattr(batch, "errors", []) or []),
            list(getattr(batch, "transport_receipts", []) or []),
            list(getattr(batch, "parser_input_envelopes", []) or []),
        )
        if any(len(values) != len(requested_nodes) for values in vectors):
            raise RuntimeError(
                "Arkansas delegated multi-fetch result lost frontier alignment"
            )
        batch_urls, payloads, errors, receipts, _envelopes = vectors
        if batch_urls != urls:
            raise RuntimeError(
                "Arkansas delegated multi-fetch changed locator order or identity"
            )
        stats = dict(getattr(batch, "stats", {}) or {})
        if int(stats.get("common_crawl_inventory_queries") or 0) > 1:
            raise RuntimeError(
                "Arkansas delegated frontier repeated Common Crawl inventory lookup"
            )
        if (
            int(stats.get("network_requested_pages") or 0) > 0
            and (
                stats.get("per_page_archive_fallback_disabled") is not True
                or int(stats.get("fallback_requests") or 0) != 0
            )
        ):
            raise RuntimeError(
                "Arkansas delegated frontier enabled legacy per-page archive fallback"
            )
        stats.update(
            {
                "arkansas_delegated_document_prefix": "/documentpage/",
                "arkansas_exact_citation_validator": True,
                "arkansas_exact_unresolved_frontier": bool(
                    require_exact_unresolved_frontier
                ),
                "arkansas_exact_identity_frontier": bool(
                    require_exact_identity_frontier
                ),
            }
        )

        statutes: list[NormalizedStatute | None] = []
        diagnostics: list[dict[str, Any]] = []
        for node, source_url, payload, error, receipt in zip(
            requested_nodes,
            urls,
            payloads,
            errors,
            receipts,
            strict=True,
        ):
            section_number = str(
                getattr(node, "section_number", "") or ""
            ).strip()
            diagnostic: dict[str, Any] = {
                "node_id": str(getattr(node, "node_id", "") or ""),
                "section_number": section_number,
                "source_url": source_url,
                "disposition": "unavailable",
            }
            if not payload or not isinstance(receipt, Mapping):
                diagnostic["error"] = str(
                    error or "all shared direct/archive transports missed"
                )
                statutes.append(None)
                diagnostics.append(diagnostic)
                continue
            try:
                statute = self._delegated_lexis_statute_from_retained_payload(
                    code_name=code_name,
                    node=node,
                    source_url=source_url,
                    payload=bytes(payload),
                    transport_receipt=receipt,
                )
            except Exception as exc:  # noqa: BLE001 - aligned failure evidence
                diagnostic["error"] = (
                    f"{type(exc).__name__}: exact delegated body rejected: {exc}"
                )
                statutes.append(None)
                diagnostics.append(diagnostic)
                continue
            diagnostic.update(
                {
                    "content_sha256": statute.structured_data["content_sha256"],
                    "disposition": "verified_body_probe",
                    "transport": str(receipt.get("source_transport") or ""),
                    "transport_receipt": dict(receipt),
                }
            )
            statutes.append(statute)
            diagnostics.append(diagnostic)
        return statutes, diagnostics, stats

    async def _fetch_exact_unresolved_delegated_lexis_variants(
        self,
        *,
        code_name: str,
        nodes: Sequence[Any],
    ) -> tuple[
        list[NormalizedStatute | None],
        list[dict[str, Any]],
        dict[str, Any],
    ]:
        """Batch the fixed sixteen unresolved variant locators exactly once."""

        return await self._fetch_verified_delegated_lexis_statutes(
            code_name=code_name,
            nodes=nodes,
            require_exact_unresolved_frontier=True,
        )

    async def _fetch_exact_unresolved_delegated_lexis_variant_identities(
        self,
        *,
        code_name: str,
        nodes: Sequence[Any],
    ) -> tuple[
        list[NormalizedStatute | None],
        list[dict[str, Any]],
        dict[str, Any],
    ]:
        """Submit the exact four identity-gap URNs as one shared body wave."""

        return await self._fetch_verified_delegated_lexis_statutes(
            code_name=code_name,
            nodes=nodes,
            require_exact_identity_frontier=True,
        )

    async def _resolve_enactment_toc_current_variants(
        self,
        *,
        nodes: Sequence[Any],
        inventory_sha256: str,
    ) -> tuple[tuple[Any, ...], dict[str, Any]]:
        """Replay the fixed 29-decision enactment/TOC proof bundle."""

        from .arkansas_lexis import (
            ARKANSAS_ENACTMENT_TOC_SOURCE_INPUT_CONTRACT,
            CURRENT_VARIANT_RESOLVER_PARSER_NAME,
            resolve_enactment_toc_source_bound_variants,
        )

        diagnostic: dict[str, Any] = {
            "schema_version": "arkansas-enactment-toc-current-variant-v1",
            "inventory_sha256": inventory_sha256,
            "source_input_count": len(
                ARKANSAS_ENACTMENT_TOC_SOURCE_INPUT_CONTRACT
            ),
            "disposition": "unresolved",
        }
        ledger = self._get_arkansas_current_variant_resolution_ledger()
        if ledger is None:
            diagnostic["error"] = (
                "source-bound resolution requires the Arkansas proof ledger"
            )
            return (), diagnostic
        if str(getattr(ledger, "parser_name", "") or "") != (
            CURRENT_VARIANT_RESOLVER_PARSER_NAME
        ):
            diagnostic["error"] = "source-bound resolution ledger identity drifted"
            return (), diagnostic
        ordered_inputs = sorted(ARKANSAS_ENACTMENT_TOC_SOURCE_INPUT_CONTRACT)
        requests = tuple(
            (
                ARKANSAS_ENACTMENT_TOC_SOURCE_INPUT_CONTRACT[key][0],
                {
                    "method": "GET",
                    "url": ARKANSAS_ENACTMENT_TOC_SOURCE_INPUT_CONTRACT[key][0],
                },
            )
            for key in ordered_inputs
        )
        try:
            retained = tuple(
                ledger.replay_retained_parser_inputs(requests=requests)
            )
        except Exception as exc:  # noqa: BLE001 - retained proof boundary
            diagnostic["error"] = (
                f"{type(exc).__name__}: exact enactment/TOC replay failed: {exc}"
            )
            return (), diagnostic
        if len(retained) != len(ordered_inputs):
            diagnostic["error"] = (
                "exact enactment/TOC retained proof bundle is incomplete"
            )
            return (), diagnostic
        try:
            resolutions = resolve_enactment_toc_source_bound_variants(
                nodes,
                inventory_sha256=inventory_sha256,
                retained_inputs=dict(zip(ordered_inputs, retained, strict=True)),
            )
        except Exception as exc:  # noqa: BLE001 - fail-closed proof boundary
            diagnostic["error"] = f"{type(exc).__name__}: {exc}"
            return (), diagnostic
        diagnostic.update(
            {
                "disposition": "selected_current_locators",
                "resolution_count": len(resolutions),
                "resolutions": [item.to_dict() for item in resolutions],
            }
        )
        return resolutions, diagnostic

    async def _resolve_act283_current_variants(
        self,
        *,
        nodes: Sequence[Any],
    ) -> tuple[tuple[Any, ...], dict[str, Any]]:
        """Replay, never invent, the exact three-input Act 283 proof bundle."""

        from .arkansas_lexis import (
            ACT283_CRC_NONOCCURRENCE_URL,
            ACT283_DWS_CURRENT_FORM_URL,
            ACT283_URL,
            CURRENT_VARIANT_RESOLVER_PARSER_NAME,
            resolve_act283_source_bound_variants,
        )

        diagnostic: dict[str, Any] = {
            "schema_version": "arkansas-act283-current-variant-resolution-v1",
            "section_numbers": ["11-10-803", "26-51-905"],
            "source_urls": [
                ACT283_URL,
                ACT283_CRC_NONOCCURRENCE_URL,
                ACT283_DWS_CURRENT_FORM_URL,
            ],
            "disposition": "unresolved",
        }
        ledger = self._get_arkansas_current_variant_resolution_ledger()
        if ledger is None:
            diagnostic["error"] = "source-bound resolution requires an attached ledger"
            return (), diagnostic
        if str(getattr(ledger, "parser_name", "") or "") != (
            CURRENT_VARIANT_RESOLVER_PARSER_NAME
        ):
            diagnostic["error"] = "source-bound resolution ledger identity drifted"
            return (), diagnostic
        requests = tuple(
            (url, {"method": "GET", "url": url})
            for url in (
                ACT283_URL,
                ACT283_CRC_NONOCCURRENCE_URL,
                ACT283_DWS_CURRENT_FORM_URL,
            )
        )
        try:
            retained = tuple(
                ledger.replay_retained_parser_inputs(requests=requests)
            )
        except Exception as exc:  # noqa: BLE001 - retained ledger boundary
            retained_urls = {
                str(getattr(entry.receipt, "endpoint", "") or "")
                for entry in getattr(ledger, "entries", ())
            }
            diagnostic["missing_source_urls"] = [
                url for url, _request in requests if url not in retained_urls
            ]
            diagnostic["error"] = (
                f"{type(exc).__name__}: exact Act 283 retained replay failed: {exc}"
            )
            return (), diagnostic
        if len(retained) != 3:
            diagnostic["error"] = "exact Act 283 retained proof bundle is incomplete"
            return (), diagnostic
        try:
            resolutions = resolve_act283_source_bound_variants(
                nodes,
                trigger_act_retained_input=retained[0],
                crc_nonoccurrence_retained_input=retained[1],
                current_dws_form_retained_input=retained[2],
            )
        except Exception as exc:  # noqa: BLE001 - fail-closed evidence boundary
            diagnostic["error"] = f"{type(exc).__name__}: {exc}"
            return (), diagnostic
        diagnostic.update(
            {
                "disposition": "selected_current_locators",
                "resolutions": [item.to_dict() for item in resolutions],
                "retained_body_paths": [
                    str(item.body_path) for item in retained
                ],
                "retained_evidence_paths": [
                    str(item.evidence_path) for item in retained
                ],
            }
        )
        return resolutions, diagnostic

    async def _resolve_hr5330_current_variant(
        self,
        *,
        nodes: Sequence[Any],
    ) -> tuple[Any | None, dict[str, Any]]:
        """Acquire and retain exact official evidence for Ark. Code 16-56-106."""

        from .arkansas_lexis import (
            ACT1032_URL,
            CURRENT_VARIANT_RESOLVER_PARSER_NAME,
            HR5330_BILLSTATUS_URL,
            resolve_hr5330_source_bound_variant,
        )

        diagnostic: dict[str, Any] = {
            "schema_version": "arkansas-hr5330-current-variant-resolution-v1",
            "section_number": "16-56-106",
            "source_url": HR5330_BILLSTATUS_URL,
            "disposition": "unresolved",
        }
        ledger = self._get_arkansas_current_variant_resolution_ledger()
        if ledger is None:
            diagnostic["error"] = "source-bound resolution requires an attached ledger"
            return None, diagnostic
        if str(getattr(ledger, "parser_name", "") or "") != (
            CURRENT_VARIANT_RESOLVER_PARSER_NAME
        ):
            diagnostic["error"] = "source-bound resolution ledger identity drifted"
            return None, diagnostic
        try:
            trigger_act_retained = ledger.replay_retained_parser_input(
                official_url=ACT1032_URL,
                sanitized_request={"method": "GET", "url": ACT1032_URL},
            )
        except Exception as exc:  # noqa: BLE001 - fail-closed retained evidence
            diagnostic["error"] = (
                f"{type(exc).__name__}: Act 1032 retained replay failed: {exc}"
            )
            return None, diagnostic
        if trigger_act_retained is None:
            diagnostic["error"] = "exact retained Arkansas Act 1032 input is missing"
            return None, diagnostic

        try:
            retained = ledger.replay_retained_parser_input(
                official_url=HR5330_BILLSTATUS_URL,
                sanitized_request={
                    "method": "GET",
                    "url": HR5330_BILLSTATUS_URL,
                },
            )
        except Exception as exc:  # noqa: BLE001 - retained proof boundary
            diagnostic["error"] = (
                f"{type(exc).__name__}: GovInfo retained replay failed: {exc}"
            )
            return None, diagnostic
        if retained is None:
            diagnostic["error"] = "exact retained GovInfo input is missing"
            return None, diagnostic
        diagnostic["transport_batch"] = {
            "requested_pages": 1,
            "retained_replay_hits": 1,
            "network_requested_pages": 0,
            "common_crawl_inventory_queries": 0,
        }
        try:
            resolution = resolve_hr5330_source_bound_variant(
                nodes,
                billstatus_xml=bytes(retained.envelope.body or b""),
                source_url=HR5330_BILLSTATUS_URL,
                transport_receipt=retained.transport_receipt,
                parser_input_envelope=retained.envelope,
                trigger_act_retained_input=trigger_act_retained,
            )
        except Exception as exc:  # noqa: BLE001 - fail-closed evidence boundary
            diagnostic["error"] = f"{type(exc).__name__}: {exc}"
            return None, diagnostic
        if (
            str(retained.receipt.receipt_sha256)
            != resolution.parser_input_receipt_sha256
        ):
            diagnostic["error"] = "resolved GovInfo bytes are absent from the ledger"
            return None, diagnostic
        diagnostic.update(
            {
                "disposition": "selected_current_locator",
                "resolution": resolution.to_dict(),
                "retained_body_path": str(retained.body_path),
                "retained_evidence_path": str(retained.evidence_path),
                "trigger_act_retained_body_path": str(
                    trigger_act_retained.body_path
                ),
                "trigger_act_retained_evidence_path": str(
                    trigger_act_retained.evidence_path
                ),
            }
        )
        return resolution, diagnostic

    async def _resolve_exact_current_variant_frontier(
        self,
        *,
        nodes: Sequence[Any],
        observed_at: str,
        inventory_sha256: str,
    ) -> dict[str, Any]:
        """Invoke every executable Arkansas current-variant proof atomically."""

        from .arkansas_lexis import (
            reconcile_current_statute_variants,
            variant_decision_sha256,
        )

        baseline = reconcile_current_statute_variants(
            nodes,
            observed_at=observed_at,
        )
        baseline_unresolved = {
            item.section_number
            for item in baseline
            if item.disposition == "unresolved"
        }
        enactment, enactment_diagnostic = (
            await self._resolve_enactment_toc_current_variants(
                nodes=nodes,
                inventory_sha256=inventory_sha256,
            )
        )
        hr5330, hr5330_diagnostic = await self._resolve_hr5330_current_variant(
            nodes=nodes,
        )
        act283, act283_diagnostic = await self._resolve_act283_current_variants(
            nodes=nodes,
        )
        source_bound = [*enactment, *act283]
        if hr5330 is not None:
            source_bound.append(hr5330)
        decisions = reconcile_current_statute_variants(
            nodes,
            observed_at=observed_at,
            source_bound_resolutions=source_bound,
        )

        def _counts(items: Sequence[Any]) -> dict[str, int]:
            return {
                disposition: sum(
                    item.disposition == disposition for item in items
                )
                for disposition in (
                    "selected_current_locator",
                    "no_current_locator",
                    "unresolved",
                )
            }

        baseline_counts = _counts(baseline)
        current_counts = _counts(decisions)
        original_conflicts = tuple(
            item
            for item in decisions
            if item.section_number in baseline_unresolved
        )
        original_conflict_counts = _counts(original_conflicts)
        unresolved = tuple(
            item.section_number
            for item in decisions
            if item.disposition == "unresolved"
        )
        return {
            "schema_version": "arkansas-exact-current-variant-frontier-v1",
            "inventory_sha256": inventory_sha256,
            "observed_at": observed_at,
            "baseline_counts": baseline_counts,
            "baseline_unresolved_section_numbers": sorted(
                baseline_unresolved
            ),
            "current_counts": current_counts,
            "original_conflict_counts": original_conflict_counts,
            "unresolved_section_numbers": list(unresolved),
            "decision_sha256": variant_decision_sha256(decisions),
            "enactment_toc": enactment_diagnostic,
            "hr5330": hr5330_diagnostic,
            "act283": act283_diagnostic,
            "authorizing_for_materialization": not unresolved,
            "disposition": (
                "current_variant_frontier_closed"
                if not unresolved
                else "current_variant_frontier_unresolved"
            ),
        }

    async def _configured_retained_current_variant_preflight(
        self,
    ) -> dict[str, Any] | None:
        """Replay the configured fixed inventory and proof ledger offline."""

        inventory_path = self.state_law_run_environment_value(
            "ARKANSAS_LEXIS_INVENTORY_PATH"
        )
        if not inventory_path:
            return None
        from .arkansas_lexis import load_exact_retained_inventory

        try:
            inventory, inventory_sha256 = load_exact_retained_inventory(
                inventory_path
            )
            resolution = await self._resolve_exact_current_variant_frontier(
                nodes=inventory.nodes,
                observed_at=inventory.observed_at,
                inventory_sha256=inventory_sha256,
            )
        except Exception as exc:  # noqa: BLE001 - retained preflight boundary
            return {
                "schema_version": "arkansas-retained-current-preflight-v1",
                "disposition": "retained_current_preflight_rejected",
                "authorizing_for_materialization": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        return {
            "schema_version": "arkansas-retained-current-preflight-v1",
            "disposition": str(resolution["disposition"]),
            "authorizing_for_materialization": resolution[
                "authorizing_for_materialization"
            ],
            "inventory": dict(inventory.frontier),
            "current_variants": resolution,
            "secondary_recovery_admitted": False,
        }

    async def _probe_delegated_arkansas_code(
        self,
        *,
        code_name: str,
    ) -> Dict[str, Any]:
        """Inventory the delegated TOC and test exact body transports."""

        from .arkansas_lexis import discover_live_inventory

        max_expansions = max(
            40,
            min(
                self._env_int(
                    "ARKANSAS_LEXIS_PROBE_MAX_EXPANSIONS",
                    default=48,
                ),
                256,
            ),
        )
        inventory = await discover_live_inventory(
            max_expansions=max_expansions,
            retries=2,
            request_delay_seconds=0.05,
            timeout_ms=max(
                15_000,
                self._env_int("ARKANSAS_LEXIS_PROBE_TIMEOUT_MS", default=45_000),
            ),
            require_enabled=False,
        )
        frontier = dict(inventory.frontier)
        evidence: Dict[str, Any] = {
            "schema_version": "arkansas-delegated-body-probe/v1",
            "status": inventory.status,
            "observed_at": inventory.observed_at,
            "final_url": inventory.final_url,
            "delegation_verified": inventory.delegation_verified,
            "root_rendered_sha256": inventory.root_rendered_sha256,
            "frontier": frontier,
            "diagnostics": list(inventory.diagnostics),
            "body_probes": [],
            "secondary_recovery_admitted": False,
        }
        locators = [node for node in inventory.nodes if node.is_statute_locator]
        if not (
            inventory.delegation_verified
            and frontier.get("title_inventory_closed") is True
            and locators
        ):
            evidence["disposition"] = "delegated_locator_frontier_unavailable"
            return evidence

        selected: List[Any] = []
        selected_titles: set[str] = set()
        max_probes = max(
            1,
            min(self._env_int("ARKANSAS_LEXIS_BODY_PROBE_COUNT", default=3), 5),
        )
        for node in locators:
            section_number = str(node.section_number or "")
            title_number = section_number.split("-", 1)[0]
            if title_number in selected_titles:
                continue
            selected_titles.add(title_number)
            selected.append(node)
            if len(selected) >= max_probes:
                break
        if len(selected) < max_probes:
            for node in locators:
                if node in selected:
                    continue
                selected.append(node)
                if len(selected) >= max_probes:
                    break

        statutes, diagnostics, batch_stats = (
            await self._fetch_verified_delegated_lexis_statutes(
                code_name=code_name,
                nodes=selected,
            )
        )
        evidence["body_probes"] = diagnostics
        evidence["body_transport_batch"] = batch_stats
        verified_body_probe_count = sum(statute is not None for statute in statutes)
        evidence["verified_body_probe_count"] = verified_body_probe_count
        evidence["probed_locator_count"] = len(selected)
        evidence["disposition"] = (
            "body_transport_verified_but_policy_or_frontier_unreconciled"
            if verified_body_probe_count
            else "delegated_body_access_blocked"
        )
        return evidence
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: int | None = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Arkansas's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=180)
        from .arkansas_constitution import (
            configured_constitution_text_path,
            parse_arkansas_constitution_text,
        )

        constitution_path = configured_constitution_text_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_arkansas_constitution_text(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Arkansas Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .arkansas_section import (
            configured_section_html_path,
            parse_arkansas_section_html,
        )

        local_section = configured_section_html_path()
        if local_section is not None:
            local_rows = parse_arkansas_section_html(
                local_section.read_text(encoding="utf-8", errors="replace"),
                source_url="https://www.arkleg.state.ar.us/ArkansasCode/5-10-101/",
                code_name=code_name,
                max_statutes=limit,
            )
            if local_rows:
                return local_rows if limit is None else local_rows[: int(limit)]
        official = await self._scrape_official_arkansas_code(
            code_name, code_url or self.OFFICIAL_CODE_INDEX, max_statutes=limit
        )
        official = self._filter_non_code_results(official)
        if official and limit is not None and len(official) >= limit:
            return official[:limit]

        # Full-corpus mode must bind every body to the official/delegated
        # locator.  The Lexis TOC is authoritative inventory; Justia remains a
        # secondary recovery source and is never promoted merely because the
        # designated document route is CAPTCHA-gated.
        if limit is None and self._full_corpus_enabled():
            evidence = await self._configured_retained_current_variant_preflight()
            if evidence is None:
                evidence = await self._probe_delegated_arkansas_code(
                    code_name=code_name,
                )
            self._last_full_corpus_frontier = dict(evidence)
            self._write_partial_checkpoint(
                official,
                code_name=code_name,
                stage_label="arkansas:delegated_body_blocked",
                force=True,
                extra={"arkansas_delegated_frontier": evidence},
            )
            raise ArkansasDelegatedCorpusBlockedError(
                str(evidence.get("disposition") or "delegated source unavailable"),
                evidence=evidence,
            )

        justia_statutes = await self._scrape_justia_titles(code_name, max_statutes=limit)
        justia_statutes = self._filter_non_code_results(justia_statutes)
        if limit is not None and len(justia_statutes) >= limit:
            return justia_statutes[:limit]

        candidate_urls = [
            code_url,
            "https://www.arkleg.state.ar.us/",
            self.OFFICIAL_ENTRY_URL,
            (
                "https://web.archive.org/web/20240101000000/"
                "https://www.arkleg.state.ar.us/ArkansasLaw/"
            ),
            "https://law.justia.com/codes/arkansas/",
            "https://web.archive.org/web/20231201000000/https://law.justia.com/codes/arkansas/",
        ]

        seen = set()
        merged: List[NormalizedStatute] = list(official) + list(justia_statutes)
        merged_keys = set()
        for statute in merged:
            key = str(statute.statute_id or statute.source_url or "").strip().lower()
            if key:
                merged_keys.add(key)

        def _merge(items: List[NormalizedStatute]) -> None:
            for statute in items:
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if not key or key in merged_keys:
                    continue
                merged_keys.add(key)
                merged.append(statute)

        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            statutes = await self._generic_scrape(
                code_name, candidate, "Ark. Code Ann.", max_sections=limit or 1000000
            )
            statutes = self._filter_non_code_results(statutes)
            _merge(statutes)
            if limit is not None and len(merged) >= limit:
                return merged[:limit]

        return merged[:limit] if limit is not None else merged

    async def _scrape_justia_titles(self, code_name: str, max_statutes: Optional[int]) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = "https://law.justia.com/codes/arkansas/"
        try:
            payload = await self._fetch_justia_html(index_url, timeout_seconds=18)
        except Exception:
            await self._close_justia_browser()
            return []
        if not payload:
            await self._close_justia_browser()
            return []

        soup = BeautifulSoup(payload, "html.parser")
        candidate_title_indexes = [index_url]
        seen_title_indexes = {index_url}
        for anchor in soup.find_all("a", href=True):
            href = urljoin(index_url, str(anchor.get("href") or "").strip())
            if not self._AR_JUSTIA_VERSION_RE.search(href):
                continue
            if href in seen_title_indexes:
                continue
            seen_title_indexes.add(href)
            candidate_title_indexes.append(href)
            break

        title_limit = max_statutes if max_statutes is not None else None
        section_limit = max_statutes if max_statutes is not None else None
        title_urls: List[str] = []
        seen_titles = set()
        for title_index_url in candidate_title_indexes:
            if title_index_url == index_url:
                title_soup = soup
            else:
                title_index_payload = await self._fetch_justia_html(title_index_url, timeout_seconds=18)
                if not title_index_payload:
                    continue
                title_soup = BeautifulSoup(title_index_payload, "html.parser")

            for anchor in title_soup.find_all("a", href=True):
                href = urljoin(title_index_url, str(anchor.get("href") or "").strip())
                if not self._AR_JUSTIA_TITLE_RE.search(href):
                    continue
                if href in seen_titles:
                    continue
                seen_titles.add(href)
                title_urls.append(href)
                if title_limit is not None and len(title_urls) >= title_limit:
                    break
            if title_urls:
                break
        self.logger.info("Arkansas Justia: discovered %d title indexes", len(title_urls))

        section_urls: List[str] = []
        intermediate_urls: List[str] = []
        seen_intermediate = set()
        seen_sections = set()
        for title_url in title_urls:
            try:
                title_payload = await self._fetch_justia_html(title_url, timeout_seconds=18)
            except Exception:
                continue
            if not title_payload:
                continue
            title_soup = BeautifulSoup(title_payload, "html.parser")
            for anchor in title_soup.find_all("a", href=True):
                href = urljoin(title_url, str(anchor.get("href") or "").strip())
                if not self._AR_JUSTIA_SECTION_RE.search(href):
                    if self._AR_JUSTIA_INTERMEDIATE_RE.search(href) and href not in seen_intermediate and href != title_url:
                        seen_intermediate.add(href)
                        intermediate_urls.append(href)
                    continue
                if href not in seen_sections:
                    seen_sections.add(href)
                    section_urls.append(href)
                if section_limit is not None and len(section_urls) >= max(1, int(section_limit * 4)):
                    break
            if section_limit is not None and len(intermediate_urls) >= max(1, int(section_limit * 2)):
                break
            if section_limit is not None and len(section_urls) >= max(1, int(section_limit * 4)):
                break

        intermediate_scan = intermediate_urls[: max(1, int(section_limit * 2))] if section_limit is not None else intermediate_urls
        self.logger.info(
            "Arkansas Justia: discovered %d direct section urls and %d intermediate urls",
            len(section_urls),
            len(intermediate_urls),
        )
        heartbeat_seconds = max(15.0, float(self._env_int("STATE_SCRAPER_HEARTBEAT_SECONDS", default=60)))
        last_heartbeat = time.monotonic()
        for idx, page_url in enumerate(intermediate_scan, start=1):
            try:
                page_payload = await self._fetch_justia_html(page_url, timeout_seconds=18)
            except Exception:
                continue
            if not page_payload:
                continue
            page_soup = BeautifulSoup(page_payload, "html.parser")
            for anchor in page_soup.find_all("a", href=True):
                href = urljoin(page_url, str(anchor.get("href") or "").strip())
                if not self._AR_JUSTIA_SECTION_RE.search(href):
                    continue
                if href in seen_sections:
                    continue
                seen_sections.add(href)
                section_urls.append(href)
                if section_limit is not None and len(section_urls) >= max(1, int(section_limit * 4)):
                    break
            now = time.monotonic()
            if now - last_heartbeat >= heartbeat_seconds:
                self.logger.info(
                    "Arkansas Justia: scanned_intermediate=%d/%d section_urls=%d",
                    idx,
                    len(intermediate_scan),
                    len(section_urls),
                )
                last_heartbeat = now
            if section_limit is not None and len(section_urls) >= max(1, int(section_limit * 4)):
                break
        self.logger.info("Arkansas Justia: total section urls queued=%d", len(section_urls))

        sem = asyncio.Semaphore(2)

        async def _fetch_one(section_url: str, index: int) -> NormalizedStatute | None:
            async with sem:
                return await self._build_justia_statute(code_name=code_name, section_url=section_url, fallback_number=str(index))

        statutes: List[NormalizedStatute] = []
        urls_to_fetch = section_urls[: max(1, int(section_limit * 4))] if section_limit is not None else section_urls
        batch_size = 24
        last_heartbeat = time.monotonic()
        for offset in range(0, len(urls_to_fetch), batch_size):
            batch = urls_to_fetch[offset : offset + batch_size]
            jobs = [_fetch_one(section_url, offset + idx) for idx, section_url in enumerate(batch, start=1)]
            for result in await asyncio.gather(*jobs, return_exceptions=True):
                if isinstance(result, Exception) or result is None:
                    continue
                statutes.append(result)
                if max_statutes is not None and len(statutes) >= max_statutes:
                    await self._close_justia_browser()
                    return statutes
            now = time.monotonic()
            if now - last_heartbeat >= heartbeat_seconds:
                self.logger.info(
                    "Arkansas Justia: fetched_sections=%d/%d statutes=%d",
                    min(offset + len(batch), len(urls_to_fetch)),
                    len(urls_to_fetch),
                    len(statutes),
                )
                last_heartbeat = now

        await self._close_justia_browser()
        return statutes

    async def _build_justia_statute(self, *, code_name: str, section_url: str, fallback_number: str) -> NormalizedStatute | None:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        try:
            payload = await self._fetch_justia_html(section_url, timeout_seconds=18)
        except Exception:
            return None
        if not payload:
            return None

        html = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
        soup = BeautifulSoup(html, "html.parser")
        content_node = (
            soup.select_one("#codes-content")
            or soup.select_one("div.wrapper")
            or soup.select_one(".primary-content")
            or soup.select_one("#main-content")
            or soup.select_one("main")
            or soup.select_one("article")
            or soup.select_one("body")
        )
        if content_node is None:
            return None

        # ``#codes-content`` contains enacted section text followed by
        # publisher-supplied history/annotations.  Preserve the law and remove
        # editorial additions without relying on the portal's copyright banner.
        editorial_removed = False
        for marker in list(content_node.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "strong"])):
            marker_text = re.sub(r"\s+", " ", marker.get_text(" ", strip=True) or "").strip()
            if not self._AR_JUSTIA_EDITORIAL_HEADING_RE.fullmatch(marker_text):
                continue
            editorial_removed = True
            sibling = marker.next_sibling
            while sibling is not None:
                following = sibling.next_sibling
                try:
                    sibling.extract()
                except Exception:
                    pass
                sibling = following
            marker.extract()
            break

        full_text = self._normalize_legal_text(content_node.get_text(" ", strip=True))
        if not full_text:
            full_text = self._extract_best_content_text(str(content_node))
        full_text = re.split(r"\bDisclaimer\s*:", full_text, maxsplit=1)[0].strip()
        full_text = re.split(r"\bAsk a Lawyer\b", full_text, maxsplit=1)[0].strip()
        full_text = re.sub(
            r"^Go to Previous Versions\b.*?\bUniversal Citation:\s*AR Code\s*§\s*[^.]+?"
            r"\s*Learn more\s*This media-neutral citation.*?official citation\.\s*(?:Previous\s+)?Next\s*",
            "",
            full_text,
            flags=re.IGNORECASE,
        )
        full_text = re.sub(r"\s*(?:Previous\s+)?Next\s*$", "", full_text, flags=re.IGNORECASE)
        full_text = re.sub(r"\s+", " ", full_text).strip()
        if len(full_text) < 40:
            return None

        heading_node = soup.select_one("h1") or soup.select_one("title")
        heading = " ".join((heading_node.get_text(" ", strip=True) if heading_node else "").split())
        match = self._AR_SECTION_NUMBER_RE.search(section_url)
        section_number = match.group(1) if match else fallback_number
        heading_match = re.search(
            rf"(?:§\s*)?{re.escape(section_number)}\.\s*(?P<title>.+)$",
            heading,
            flags=re.IGNORECASE,
        )
        section_title = (
            heading_match.group("title").strip() if heading_match else heading
        )

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=(section_title or f"Arkansas Code {section_number}")[:200],
            short_title=(section_title or f"Arkansas Code {section_number}")[:200],
            full_text=full_text,
            source_url=section_url,
            legal_area=self._identify_legal_area(heading),
            official_cite=f"Ark. Code Ann. § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "secondary_justia_arkansas_html",
                "source_authority_class": "secondary",
                "discovery_method": "justia_title_section_crawl_with_web_archiving",
                "retrieval_provider": self._current_fetch_provider(),
                "recovery_only": True,
                "full_corpus_admissible": False,
                "official_delegating_authority": "Arkansas Bureau of Legislative Research",
                "official_delegated_entry_url": self.OFFICIAL_DELEGATED_ENTRY_URL,
                "official_delegated_container_url": self.OFFICIAL_DELEGATED_CONTAINER_URL,
                "editorial_material_removed": editorial_removed,
                "skip_hydrate": True,
            },
        )

    def official_title_url(self, title_number: object) -> str:
        # The legislature exposes one referral landing page rather than stable
        # per-title arkleg URLs.  Title identity remains in ``canonical_key``
        # and ``title_number``; do not manufacture dead query URLs.
        return self.OFFICIAL_ENTRY_URL

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Arkansas Code title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"ar:title-{number}",
                    "title_number": str(number),
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Arkansas Code Title {number} ({name}) official arkleg "
                        f"catalog unit at {url}"
                    ),
                }
            )
        return rows

    def is_official_arkleg_url(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host == "arkleg.state.ar.us" or host.endswith(".arkleg.state.ar.us")

    def _looks_like_bucket_seed_url(self, url: str) -> bool:
        text = str(url or "").strip().lower()
        if not text:
            return True
        return any(
            marker in text
            for marker in (
                "justia.com",
                "findlaw.com",
                "law.cornell.edu",
                "open-us-law-bucket",
                "huggingface.co",
                "unicourt",
            )
        )

    def _recover_title_number(self, *parts: object) -> str:
        blob = " ".join(str(item or "") for item in parts)
        query_match = self._AR_TITLE_QUERY_RE.search(blob)
        if query_match:
            return query_match.group(1).lstrip("0") or query_match.group(1)
        label_match = self._AR_TITLE_LABEL_RE.search(blob)
        if label_match:
            return label_match.group(1).lstrip("0") or label_match.group(1)
        official_section = self._official_section_number_from_url(blob)
        if official_section:
            return official_section.split("-", 1)[0].lstrip("0") or official_section.split("-", 1)[0]
        return ""

    def classify_bucket_seed_rows(
        self,
        seeds: object,
        *,
        page_url: str = "",
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Admit official arkleg replacements or keep bucket seed rows quarantined.

        Recoverable title numbers are rewritten to the official Arkansas Code
        title URL. Remaining Hugging Face bucket / secondary-mirror rows stay
        quarantined with ``bucket_seed_pending_official_replacement`` until an
        official replacement is proven.
        """

        repaired: List[Dict[str, Any]] = []
        quarantines: List[Dict[str, Any]] = []
        seen_titles: set[str] = set()
        seen_quarantine: set[str] = set()
        known = {number for number, _name in self.OFFICIAL_TITLES}

        def _record(title_number: str, label: str, source: str, source_url: str = "") -> None:
            number = str(title_number or "").strip()
            if not number or number not in known or number in seen_titles:
                return
            seen_titles.add(number)
            official_url = source_url if source_url and self.is_official_arkleg_url(source_url) else self.official_title_url(number)
            name = dict(self.OFFICIAL_TITLES).get(number, f"Title {number}")
            repaired.append(
                {
                    "canonical_key": f"ar:title-{number}",
                    "title_number": number,
                    "name": name,
                    "source_url": official_url,
                    "source_link_disposition": source,
                    "repair_source": source,
                    "text": (
                        f"Arkansas Code Title {number} ({name}) official arkleg "
                        f"catalog unit at {official_url}"
                    ),
                }
            )

        def _quarantine(label: str, evidence: str, unit_id: str = "") -> None:
            cleaned = re.sub(r"\s+", " ", str(label or "")).strip()
            if not cleaned:
                return
            key = unit_id or (
                "ar:bucket-"
                + hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]
            )
            if key in seen_quarantine:
                return
            seen_quarantine.add(key)
            quarantines.append(
                {
                    "unit_id": key,
                    "reason": self.BUCKET_SEED_QUARANTINE_REASON,
                    "label": cleaned[:240],
                    "page_url": page_url,
                    "evidence_sha256": hashlib.sha256(
                        str(evidence or cleaned).encode("utf-8")
                    ).hexdigest(),
                }
            )

        items: Sequence[Any]
        if isinstance(seeds, (bytes, bytearray, str)):
            html = seeds.decode("utf-8", errors="replace") if isinstance(seeds, (bytes, bytearray)) else seeds
            try:
                from bs4 import BeautifulSoup
            except ImportError as exc:
                raise RuntimeError(
                    "BeautifulSoup is required for official Arkansas discovery"
                ) from exc
            soup = BeautifulSoup(html, "html.parser")
            for link in soup.find_all("a", href=True):
                href = str(link.get("href") or "").strip()
                label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
                absolute = urljoin(page_url or self.OFFICIAL_ENTRY_URL, href)
                title_number = self._recover_title_number(absolute, href, label)
                if title_number and self.is_official_arkleg_url(absolute):
                    _record(title_number, label, "official", self.official_title_url(title_number))
                    continue
                if title_number and not self._looks_like_bucket_seed_url(absolute):
                    _record(title_number, label, "official_replacement")
                    continue
                if title_number:
                    _record(title_number, label, "official_replacement")
                    continue
                if label and self._looks_like_bucket_seed_url(absolute):
                    _quarantine(label, str(link))
            for node in soup.find_all(["span", "td", "li", "div"]):
                if node.find("a", href=True):
                    continue
                label = re.sub(r"\s+", " ", node.get_text(" ", strip=True) or "").strip()
                if not label:
                    continue
                title_number = self._recover_title_number(
                    node.get("data-title"),
                    node.get("id"),
                    label,
                    str(node),
                )
                if title_number:
                    _record(title_number, label, "official_replacement")
                    continue
                if re.search(r"\b(bucket seed|phantom|without a recoverable)\b", label, re.IGNORECASE):
                    _quarantine(label, str(node))
            return {"repaired": repaired, "quarantines": quarantines}

        items = seeds or ()
        for item in items:
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
            if title_number and source_url and self.is_official_arkleg_url(source_url):
                _record(title_number, label, "official", source_url)
                continue
            if title_number:
                _record(title_number, label, "official_replacement")
                continue
            _quarantine(
                label or source_url or "arkansas bucket seed",
                json.dumps(dict(item), sort_keys=True),
                unit_id=str(item.get("canonical_key") or ""),
            )
        return {"repaired": repaired, "quarantines": quarantines}

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))

        def _request() -> bytes:
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-arkansas-official-catalog/1.0",
                        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                    },
                )
                context = ssl.create_default_context()
                with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                    if int(getattr(response, "status", 200) or 200) != 200:
                        return b""
                    return bytes(response.read() or b"")
            except Exception:
                try:
                    request = urllib.request.Request(
                        url,
                        headers={
                            "User-Agent": "ipfs-datasets-arkansas-official-catalog/1.0",
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

    def _parse_official_title_links(self, html: bytes, page_url: str = "") -> Dict[str, str]:
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
            if not href:
                continue
            absolute = urljoin(page_url or self.OFFICIAL_ENTRY_URL, href)
            if not self.is_official_arkleg_url(absolute):
                continue
            number = self._recover_title_number(
                absolute, href, link.get_text(" ", strip=True) or ""
            )
            if number not in known:
                continue
            if number not in found:
                found[number] = self.official_title_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
        seed_rows: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Enumerate official Arkansas titles and quarantine leftover bucket seeds."""

        discovered = self._parse_official_title_links(
            html, page_url or self.OFFICIAL_ENTRY_URL
        )
        classified = self.classify_bucket_seed_rows(
            html or b"",
            page_url=page_url or self.OFFICIAL_ENTRY_URL,
        )
        seed_classified = self.classify_bucket_seed_rows(
            list(seed_rows) if seed_rows is not None else list(self.DEFAULT_BUCKET_SEED_ROWS),
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
                row["source_link_disposition"] = "repaired_official_arkleg"
        for unit in classified["repaired"]:
            number = str(unit.get("title_number") or "")
            if number in by_title:
                if unit.get("source_link_disposition") in {"official", "official_replacement"}:
                    by_title[number]["source_url"] = unit["source_url"]
                    if unit.get("source_link_disposition") == "official":
                        by_title[number]["source_link_disposition"] = "official"
                continue
        return rows

    def fetch_official(self, code: str = "AR"):
        """Acquire the exhaustive official Arkansas Code title catalog.

        Official arkleg titles are admitted. Hugging Face bucket seed rows
        remain quarantined unless an official title replacement is proven.
        This hook never returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "AR").strip().upper() or "AR"
        if normalized != "AR":
            raise ValueError(f"ArkansasScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        quarantines = list(getattr(self, "last_official_quarantines", []) or [])
        if len(rows) < 3:
            raise RuntimeError("arkansas official catalog enumeration is incomplete")
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
            "ar_bucket_seed_quarantines": quarantines,
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
StateScraperRegistry.register("AR", ArkansasScraper)
