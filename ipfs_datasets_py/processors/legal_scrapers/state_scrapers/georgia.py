"""Scraper for Georgia state laws.

Official-source path walks the Georgia General Assembly HTML tree on
legis.ga.gov. Secondary Justia mirrors are never sole-admitted for full-corpus
certification unless explicitly allowed by environment flag.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry
from .retained_replay_network_guard import trusted_pdftotext_executable


class GeorgiaFullCorpusIncompleteError(RuntimeError):
    """Georgia evidence cannot prove a fresh, exhaustive live-code frontier."""

    def __init__(
        self,
        reason: str,
        *,
        evidence: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.reason = str(reason)
        self.evidence = dict(evidence or {})
        super().__init__(f"Georgia full-corpus frontier is incomplete: {self.reason}")


class GeorgiaScraper(BaseStateScraper):
    """Scraper for Georgia state laws from https://www.legis.ga.gov."""

    OFFICIAL_DOMAIN = "www.legis.ga.gov"
    OFFICIAL_ENTRY_PATH = "/legislation/georgia-code"
    OFFICIAL_ENTRY_URL = "https://www.legis.ga.gov/legislation/georgia-code"
    MISSING_LINK_QUARANTINE_REASON = "missing_official_source_link"
    CONTAMINATED_BUCKET_REPLACEMENT_REASON = (
        "contaminated_bucket_replaced_from_official_clean_text"
    )
    NAVIGATION_FOOTER_MARKERS = (
        "skip to main",
        "skip to content",
        "skip to navigation",
        "privacy policy",
        "site map",
        "sitemap",
        "copyright ©",
        "footer navigation",
        "cookie policy",
        "terms of use",
    )
    _GA_TITLE_RE = re.compile(r"/legislation/georgia-code/title-([0-9A-Za-z-]+)/?$", re.IGNORECASE)
    _GA_TITLE_LABEL_RE = re.compile(r"\bTitle\s+([0-9]+[A-Za-z]?)\b", re.IGNORECASE)
    _GA_CHAPTER_RE = re.compile(
        r"/legislation/georgia-code/title-[0-9A-Za-z-]+/chapter-([0-9A-Za-z-]+)/?$",
        re.IGNORECASE,
    )
    _GA_SECTION_RE = re.compile(
        r"/legislation/georgia-code/title-[0-9A-Za-z-]+/chapter-[0-9A-Za-z-]+/"
        r"section-([0-9A-Za-z.-]+)/?$",
        re.IGNORECASE,
    )
    _GA_JUSTIA_SECTION_RE = re.compile(
        r"/codes/georgia/(?:\d{4}/)?title-[^/]+/.*/section-[^/]+/?$",
        re.IGNORECASE,
    )
    _GA_SECTION_NUMBER_RE = re.compile(r"/section-([^/]+)/?$", re.IGNORECASE)
    OFFICIAL_TITLES = (
        ("1", "General Provisions"),
        ("2", "Agriculture"),
        ("3", "Alcoholic Beverages"),
        ("4", "Animals"),
        ("5", "Appeal and Error"),
        ("6", "Aviation"),
        ("7", "Banking and Finance"),
        ("8", "Buildings and Housing"),
        ("9", "Civil Practice"),
        ("10", "Commerce and Trade"),
        ("11", "Commercial Code"),
        ("12", "Conservation and Natural Resources"),
        ("13", "Contracts"),
        ("14", "Corporations, Partnerships, and Associations"),
        ("15", "Courts"),
        ("16", "Crimes and Offenses"),
        ("17", "Criminal Procedure"),
        ("18", "Debtor and Creditor"),
        ("19", "Domestic Relations"),
        ("20", "Education"),
        ("21", "Elections"),
        ("22", "Eminent Domain"),
        ("23", "Equity"),
        ("24", "Evidence"),
        ("25", "Fire Protection and Safety"),
        ("26", "Food, Drugs, and Cosmetics"),
        ("27", "Game and Fish"),
        ("28", "General Assembly"),
        ("29", "Guardian and Ward"),
        ("30", "Handicapped Persons"),
        ("31", "Health"),
        ("32", "Highways, Bridges, and Ferries"),
        ("33", "Insurance"),
        ("34", "Labor and Industrial Relations"),
        ("35", "Law Enforcement Officers and Agencies"),
        ("36", "Local Government"),
        ("37", "Mental Health"),
        ("38", "Military, Emergency Management, and Veterans Affairs"),
        ("39", "Minors"),
        ("40", "Motor Vehicles and Traffic"),
        ("41", "Nuisances"),
        ("42", "Penal Institutions"),
        ("43", "Professions and Businesses"),
        ("44", "Property"),
        ("45", "Public Officers and Employees"),
        ("46", "Public Utilities and Public Transportation"),
        ("47", "Retirement and Pensions"),
        ("48", "Revenue and Taxation"),
        ("49", "Social Services"),
        ("50", "State Government"),
        ("51", "Torts"),
        ("52", "Waters of the State, Ports, and Watercraft"),
        ("53", "Wills, Trusts, and Administration of Estates"),
    )
    DEFAULT_CONTAMINATED_BUCKET_SEEDS = (
        {
            "canonical_key": "ga:bucket-title-1",
            "label": "Official Code of Georgia Title 1 General Provisions",
            "source_url": "https://law.justia.com/codes/georgia/title-1/",
            "title_number": "1",
            "text": (
                "Skip to main content Site Map Privacy Policy Copyright © "
                "Georgia General Assembly Footer navigation Title 1 General Provisions"
            ),
        },
        {
            "canonical_key": "ga:bucket-title-16",
            "label": "Official Code of Georgia Title 16 Crimes and Offenses",
            "source_url": "https://law.justia.com/codes/georgia/title-16/",
            "title_number": "16",
            "text": (
                "Skip to navigation Cookie Policy Footer navigation Copyright © "
                "Georgia Title 16 Crimes and Offenses sitemap"
            ),
        },
        {
            "canonical_key": "ga:bucket-contaminated-untitled",
            "label": "open-us-law-bucket Georgia seed row with navigation and footer contamination",
            "source_url": "",
            "text": "Skip to main content Privacy Policy Footer navigation Copyright ©",
        },
        {
            "canonical_key": "ga:bucket-absent-object",
            "label": "Absent contaminated Georgia v2026.07 bucket object without a recoverable official identifier",
            "source_url": "",
        },
    )

    def state_law_frontier_source_dependencies(self) -> Sequence[Any]:
        """Bind the archived body parser and strict closure implementation."""

        from . import (
            georgia_archive,
            georgia_archived_official,
            georgia_lexis,
            strict_frontier_closure,
        )

        return (
            georgia_archive,
            georgia_archived_official,
            georgia_lexis,
            strict_frontier_closure,
        )

    def get_base_url(self) -> str:
        """Return the base URL for Georgia's legislative website."""
        return "https://www.legis.ga.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Georgia."""
        return [
            {
                "name": "Official Code of Georgia",
                "url": f"{self.get_base_url()}/legislation/georgia-code",
                "type": "Code",
            }
        ]

    @staticmethod
    def _georgia_archived_exact_frontier(corpus: Any) -> Dict[str, Any]:
        """Project a verified manifest onto the shared exact-leaf contract."""

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            compute_frontier_digest,
        )

        receipt = corpus.receipt
        source_frontier = receipt.get("frontier")
        inventory = receipt.get("inventory")
        if not isinstance(source_frontier, Mapping) or not isinstance(
            inventory, Mapping
        ):
            raise GeorgiaFullCorpusIncompleteError(
                "the archived-official manifest lacks a verified frontier",
                evidence={"full_corpus_admissible": False},
            )
        disposition = {
            field: int(source_frontier.get(field) or 0)
            for field in (
                "discovered",
                "fetched",
                "excluded",
                "quarantined",
                "failed_final",
                "duplicates",
            )
        }
        algebra_closed = disposition["discovered"] == sum(
            disposition[field]
            for field in (
                "fetched",
                "excluded",
                "quarantined",
                "failed_final",
                "duplicates",
            )
        )
        if (
            source_frontier.get("closed") is not True
            or source_frontier.get("frontier_closed") is not True
            or not algebra_closed
            or disposition["fetched"] != len(corpus.statutes)
            or disposition["quarantined"]
            or disposition["failed_final"]
            or disposition["duplicates"]
        ):
            raise GeorgiaFullCorpusIncompleteError(
                "the archived-official source disposition does not close",
                evidence={
                    "disposition": disposition,
                    "full_corpus_admissible": False,
                },
            )
        inventory_frontier = inventory.get("frontier")
        if not isinstance(inventory_frontier, Mapping):
            raise GeorgiaFullCorpusIncompleteError(
                "the delegated locator inventory is missing",
                evidence={"full_corpus_admissible": False},
            )
        title_numbers = [
            str(value) for value in inventory_frontier.get("title_numbers") or []
        ]
        if title_numbers != [str(number) for number in range(1, 54)]:
            raise GeorgiaFullCorpusIncompleteError(
                "the delegated locator inventory is not the exact Title 1-53 set",
                evidence={
                    "full_corpus_admissible": False,
                    "title_numbers": title_numbers,
                },
            )
        frontier: Dict[str, Any] = {
            "algebra_closed": True,
            "archived_body_frontier_sha256": str(
                source_frontier.get("frontier_digest_sha256") or ""
            ),
            "bundle_closed": True,
            "closed": True,
            "disposition": disposition,
            "enumerator_closed": True,
            "expected_index_units": disposition["discovered"],
            "inventory_sha256": str(receipt.get("inventory_sha256") or ""),
            "manifest_sha256": str(corpus.manifest_sha256 or ""),
            "pagination_closed": True,
            "request_batch_count": 1,
            "schema_version": "georgia-archived-official-strict-frontier-v1",
            "scope_closed": True,
            "section_numbers_sha256": str(
                source_frontier.get("section_numbers_sha256") or ""
            ),
            "title_count": len(title_numbers),
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": disposition["discovered"],
        }
        required_digests = (
            frontier["archived_body_frontier_sha256"],
            frontier["inventory_sha256"],
            frontier["manifest_sha256"],
            frontier["section_numbers_sha256"],
        )
        if any(not re.fullmatch(r"[a-f0-9]{64}", value) for value in required_digests):
            raise GeorgiaFullCorpusIncompleteError(
                "the archived-official closure lacks an exact digest",
                evidence={"full_corpus_admissible": False},
            )
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return frontier

    def _bind_georgia_archived_inputs_to_ledger(
        self,
        corpus: Any,
        *,
        allow_retention: bool,
    ) -> None:
        """Bind or replay every verified body object under this scraper ledger."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            if allow_retention:
                return
            raise RuntimeError("Georgia retained replay requires an attached ledger")
        artifacts = corpus.receipt.get("artifacts")
        if not isinstance(artifacts, Sequence) or isinstance(
            artifacts, (str, bytes, bytearray)
        ):
            raise RuntimeError("Georgia verified manifest lacks body artifacts")
        manifest_root = Path(corpus.manifest_path).resolve().parent
        for position, artifact in enumerate(artifacts):
            if not isinstance(artifact, Mapping):
                raise RuntimeError(
                    f"Georgia archived artifact {position} is not an object"
                )
            official_url = self._canonical_fetch_url(
                str(artifact.get("official_url") or "")
            )
            digest = str(artifact.get("sha256") or "").strip().lower()
            relative_path = str(artifact.get("path") or "").strip()
            if (
                not official_url
                or not re.fullmatch(r"[a-f0-9]{64}", digest)
                or not relative_path
            ):
                raise RuntimeError(
                    f"Georgia archived artifact {position} lacks exact identity"
                )
            source_path = (manifest_root / relative_path).resolve()
            try:
                source_path.relative_to(manifest_root)
            except ValueError as exc:
                raise RuntimeError(
                    "Georgia archived body path escaped its manifest"
                ) from exc
            request = {"method": "GET", "url": official_url}
            retained = ledger.replay_retained_parser_input_file(
                official_url=official_url,
                sanitized_request=request,
            )
            if retained is None:
                retained = ledger.replay_retained_parser_input(
                    official_url=official_url,
                    sanitized_request=request,
                )
            if retained is None and allow_retention:
                from ipfs_datasets_py.processors.legal_data.state_laws_source_provenance import (
                    canonicalize_state_law_transport_receipt,
                )

                transport = canonicalize_state_law_transport_receipt(
                    artifact,
                    official_url=official_url,
                    content_sha256=digest,
                )
                retained = ledger.retain_parser_input_file(
                    official_url=official_url,
                    source_path=source_path,
                    transport_receipt=transport,
                    retrieved_at=str(artifact.get("fetched_at") or ""),
                    response_status=int(artifact.get("status_code") or 200),
                    media_type="text/html",
                    sanitized_request=request,
                )
            if retained is None:
                raise RuntimeError(
                    "Georgia retained replay is missing an exact body input: "
                    f"{official_url}"
                )
            content = retained.receipt.content
            if content is None or str(content.sha256).lower() != digest:
                raise RuntimeError(
                    "Georgia retained body digest changed on replay: "
                    f"{official_url}"
                )

    def _record_georgia_archived_observation(
        self,
        corpus: Any,
        *,
        code_name: str,
        record_primary: bool,
    ) -> Dict[str, Any]:
        frontier = self._georgia_archived_exact_frontier(corpus)
        inventory = corpus.receipt.get("inventory") or {}
        artifacts = list(corpus.receipt.get("artifacts") or [])
        official_urls = [
            str(row.get("official_url") or "")
            for row in artifacts
            if isinstance(row, Mapping)
        ]
        if not official_urls or any(not value for value in official_urls):
            raise RuntimeError("Georgia archived frontier lacks boundary locators")
        for statute in corpus.statutes:
            structured = dict(statute.structured_data or {})
            structured["content_sha256"] = str(
                structured.get("body_sha256") or ""
            )
            statute.structured_data = structured
        observation = {
            "boundary_first": official_urls[0],
            "boundary_last": official_urls[-1],
            "code_name": code_name,
            "frontier": frontier,
            "legal_as_of": str(inventory.get("edition_as_of") or ""),
            "manifest_path": str(corpus.manifest_path),
            "observed_at": str(inventory.get("observed_at") or ""),
        }
        setattr(
            self,
            (
                "_last_georgia_strict_observation"
                if record_primary
                else "_last_georgia_replayed_observation"
            ),
            observation,
        )
        return observation

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape Georgia code from the official General Assembly HTML tree first."""
        limit = max(1, int(max_statutes)) if max_statutes else None
        require_live_full_frontier = self._full_corpus_enabled() and limit is None
        from .georgia_constitution import (
            configured_constitution_html_path,
            parse_georgia_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        constitution_request = "constitution" in " ".join(
            (str(code_name or ""), str(code_url or ""))
        ).lower()
        if constitution_request and constitution_path is not None:
            constitution_rows = parse_georgia_constitution_html(
                constitution_path.read_text(encoding="utf-8", errors="replace"),
                code_name=code_name or "Georgia Constitution",
                max_statutes=limit,
            )
            return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .georgia_archived_official import (
            GeorgiaArchivedOfficialCorpusError,
            configured_georgia_archived_official_manifest_path,
            load_georgia_archived_official_corpus,
        )

        archived_official_manifest = configured_georgia_archived_official_manifest_path()
        if archived_official_manifest is not None:
            try:
                archived = load_georgia_archived_official_corpus(
                    archived_official_manifest,
                    code_name=code_name or "Official Code of Georgia Annotated",
                )
            except GeorgiaArchivedOfficialCorpusError as exc:
                if require_live_full_frontier:
                    raise GeorgiaFullCorpusIncompleteError(
                        "the configured archived-official body receipt failed verification",
                        evidence={
                            "archived_official_manifest": str(archived_official_manifest),
                            "archived_official_reason": exc.reason,
                            "full_corpus_admissible": False,
                            **exc.evidence,
                        },
                    ) from exc
                raise
            self._bind_georgia_archived_inputs_to_ledger(
                archived,
                allow_retention=True,
            )
            self._record_georgia_archived_observation(
                archived,
                code_name=code_name or "Official Code of Georgia Annotated",
                record_primary=True,
            )
            rows = list(archived.statutes)
            self._last_full_corpus_frontier = dict(archived.receipt.get("frontier") or {})
            self._last_full_corpus_frontier.update(
                {
                    "acquisition_method": "hash_bound_archived_official",
                    "inventory_sha256": archived.receipt.get("inventory_sha256"),
                    "manifest_sha256": archived.manifest_sha256,
                }
            )
            return rows if limit is None else rows[: int(limit)]
        from .georgia_title import (
            configured_title_text_paths,
            parse_configured_georgia_title,
        )

        title_paths = configured_title_text_paths()
        if title_paths:
            require_complete_title_inventory = require_live_full_frontier
            official_rows = parse_configured_georgia_title(
                code_name=code_name or "Official Code of Georgia Annotated",
                max_statutes=limit,
                paths=title_paths,
                require_complete_inventory=require_complete_title_inventory,
            )
            if require_live_full_frontier:
                raise GeorgiaFullCorpusIncompleteError(
                    "configured title dumps verify a local Title 1-53 inventory, "
                    "not a fresh and exhaustive live official frontier",
                    evidence={
                        "configured_title_inventory_complete": True,
                        "configured_title_inventory_count": len(self.OFFICIAL_TITLES),
                        "configured_statute_count": len(official_rows),
                        "fresh_live_frontier_verified": False,
                        "full_corpus_admissible": False,
                    },
                )
            return official_rows if limit is None else official_rows[: int(limit)]
        if not self._full_corpus_enabled():
            from .georgia_archive import parse_configured_georgia_archive

            recovered = parse_configured_georgia_archive(
                code_name=code_name,
                max_statutes=limit,
            )
            if recovered:
                return recovered if limit is None else recovered[: int(limit)]

        # The legacy General Assembly HTML-tree walker has no exhaustive live
        # manifest and may hydrate individual pages through cache/archive
        # recovery.  It remains useful for bounded probes, but an uncapped
        # full-corpus run must fail before that partial route can sole-admit.
        if require_live_full_frontier:
            raise GeorgiaFullCorpusIncompleteError(
                "the legacy General Assembly HTML route cannot prove a fresh "
                "exhaustive frontier; delegated Lexis discovery is bounded and "
                "document bodies remain access-gated",
                evidence={
                    "fresh_live_frontier_verified": False,
                    "full_corpus_admissible": False,
                },
            )

        official = await self._scrape_official_georgia_code(
            code_name=code_name,
            code_url=code_url,
            max_statutes=limit,
        )
        if official:
            return official[:limit] if limit is not None else official

        # Bounded recovery: official summary PDFs (not secondary mirrors).
        if not self._full_corpus_enabled() or self._env_enabled(
            "GEORGIA_SUMMARY_PDF_FALLBACK", default=False
        ):
            summary = await self._scrape_general_statute_summary_pdfs(code_name)
            if summary:
                return summary[:limit] if limit is not None else summary

        # Optional secondary Justia path — never sole-admit under full corpus.
        allow_justia = self._env_enabled("GEORGIA_JUSTIA_ENABLE", default=False) or self._env_enabled(
            "STATE_SCRAPER_GA_ALLOW_JUSTIA_FALLBACK", default=False
        )
        if allow_justia and not self._full_corpus_enabled():
            justia = await self._scrape_justia_year(
                code_name,
                year="2024",
                max_statutes=max(
                    10,
                    limit or self._bounded_return_threshold(160),
                ),
            )
            justia = self._filter_non_code_results(justia)
            if justia:
                return justia[:limit] if limit is not None else justia

        self.logger.warning(
            "Georgia official direct crawl returned no statutes; refusing secondary sole-admission"
        )
        return []

    @staticmethod
    def _env_enabled(name: str, default: bool = False) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    def _filter_non_code_results(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        out: List[NormalizedStatute] = []
        for statute in statutes:
            url = str(statute.source_url or "").lower()
            text = str(statute.full_text or "").lower()
            allow_justia_section = bool(self._GA_JUSTIA_SECTION_RE.search(url))
            allow_summary_pdf = url.endswith("25sumdoc.pdf") or "general-statutes-summary-pdf.pdf" in url
            allow_official_section = bool(self._GA_SECTION_RE.search(url))
            if any(
                hint in url
                for hint in [
                    "dds.georgia.gov",
                    "dol.georgia.gov",
                    "lexisnexis.com/hottopics/gacode",
                ]
            ):
                continue
            if "temporary error. please try again" in text or "complete the security check before continuing" in text:
                continue
            if "law.justia.com" in url and not allow_justia_section:
                continue
            if "legis.ga.gov" in url and not (
                allow_summary_pdf or allow_official_section or "/api/document/docs/" in url
            ):
                continue
            out.append(statute)
        return out

    _RECOVERY_FETCH_PROVIDERS = (
        "wayback",
        "archive_is",
        "common_crawl",
        "archival_fallback",
        "common_crawl_insecure_tls",
        "fetch_cache",
        "ipfs_page_cache",
        "durable_cache",
        "unified_api",
    )

    def _classify_html_transport(self, provider: str) -> Tuple[str, str]:
        token = str(provider or "").strip().lower()
        if any(marker in token for marker in self._RECOVERY_FETCH_PROVIDERS):
            return "recovery", "official_georgia_code_html_via_archive"
        return "official", "official_georgia_code_html"

    async def _fetch_official_ga_html(self, url: str, timeout_seconds: int = 18) -> str:
        from .georgia_archive import looks_like_georgia_spa_shell

        timeout = max(1, int(timeout_seconds or 18))
        payload = await self._fetch_parser_input_with_transport(
            url,
            headers={
                "User-Agent": "ipfs-datasets-georgia-code-scraper/3.0",
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            },
            timeout_seconds=timeout,
            content_validator=lambda body: not looks_like_georgia_spa_shell(
                body.decode("utf-8", errors="replace")
            ),
            allow_archival_fallback=True,
            media_type="text/html",
            provider="requests_direct",
        )
        return payload.decode("utf-8", errors="replace") if payload else ""

    async def _scrape_official_georgia_code(
        self,
        *,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int],
    ) -> List[NormalizedStatute]:
        index_url = code_url or f"{self.get_base_url()}/legislation/georgia-code"
        title_links = await self._discover_title_links(index_url)
        self.logger.info("Georgia official index: discovered %s title links", len(title_links))
        statutes: List[NormalizedStatute] = []

        for title_index, (title_url, title_label) in enumerate(title_links, start=1):
            if max_statutes is not None and len(statutes) >= max_statutes:
                break
            chapter_links = await self._discover_chapter_links(title_url)
            self.logger.info(
                "Georgia official index: title=%s index=%s/%s chapters=%s statutes_so_far=%s",
                title_label or title_url,
                title_index,
                len(title_links),
                len(chapter_links),
                len(statutes),
            )
            for chapter_url, chapter_label in chapter_links:
                if max_statutes is not None and len(statutes) >= max_statutes:
                    break
                section_links = await self._discover_section_links(chapter_url)
                for section_url, section_label in section_links:
                    if max_statutes is not None and len(statutes) >= max_statutes:
                        break
                    statute = await self._parse_section_page(
                        code_name=code_name,
                        section_url=section_url,
                        section_label=section_label,
                        title_label=title_label,
                        chapter_label=chapter_label,
                    )
                    if statute is not None:
                        statutes.append(statute)
        return statutes

    async def _discover_title_links(self, index_url: str) -> List[Tuple[str, str]]:
        return await self._discover_links(index_url, self._GA_TITLE_RE)

    async def _discover_chapter_links(self, title_url: str) -> List[Tuple[str, str]]:
        return await self._discover_links(title_url, self._GA_CHAPTER_RE)

    async def _discover_section_links(self, chapter_url: str) -> List[Tuple[str, str]]:
        return await self._discover_links(chapter_url, self._GA_SECTION_RE)

    async def _discover_links(self, page_url: str, pattern: re.Pattern[str]) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        html = await self._fetch_official_ga_html(page_url)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(page_url, str(anchor.get("href") or "").strip())
            if not pattern.search(href.rstrip("/")):
                continue
            normalized = href.rstrip("/") + "/"
            if normalized in seen:
                continue
            seen.add(normalized)
            label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True) or "").strip()
            out.append((normalized, label or normalized.rstrip("/").rsplit("/", 1)[-1]))
        return out

    async def _parse_section_page(
        self,
        *,
        code_name: str,
        section_url: str,
        section_label: str,
        title_label: str,
        chapter_label: str,
    ) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        html = await self._fetch_official_ga_html(section_url)
        if not html:
            return None
        provider = str(getattr(self, "_last_fetch_provider", "") or "")
        authority, source_kind = self._classify_html_transport(provider)
        from .georgia_archive import parse_georgia_archive_html

        recovered_rows = parse_georgia_archive_html(
            html, source_url=section_url, code_name=code_name, max_statutes=None
        )
        if recovered_rows:
            url_match = self._GA_SECTION_RE.search(section_url.rstrip("/"))
            wanted = str(url_match.group(1) if url_match else "").strip()
            if not wanted:
                label_match = re.search(
                    r"\b(\d+[A-Za-z]?-\d+[A-Za-z0-9.-]*)\b",
                    str(section_label or ""),
                )
                wanted = str(label_match.group(1) if label_match else "").strip()
            row = next(
                (
                    candidate
                    for candidate in recovered_rows
                    if str(candidate.section_number or "").strip() == wanted
                ),
                None,
            )
            if row is None:
                return None
            if authority == "official":
                data = dict(row.structured_data or {})
                data["source_authority_class"] = "official"
                data["source_kind"] = "official_georgia_code_html"
                data["discovery_method"] = "official_title_chapter_section_index"
                row.structured_data = data
            else:
                data = dict(row.structured_data or {})
                data["fetch_transport"] = provider or "archival_fallback"
                row.structured_data = data
            return row
        soup = BeautifulSoup(html, "html.parser")
        for node in soup(["script", "style", "noscript", "nav", "footer", "header"]):
            node.decompose()

        main = (
            soup.select_one("main")
            or soup.select_one("article")
            or soup.select_one(".statute-content")
            or soup.select_one("body")
        )
        if main is None:
            return None
        from .georgia_archive import strip_georgia_editorial_tail

        full_text = self._normalize_legal_text(
            strip_georgia_editorial_tail(main.get_text("\n", strip=True))
        )
        if len(full_text) < 80:
            return None
        if self._looks_contaminated(full_text):
            return None

        match = self._GA_SECTION_RE.search(section_url.rstrip("/"))
        section_number = match.group(1) if match else ""
        if not section_number:
            match = re.search(r"\b(\d+[A-Za-z]?-\d+[A-Za-z0-9.-]*)\b", section_label)
            section_number = match.group(1) if match else section_label
        section_number = str(section_number or "").strip()
        if not section_number:
            return None

        title_match = self._GA_TITLE_RE.search(section_url)
        chapter_match = self._GA_CHAPTER_RE.search(section_url)
        heading = self._normalize_legal_text(
            (soup.select_one("h1") or soup.select_one("h2") or soup.select_one("title") or main).get_text(
                " ", strip=True
            )
        )
        section_name = section_label or heading or f"Section {section_number}"

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            title_number=title_match.group(1) if title_match else None,
            title_name=title_label or None,
            chapter_number=chapter_match.group(1) if chapter_match else None,
            chapter_name=chapter_label or None,
            section_number=section_number,
            section_name=section_name[:200],
            short_title=section_name[:200],
            full_text=full_text,
            legal_area=self._identify_legal_area(section_name or chapter_label or title_label),
            source_url=section_url.rstrip("/") + "/",
            official_cite=f"Ga. Code Ann. § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": source_kind,
                "source_authority_class": authority,
                "fetch_transport": provider or "requests_direct",
                "discovery_method": "official_title_chapter_section_index",
                "skip_hydrate": True,
            },
        )

    async def _scrape_justia_year(self, code_name: str, year: str, max_statutes: int) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        year_url = f"https://law.justia.com/codes/georgia/{year}/"
        try:
            payload = await self._fetch_page_content_with_archival_fallback(year_url, timeout_seconds=40)
        except Exception:
            return []
        if not payload:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        section_urls: List[str] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(year_url, str(anchor.get("href") or "").strip())
            if not self._GA_JUSTIA_SECTION_RE.search(href):
                continue
            if href in seen:
                continue
            seen.add(href)
            section_urls.append(href)
            if len(section_urls) >= max(1, int(max_statutes) * 4):
                break

        statutes: List[NormalizedStatute] = []
        for index, section_url in enumerate(section_urls, start=1):
            statute = await self._build_justia_statute(
                code_name=code_name,
                section_url=section_url,
                fallback_number=str(index),
            )
            if statute is None:
                continue
            statutes.append(statute)
            if len(statutes) >= max_statutes:
                break
        return statutes

    async def _build_justia_statute(
        self, *, code_name: str, section_url: str, fallback_number: str
    ) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        try:
            payload = await self._fetch_page_content_with_archival_fallback(section_url, timeout_seconds=35)
        except Exception:
            return None
        if not payload:
            return None

        html = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
        soup = BeautifulSoup(html, "html.parser")
        content_node = soup.select_one("main") or soup.select_one("article") or soup.select_one("body")
        if content_node is None:
            return None

        full_text = self._extract_best_content_text(str(content_node))
        full_text = re.split(r"\bDisclaimer:\b", full_text, maxsplit=1)[0].strip()
        full_text = re.split(r"\bAsk a Lawyer\b", full_text, maxsplit=1)[0].strip()
        full_text = re.sub(r"\s+", " ", full_text).strip()
        if len(full_text) < 280:
            return None

        heading_node = soup.select_one("h1") or soup.select_one("title")
        heading = " ".join((heading_node.get_text(" ", strip=True) if heading_node else "").split())
        match = self._GA_SECTION_NUMBER_RE.search(section_url)
        section_number = match.group(1) if match else fallback_number

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=(heading or f"Georgia Code {section_number}")[:200],
            full_text=full_text,
            source_url=section_url,
            legal_area=self._identify_legal_area(heading),
            official_cite=f"Ga. Code Ann. § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={"source_kind": "secondary_justia_georgia"},
        )

    async def _scrape_general_statute_summary_pdfs(self, code_name: str) -> List[NormalizedStatute]:
        """Use official GA-hosted General Statutes summary PDFs as strict-safe fallback."""
        candidate_docs = [
            (
                "2025",
                "https://www.legis.ga.gov/api/document/docs/default-source/legislative-counsel-document-library/25sumdoc.pdf?sfvrsn=95973fc9_4",
            ),
            (
                "2024",
                "https://www.legis.ga.gov/api/document/docs/default-source/legislative-counsel-document-library/2024-general-statutes-summary-pdf.pdf?sfvrsn=38862f9_8",
            ),
        ]

        statutes: List[NormalizedStatute] = []
        for year, pdf_url in candidate_docs:
            text = ""
            for _ in range(2):
                text = await self._extract_pdf_text_summary(pdf_url)
                if len(text) >= 280:
                    break
            if len(text) < 280:
                continue

            statute = NormalizedStatute(
                state_code=self.state_code,
                state_name=self.state_name,
                statute_id=f"{code_name} § Summary-{year}",
                code_name=code_name,
                section_number=year,
                section_name=f"Summary of {year} General Statutes",
                full_text=text,
                legal_area="general",
                source_url=pdf_url,
                official_cite=f"Ga. Gen. Stat. Summary ({year})",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_georgia_summary_pdf",
                    "skip_hydrate": True,
                    "coverage_note": "summary_fallback_not_full_code_corpus",
                },
            )
            statutes.append(statute)

        if statutes:
            self.logger.info("Georgia summary PDF fallback: Scraped %s records", len(statutes))
        return statutes

    async def _extract_pdf_text_summary(self, pdf_url: str, max_chars: int = 12000) -> str:
        try:
            payload = await self._fetch_pdf_bytes_direct(pdf_url, timeout_seconds=45)
            if not payload:
                return ""
        except Exception as exc:
            self.logger.debug("Georgia PDF download failed for %s: %s", pdf_url, exc)
            return ""

        try:
            with tempfile.TemporaryDirectory(prefix="ga_sum_pdf_") as tmpdir:
                from pathlib import Path

                pdf_path = Path(tmpdir) / "summary.pdf"
                txt_path = Path(tmpdir) / "summary.txt"
                pdf_path.write_bytes(payload)

                result = subprocess.run(
                    [trusted_pdftotext_executable(), "-f", "1", "-l", "12", str(pdf_path), str(txt_path)],
                    capture_output=True,
                    text=True,
                    timeout=40,
                    check=False,
                )
                if int(result.returncode) != 0 or not txt_path.exists():
                    return ""

                text = txt_path.read_text(encoding="utf-8", errors="ignore")
                text = re.sub(r"\s+", " ", text).strip()
                return text[:max_chars]
        except Exception as exc:
            self.logger.debug("Georgia PDF extraction failed for %s: %s", pdf_url, exc)
            return ""

    async def _fetch_pdf_bytes_direct(self, url: str, timeout_seconds: int = 45) -> bytes:
        timeout = max(5, int(timeout_seconds or 45))
        return await self._fetch_parser_input_with_transport(
            url,
            headers={
                "User-Agent": "ipfs-datasets-georgia-code-scraper/3.0",
                "Accept": "application/pdf,*/*;q=0.8",
            },
            timeout_seconds=timeout,
            content_validator=lambda payload: payload.startswith(b"%PDF"),
            allow_archival_fallback=True,
            media_type="application/pdf",
            provider="requests_direct",
        )

    def official_title_url(self, title_number: object) -> str:
        number = str(title_number or "").strip()
        return f"{self.get_base_url()}/legislation/georgia-code/title-{number}"

    def official_section_url(self, section_number: str) -> str:
        section = str(section_number or "").strip()
        parts = section.split("-")
        title = parts[0] if parts else ""
        chapter = parts[1] if len(parts) > 1 else "1"
        return (
            f"{self.get_base_url()}/legislation/georgia-code/title-{title}"
            f"/chapter-{chapter}/section-{section}"
        )

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Code of Georgia title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "body_admissible": False,
                    "canonical_key": f"ga:title-{number}",
                    "full_corpus_admissible": False,
                    "title_number": number,
                    "name": name,
                    "source_scope": "title_inventory",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Official Code of Georgia Title {number} ({name}) official "
                        f"General Assembly catalog unit at {url}"
                    ),
                }
            )
        return rows

    def is_official_ga_url(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host == self.OFFICIAL_DOMAIN or host.endswith(".legis.ga.gov")

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

    def _looks_contaminated(self, text: str) -> bool:
        lowered = re.sub(r"\s+", " ", str(text or "")).strip().lower()
        if not lowered:
            return False
        return any(marker in lowered for marker in self.NAVIGATION_FOOTER_MARKERS)

    def _official_clean_text(self, title_number: str, name: str, source_url: str) -> str:
        return (
            f"Official Code of Georgia Title {title_number} ({name}) official "
            f"clean statutory catalog unit at {source_url}"
        )

    def repair_or_type_missing_source_link(
        self,
        statute: NormalizedStatute,
    ) -> NormalizedStatute:
        """Attach an official legis.ga.gov URL or type a linkless row."""

        structured = dict(statute.structured_data or {})
        source_url = str(statute.source_url or "").strip()
        if source_url and self.is_official_ga_url(source_url):
            structured.setdefault("source_link_disposition", "official")
            statute.structured_data = structured
            return statute

        section_number = str(statute.section_number or "").strip()
        if section_number:
            repaired = self.official_section_url(section_number)
            statute.source_url = repaired
            structured["source_kind"] = "unverified_georgia_body_with_repaired_locator"
            structured["source_authority_class"] = "unverified"
            structured["full_corpus_admissible"] = False
            structured["official_source"] = False
            structured["source_link_disposition"] = "repaired_official_galeg"
            structured["previous_source_url"] = source_url or None
            statute.structured_data = structured
            return statute

        structured["source_link_disposition"] = "typed_quarantine"
        structured["quarantine_reason"] = self.MISSING_LINK_QUARANTINE_REASON
        statute.structured_data = structured
        return statute

    def _recover_title_number(self, *parts: object) -> str:
        blob = " ".join(str(item or "") for item in parts)
        path_match = self._GA_TITLE_RE.search(blob)
        if path_match:
            return path_match.group(1).lstrip("0") or path_match.group(1)
        label_match = self._GA_TITLE_LABEL_RE.search(blob)
        if label_match:
            return label_match.group(1).lstrip("0") or label_match.group(1)
        return ""

    def replace_contaminated_bucket_object(
        self,
        seeds: object,
        *,
        page_url: str = "",
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Replace the absent contaminated GA bucket object with official clean text.

        Recoverable title numbers are rewritten to official legis.ga.gov URLs
        and retained as navigation/footer-free title inventory, not statute
        bodies.
        Unrecoverable contaminated or linkless bucket seeds stay quarantined.
        """

        replaced: List[Dict[str, Any]] = []
        quarantines: List[Dict[str, Any]] = []
        seen_titles: set[str] = set()
        seen_quarantine: set[str] = set()
        known = {number for number, _name in self.OFFICIAL_TITLES}
        names = dict(self.OFFICIAL_TITLES)

        def _record(title_number: str, label: str, source: str, source_url: str = "") -> None:
            number = str(title_number or "").strip()
            if not number or number not in known or number in seen_titles:
                return
            seen_titles.add(number)
            official_url = (
                source_url
                if source_url and self.is_official_ga_url(source_url)
                else self.official_title_url(number)
            )
            name = names.get(number, f"Title {number}")
            replaced.append(
                {
                    "body_admissible": False,
                    "canonical_key": f"ga:title-{number}",
                    "full_corpus_admissible": False,
                    "title_number": number,
                    "name": name,
                    "source_scope": "title_inventory",
                    "source_url": official_url,
                    "source_link_disposition": source,
                    "repair_source": source,
                    "contaminated_replaced": True,
                    "text": self._official_clean_text(number, name, official_url),
                }
            )

        def _quarantine(label: str, evidence: str, unit_id: str = "") -> None:
            cleaned = re.sub(r"\s+", " ", str(label or "")).strip()
            if not cleaned:
                return
            key = unit_id or (
                "ga:bucket-"
                + hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]
            )
            if key in seen_quarantine:
                return
            seen_quarantine.add(key)
            quarantines.append(
                {
                    "unit_id": key,
                    "reason": self.CONTAMINATED_BUCKET_REPLACEMENT_REASON,
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
                    "BeautifulSoup is required for official Georgia discovery"
                ) from exc
            soup = BeautifulSoup(html, "html.parser")
            for link in soup.find_all("a", href=True):
                href = str(link.get("href") or "").strip()
                label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
                absolute = urljoin(page_url or self.OFFICIAL_ENTRY_URL, href)
                title_number = self._recover_title_number(absolute, href, label)
                if title_number and self.is_official_ga_url(absolute):
                    _record(title_number, label, "official", self.official_title_url(title_number))
                    continue
                if title_number:
                    _record(title_number, label, "official_replacement")
                    continue
                if label and (
                    self._looks_like_bucket_seed_url(absolute) or self._looks_contaminated(label)
                ):
                    _quarantine(label, str(link))
            for node in soup.find_all(["span", "td", "li", "div", "nav", "footer"]):
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
                if re.search(
                    r"\b(bucket seed|phantom|without a recoverable|contaminated)\b",
                    label,
                    re.IGNORECASE,
                ) or self._looks_contaminated(label):
                    _quarantine(label, str(node))
            return {"replaced": replaced, "quarantines": quarantines}

        items: Sequence[Any] = seeds or ()
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
            if title_number and source_url and self.is_official_ga_url(source_url):
                _record(title_number, label, "official", source_url)
                continue
            if title_number:
                _record(title_number, label, "official_replacement")
                continue
            _quarantine(
                label or source_url or "georgia contaminated bucket seed",
                json.dumps(dict(item), sort_keys=True),
                unit_id=str(item.get("canonical_key") or ""),
            )
        return {"replaced": replaced, "quarantines": quarantines}

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))

        def _request() -> bytes:
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-georgia-official-catalog/1.0",
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
                            "User-Agent": "ipfs-datasets-georgia-official-catalog/1.0",
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

        payload = _request()
        if payload:
            return payload
        return self._official_http_get_via_archive(url, timeout_seconds=timeout)

    def _official_http_get_via_archive(self, url: str, timeout_seconds: int = 12) -> bytes:
        """Recover an official legis.ga.gov page through Wayback. Not a Justia path."""

        if not self.is_official_ga_url(url):
            return b""
        timeout = max(5, int(timeout_seconds or 12))
        wayback = f"https://web.archive.org/web/2026/{url}"
        try:
            request = urllib.request.Request(
                wayback,
                headers={
                    "User-Agent": "ipfs-datasets-georgia-official-catalog/1.0",
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                },
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if int(getattr(response, "status", 200) or 200) != 200:
                    return b""
                return bytes(response.read() or b"")
        except Exception:
            return b""

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
            number = self._recover_title_number(
                absolute, href, link.get_text(" ", strip=True) or ""
            )
            if number not in known:
                continue
            if number not in found and self.is_official_ga_url(absolute):
                found[number] = self.official_title_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
        seed_rows: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Enumerate official Georgia titles and replace contaminated bucket seeds."""

        discovered = self._parse_official_title_links(
            html, page_url or self.OFFICIAL_ENTRY_URL
        )
        classified = self.replace_contaminated_bucket_object(
            html or b"",
            page_url=page_url or self.OFFICIAL_ENTRY_URL,
        )
        seed_classified = self.replace_contaminated_bucket_object(
            list(seed_rows) if seed_rows is not None else list(self.DEFAULT_CONTAMINATED_BUCKET_SEEDS),
            page_url=page_url or self.OFFICIAL_ENTRY_URL,
        )
        classified["replaced"].extend(seed_classified["replaced"])
        classified["quarantines"].extend(seed_classified["quarantines"])
        self.last_official_replacements = list(classified["replaced"])
        self.last_official_quarantines = list(classified["quarantines"])

        rows = self.official_title_catalog()
        by_title = {str(row["title_number"]): row for row in rows}
        for row in rows:
            live_url = discovered.get(str(row["title_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_galeg"
            row["text"] = self._official_clean_text(
                str(row["title_number"]), str(row["name"]), str(row["source_url"])
            )
            row["contaminated_replaced"] = True
        for unit in classified["replaced"]:
            number = str(unit.get("title_number") or "")
            if number not in by_title:
                continue
            if unit.get("source_link_disposition") in {"official", "official_replacement"}:
                by_title[number]["source_url"] = unit["source_url"]
                by_title[number]["text"] = unit["text"]
                if unit.get("source_link_disposition") == "official":
                    by_title[number]["source_link_disposition"] = "official"
                elif by_title[number]["source_link_disposition"] != "official":
                    by_title[number]["source_link_disposition"] = "official_replacement"
        return rows

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection: Mapping[str, Any],
    ) -> Optional[Path]:
        """Reload retained official bodies and seal exact output parity."""

        first = getattr(self, "_last_georgia_strict_observation", None)
        if not isinstance(first, Mapping):
            raise RuntimeError(
                "Georgia verified body frontier was not observed before output"
            )
        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError(
                "Georgia frontier closure requires an attached acquisition ledger"
            )
        refresh = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh):
            refresh()

        from .georgia_archived_official import (
            GeorgiaArchivedOfficialCorpusError,
            load_georgia_archived_official_corpus,
        )

        manifest_path = str(first.get("manifest_path") or "").strip()
        if not manifest_path:
            raise RuntimeError("Georgia strict observation lacks its manifest path")
        try:
            replayed = load_georgia_archived_official_corpus(
                manifest_path,
                code_name=str(
                    first.get("code_name")
                    or "Official Code of Georgia Annotated"
                ),
            )
        except GeorgiaArchivedOfficialCorpusError as exc:
            raise RuntimeError(
                f"Georgia retained archived-official replay failed: {exc.reason}"
            ) from exc
        self._bind_georgia_archived_inputs_to_ledger(
            replayed,
            allow_retention=False,
        )
        replay = self._record_georgia_archived_observation(
            replayed,
            code_name=str(
                first.get("code_name") or "Official Code of Georgia Annotated"
            ),
            record_primary=False,
        )
        first_frontier = first.get("frontier")
        replayed_frontier = replay.get("frontier")
        if not isinstance(first_frontier, Mapping) or not isinstance(
            replayed_frontier, Mapping
        ):
            raise RuntimeError("Georgia exact frontier observations are incomplete")

        from .strict_frontier_closure import retain_exact_state_frontier_closure

        return retain_exact_state_frontier_closure(
            self,
            canonical_output_projection=canonical_output_projection,
            first_frontier=first_frontier,
            replayed_frontier=replayed_frontier,
            replay_rows=list(replayed.statutes),
            jurisdiction="GA",
            source_domain=self.OFFICIAL_DOMAIN,
            official_source_url=self.OFFICIAL_ENTRY_URL,
            observed_at=str(first.get("observed_at") or ""),
            legal_as_of=str(first.get("legal_as_of") or ""),
            boundary_first=str(first.get("boundary_first") or ""),
            boundary_last=str(first.get("boundary_last") or ""),
            bundle_total=int(first_frontier.get("request_batch_count") or 0),
            pagination_total=int(first_frontier.get("title_count") or 0),
            transport={
                "fixture": False,
                "kind": "shared_archive_aware_plural_archived_html",
                "retained_replay_network_requests": 0,
                "synthetic": False,
            },
        )

    def fetch_official(self, code: str = "GA"):
        """Acquire verified Georgia statute bodies, never title-catalog labels.

        ``enumerate_official_catalog`` remains available for inventory repair,
        but its short title labels are not statutory text.  This full-corpus
        hook therefore requires a closed, hash-bound archived-official body
        manifest and fails closed when one is not configured.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "GA").strip().upper() or "GA"
        if normalized != "GA":
            raise ValueError(f"GeorgiaScraper cannot acquire {normalized}")
        from .georgia_archived_official import (
            GeorgiaArchivedOfficialCorpusError,
            configured_georgia_archived_official_manifest_path,
            load_georgia_archived_official_corpus,
        )

        manifest_path = configured_georgia_archived_official_manifest_path()
        if manifest_path is None:
            raise GeorgiaFullCorpusIncompleteError(
                "the title catalog is inventory-only; a verified archived-official "
                "statutory-body manifest is required",
                evidence={
                    "body_frontier_closed": False,
                    "full_corpus_admissible": False,
                    "title_catalog_body_admissible": False,
                },
            )
        try:
            corpus = load_georgia_archived_official_corpus(manifest_path)
        except GeorgiaArchivedOfficialCorpusError as exc:
            raise GeorgiaFullCorpusIncompleteError(
                "the configured archived-official body receipt failed verification",
                evidence={
                    "archived_official_manifest": str(manifest_path),
                    "archived_official_reason": exc.reason,
                    "full_corpus_admissible": False,
                    **exc.evidence,
                },
            ) from exc
        rows: List[Dict[str, Any]] = []
        for statute in corpus.statutes:
            row = statute.to_dict()
            section = str(statute.section_number or "").strip()
            row.update(
                {
                    "canonical_key": f"ga:section-{section}",
                    "logical_key": f"ga:section-{section}",
                    "text": statute.full_text,
                    "url": statute.source_url,
                }
            )
            rows.append(row)
        if not rows:
            raise GeorgiaFullCorpusIncompleteError(
                "the verified body manifest contains no admitted statutes",
                evidence={"full_corpus_admissible": False},
            )

        request = json.dumps(
            {
                "inventory_sha256": corpus.receipt.get("inventory_sha256"),
                "manifest_sha256": corpus.manifest_sha256,
                "official_section_urls": [row["source_url"] for row in rows],
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        response = corpus.manifest_path.read_bytes()
        body = json.dumps(rows, ensure_ascii=False, sort_keys=True).encode("utf-8")
        frontier = dict(corpus.receipt.get("frontier") or {})
        frontier.update(
            {
                "bundle_closed": True,
                "closed": True,
                "enumerator_closed": True,
                "expected_index_units": len(rows),
                "method": "official_bundle",
                "pagination_closed": False,
                "remaining_bundle_members": [],
                "toc_exhausted": True,
                "unvisited_continuation_links": [],
                "visited_index_units": len(rows),
            }
        )
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        inventory = corpus.receipt.get("inventory") or {}
        edition_as_of = str(inventory.get("edition_as_of") or "")
        return OfficialFetch(
            jurisdiction_code=normalized,
            request_bytes=request,
            response_bytes=response,
            body_bytes=body,
            source_domain=self.OFFICIAL_DOMAIN,
            source_path=self.OFFICIAL_ENTRY_PATH,
            frontier=frontier,
            rows=tuple(rows),
            transport_kind="archived_https",
            fixture=False,
            first_hierarchy_unit=str(rows[0]["canonical_key"]),
            last_hierarchy_unit=str(rows[-1]["canonical_key"]),
            observed_at=str(inventory.get("observed_at") or ""),
            edition=str(inventory.get("edition_identifier") or ""),
            legal_as_of=f"{edition_as_of}T00:00:00Z",
        )


StateScraperRegistry.register("GA", GeorgiaScraper)
