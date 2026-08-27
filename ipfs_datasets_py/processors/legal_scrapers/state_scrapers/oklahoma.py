"""Scraper for Oklahoma state laws.

The primary corpus is the Legislature's complete-title PDF frontier.  Legacy
OSCN document methods remain available only as bounded recovery probes.
"""

import hashlib
import json
import os
import re
import ssl
import time
import urllib.request
from dataclasses import fields as dataclass_fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Set
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ipfs_datasets_py.utils import anyio_compat as asyncio

from .base_scraper import (
    BaseStateScraper,
    NormalizedStatute,
    StatuteMetadata,
    current_partial_checkpoint_run_directory,
)
from .registry import StateScraperRegistry


class OklahomaScraper(BaseStateScraper):
    """Scraper for Oklahoma laws from the HTTPS Legislature PDF frontier."""

    OFFICIAL_DOMAIN = "www.oklegislature.gov"
    OFFICIAL_ENTRY_PATH = "/osstatuestitle.html"
    OFFICIAL_ENTRY_URL = "https://www.oklegislature.gov/osstatuestitle.html"
    OFFICIAL_TITLES = (
        ("1", "Abstracting"),
        ("2", "Agriculture"),
        ("3", "Aircraft and Airports"),
        ("3A", "Amusements and Sports"),
        ("4", "Animals"),
        ("5", "Attorneys and the State Bar"),
        ("6", "Banks and Trust Companies"),
        ("7", "Blind Persons"),
        ("8", "Cemeteries"),
        ("9", "Census"),
        ("10", "Children"),
        ("10A", "Children and Juvenile Code"),
        ("11", "Cities and Towns"),
        ("12", "Civil Procedure"),
        ("12A", "Uniform Commercial Code"),
        ("13", "Common Carriers"),
        ("14", "Congressional and Legislative Districts"),
        ("14A", "Consumer Credit Code"),
        ("15", "Contracts"),
        ("16", "Conveyances"),
        ("17", "Corporation Commission"),
        ("18", "Corporations"),
        ("19", "Counties and County Officers"),
        ("20", "Courts"),
        ("21", "Crimes and Punishments"),
        ("22", "Criminal Procedure"),
        ("23", "Damages"),
        ("24", "Debtor and Creditor"),
        ("25", "Definitions and General Provisions"),
        ("26", "Elections"),
        ("27", "Eminent Domain"),
        ("27A", "Environment and Natural Resources"),
        ("28", "Fees"),
        ("29", "Game and Fish"),
        ("30", "Guardian and Ward"),
        ("31", "Homestead and Exemptions"),
        ("32", "Husband and Wife"),
        ("33", "Inebriates"),
        ("34", "Initiative and Referendum"),
        ("36", "Insurance"),
        ("37", "Intoxicating Liquors"),
        ("37A", "Alcoholic Beverages"),
        ("38", "Jurors"),
        ("39", "Justices and Constables"),
        ("40", "Labor"),
        ("41", "Landlord and Tenant"),
        ("42", "Liens"),
        ("43", "Marriage and Family"),
        ("43A", "Mental Health"),
        ("44", "Militia"),
        ("45", "Mines and Mining"),
        ("46", "Mortgages"),
        ("47", "Motor Vehicles"),
        ("49", "Notaries Public"),
        ("50", "Nuisances"),
        ("51", "Officers"),
        ("52", "Oil and Gas"),
        ("53", "Oklahoma Historical Societies and Associations"),
        ("54", "Partnership"),
        ("56", "Poor Persons"),
        ("57", "Prisons and Reformatories"),
        ("58", "Probate Procedure"),
        ("59", "Professions and Occupations"),
        ("60", "Property"),
        ("61", "Public Buildings and Public Works"),
        ("62", "Public Finance"),
        ("63", "Public Health and Safety"),
        ("64", "Public Lands"),
        ("65", "Public Libraries"),
        ("66", "Railroads"),
        ("67", "Records"),
        ("68", "Revenue and Taxation"),
        ("69", "Roads, Bridges, and Ferries"),
        ("70", "Schools"),
        ("71", "Securities"),
        ("72", "Soldiers and Sailors"),
        ("73", "State Capital and Capitol Building"),
        ("74", "State Government"),
        ("74E", "Ethics Rules"),
        ("75", "Statutes and Reports"),
        ("76", "Torts"),
        ("78", "Trademarks and Labels"),
        ("79", "Trusts and Pools"),
        ("80", "United States"),
        ("82", "Waters and Water Rights"),
        ("83", "Weights and Measures"),
        ("84", "Wills and Succession"),
        ("85", "Workers' Compensation"),
        ("85A", "Administrative Workers' Compensation System"),
    )
    OFFICIAL_TITLE_COUNT = len(OFFICIAL_TITLES)
    _SEED_INDEX_URLS = [
        "https://www.oscn.net/applications/oscn/DeliverDocument.asp?CiteID=69380",
        "https://www.oscn.net/applications/oscn/DeliverDocument.asp?CiteID=69782&Title=74",
        "https://www.oscn.net/applications/oscn/DeliverDocument.asp?CiteID=438588",
        "https://www.oscn.net/applications/oscn/Index.asp?ftdb=STOKST74",
        "https://www.oscn.net/applications/oscn/index.asp?level=1&ftdb=STOKST",
    ]
    _ANTI_BOT_RE = re.compile(
        r"why am i seeing this\?|verify (?:you are|you're) human|automated traffic|cf-browser-verification|just a moment",
        re.IGNORECASE,
    )
    _CASELAW_RE = re.compile(
        r"court of (?:criminal|civil) appeals cases|oklahoma (?:supreme|court of criminal appeals|court of civil appeals)|case number:\s*[A-Z0-9\-]+|v\.\s+state",
        re.IGNORECASE,
    )
    _NON_STATUTE_RE = re.compile(
        r"oklahoma attorney general'?s opinions|oklahoma jury instructions|uniform jury instructions|ag\s+\d{2,4}\s*[- ]\s*\d+|question submitted by:|previous case\s+top of index\s+this point in index",
        re.IGNORECASE,
    )

    @staticmethod
    def _normalize_wayback_url(url: str) -> str:
        value = str(url or "").strip()
        if value.startswith("http://web.archive.org/"):
            return "https://" + value[len("http://") :]
        return value

    def get_base_url(self) -> str:
        """Return the base URL for Oklahoma's legislative website."""
        return "https://www.oklegislature.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return all 89 official complete-title PDF frontier members."""

        return [
            {
                "name": f"Oklahoma Statutes Title {number} — {name}",
                "url": self.official_title_url(number),
                "type": "Code",
                "title_number": number,
            }
            for number, name in self.OFFICIAL_TITLES
        ]

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Oklahoma's legislative website.

        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code

        Returns:
            List of NormalizedStatute objects
        """
        # Full-corpus uses a large practical ceiling so discovery is not
        # silently truncated to the historical sample default of 160.
        # Bounded probes honor max_statutes / STATE_SCRAPER_MAX_STATUTES.
        if max_statutes is not None:
            return_threshold = max(1, int(max_statutes))
            unbounded_full = False
        elif self._full_corpus_enabled():
            return_threshold = 1000000
            unbounded_full = True
        else:
            return_threshold = self._bounded_return_threshold(160)
            unbounded_full = False

        from .oklahoma_constitution import (
            configured_constitution_text_path,
            parse_oklahoma_constitution_text,
        )

        constitution_path = configured_constitution_text_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_oklahoma_constitution_text(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Oklahoma Constitution",
                    max_statutes=None if unbounded_full else return_threshold,
                )
                return constitution_rows if unbounded_full else constitution_rows[:return_threshold]
        from .oklahoma_title import (
            parse_configured_oklahoma_title,
            title_number_from_pdf_url,
        )

        local_rows = parse_configured_oklahoma_title(
            code_name=code_name, max_statutes=return_threshold
        )
        if local_rows:
            return local_rows[: int(return_threshold)]

        title_number = title_number_from_pdf_url(code_url)
        if title_number:
            return await self._scrape_complete_title_pdf(
                declared_code_name=code_name,
                title_number=title_number,
                source_url=code_url,
                max_statutes=None if unbounded_full else return_threshold,
            )

        # Seed recovery is for bounded probes only — never sole full-corpus path.
        if not self._full_corpus_enabled() and max_statutes is None:
            direct = await self._scrape_direct_seed_sections(
                code_name, max_statutes=return_threshold
            )
            if direct:
                return direct[:return_threshold]

        checkpoint = _OklahomaCheckpoint(self.state_code)
        seed_statutes = checkpoint.load(
            default_state_name=self.state_name,
            default_code_name=code_name,
            max_statutes=max(10, min(return_threshold, 1000000)),
        )
        # Bootstrap with a tiny direct OSCN sample even in full-corpus mode so
        # long candidate-discovery phases still show early real progress.
        bootstrap_seed_target_raw = str(
            os.getenv("STATE_SCRAPER_OK_BOOTSTRAP_SEED_COUNT", "") or ""
        ).strip()
        try:
            bootstrap_seed_target = (
                int(bootstrap_seed_target_raw) if bootstrap_seed_target_raw else 2
            )
        except Exception:
            bootstrap_seed_target = 2
        bootstrap_seed_target = max(1, min(8, bootstrap_seed_target))
        try:
            direct_seed = await self._scrape_direct_seed_sections(
                code_name,
                max_statutes=bootstrap_seed_target,
            )
        except Exception:
            direct_seed = []
        if direct_seed:
            seed_statutes = list(seed_statutes) + list(direct_seed)
            self.logger.info(
                "Oklahoma OSCN bootstrap: statutes_so_far=%s direct_seed_sections=%s",
                len(direct_seed),
                len(direct_seed),
            )
        best_official: List[NormalizedStatute] = []
        for attempt in range(3):
            archival = await self._scrape_oscn_documents(
                code_name=code_name,
                max_statutes=max(10, return_threshold),
                seed_statutes=seed_statutes if attempt == 0 else best_official,
                checkpoint=checkpoint,
            )
            if len(archival) > len(best_official):
                best_official = archival
            if best_official:
                self.logger.info(
                    "Oklahoma OSCN official path: scraped %s sections on attempt %s",
                    len(best_official),
                    attempt + 1,
                )
                # Bounded probes may return early; full-corpus continues retries
                # then prefers the official OSCN set over secondary mirrors.
                if not self._full_corpus_enabled() or max_statutes is not None:
                    return best_official
            await asyncio.sleep(0.4 * (attempt + 1))

        if best_official:
            return list(best_official) if unbounded_full else best_official[:return_threshold]

        # Official OSCN only for recovery of zero-state probes. Justia is never
        # a sole full-corpus admission path (secondary host; quarantine-only).
        if self._full_corpus_enabled() and max_statutes is None:
            self.logger.warning(
                "Oklahoma full-corpus run found zero official OSCN statutes; "
                "refusing secondary Justia sole-admission fallback"
            )
            return []

        fallback_urls = [code_url]
        allow_justia = str(os.getenv("STATE_SCRAPER_OK_ALLOW_JUSTIA_FALLBACK", "") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if allow_justia:
            fallback_urls.append("https://law.justia.com/codes/oklahoma/")
        best: List[NormalizedStatute] = []
        for candidate in fallback_urls:
            try:
                statutes = await self._generic_scrape(
                    code_name,
                    candidate,
                    "Okla. Stat.",
                    max_sections=max(10, return_threshold),
                )
            except Exception:
                statutes = []
            if len(statutes) > len(best):
                best = statutes
        return best

    @staticmethod
    def _looks_like_official_pdf(payload: bytes) -> bool:
        value = bytes(payload or b"")
        return len(value) >= 256 and value.lstrip().startswith(b"%PDF-")

    @staticmethod
    def _looks_like_official_titles_html(payload: bytes) -> bool:
        sample = bytes(payload or b"")
        lowered = sample.lower()
        return bool(
            b"<html" in lowered
            and b"ok_statutes/completetitles/os" in lowered
            and b"turnstile" not in lowered
            and b"captcha" not in lowered
        )

    def _canonical_last_transport_receipt(
        self,
        *,
        source_url: str,
        payload: bytes,
    ) -> Dict[str, Any]:
        raw = dict(getattr(self, "_last_page_fetch_transport_evidence", {}) or {})
        return self._canonical_transport_receipt(
            source_url=source_url,
            payload=payload,
            raw_receipt=raw,
        )

    def _canonical_transport_receipt(
        self,
        *,
        source_url: str,
        payload: bytes,
        raw_receipt: Mapping[str, Any],
    ) -> Dict[str, Any]:
        from ipfs_datasets_py.processors.legal_data.state_laws_source_provenance import (
            StateLawTransportReceiptError,
            canonicalize_state_law_transport_receipt,
        )

        digest = hashlib.sha256(payload).hexdigest()
        raw = dict(raw_receipt or {})
        transport = str(raw.get("source_transport") or "").strip().lower()
        if transport.startswith("common_crawl"):
            indexed_url = str(raw.get("common_crawl_indexed_url") or "").strip()
            if indexed_url != source_url:
                raise RuntimeError(
                    "Oklahoma Common Crawl receipt does not bind the exact official URL"
                )
        try:
            return canonicalize_state_law_transport_receipt(
                raw,
                official_url=source_url,
                content_sha256=digest,
            )
        except StateLawTransportReceiptError as exc:
            raise RuntimeError(
                f"Oklahoma official byte transport rejected: {exc.code}"
            ) from exc

    async def _fetch_official_bytes_with_receipt(
        self,
        *,
        source_url: str,
        content_validator,
        timeout_seconds: int,
    ) -> tuple[bytes, Dict[str, Any]]:
        payload = await self._fetch_page_content_with_archival_fallback(
            source_url,
            timeout_seconds=timeout_seconds,
            content_validator=content_validator,
            # UnifiedWebScraper is reused below for PDF extraction.  Its fetch
            # API does not expose the immutable archive locator needed for a
            # state-law transport receipt, so acquisition stays on the shared
            # direct/cache/ArchivalFetchClient path.
            enable_unified=False,
        )
        if not payload or not content_validator(payload):
            raise RuntimeError(f"Oklahoma official bytes unavailable: {source_url}")
        receipt = self._canonical_last_transport_receipt(
            source_url=source_url,
            payload=payload,
        )
        return payload, receipt

    async def _ensure_complete_title_frontier(self) -> Dict[str, Any]:
        cached = getattr(self, "_oklahoma_complete_title_frontier", None)
        if isinstance(cached, dict):
            return cached

        from .oklahoma_title import EXPECTED_TITLE_COUNT, title_pdf_links

        payload, transport_receipt = await self._fetch_official_bytes_with_receipt(
            source_url=self.OFFICIAL_ENTRY_URL,
            content_validator=self._looks_like_official_titles_html,
            timeout_seconds=30,
        )
        links = title_pdf_links(payload.decode("utf-8", errors="replace"))
        expected_numbers = {number for number, _name in self.OFFICIAL_TITLES}
        discovered_numbers = {number for number, _name, _url in links}
        if (
            len(links) != EXPECTED_TITLE_COUNT
            or EXPECTED_TITLE_COUNT != self.OFFICIAL_TITLE_COUNT
            or discovered_numbers != expected_numbers
        ):
            raise RuntimeError(
                "Oklahoma complete-title frontier rejected: expected exactly "
                f"{EXPECTED_TITLE_COUNT} official PDF members, found {len(links)}"
            )

        member_urls = {number: url for number, _name, url in links}
        member_digest = hashlib.sha256(
            json.dumps(
                [(number, member_urls[number]) for number, _name in self.OFFICIAL_TITLES],
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        frontier = {
            "schema_version": "oklahoma-complete-title-frontier/v1",
            "source_url": self.OFFICIAL_ENTRY_URL,
            "official_source": True,
            "frontier_closed": True,
            "expected_title_count": EXPECTED_TITLE_COUNT,
            "discovered_title_count": len(links),
            "title_numbers": [number for number, _name in self.OFFICIAL_TITLES],
            "member_urls": member_urls,
            "member_digest_sha256": member_digest,
            "content_sha256": hashlib.sha256(payload).hexdigest(),
            "observed_at": datetime.now(UTC).isoformat(),
            "transport_receipt": transport_receipt,
        }
        self._oklahoma_complete_title_frontier = frontier
        return frontier

    async def _ensure_complete_title_payloads(
        self,
        frontier: Mapping[str, Any],
    ) -> Dict[str, tuple[bytes, Dict[str, Any]]]:
        cached = getattr(self, "_oklahoma_complete_title_payloads", None)
        if isinstance(cached, dict) and len(cached) == self.OFFICIAL_TITLE_COUNT:
            return cached

        member_urls = dict(frontier.get("member_urls") or {})
        requested = [
            str(member_urls.get(number) or "").strip()
            for number, _name in self.OFFICIAL_TITLES
        ]
        if any(not url for url in requested) or len(set(requested)) != len(requested):
            raise RuntimeError(
                "Oklahoma complete-title PDF frontier lacks unique exact member URLs"
            )
        batch = await self._fetch_page_contents_with_archival_fallback_retrying_residuals(
            requested,
            residual_retry_attempts=1,
            timeout_seconds=90,
            headers={
                "User-Agent": "ipfs-datasets-oklahoma-code-scraper/2.0",
            },
            content_validator=self._looks_like_official_pdf,
            media_type="application/pdf",
            max_concurrency=8,
            prefer_direct=True,
            wayback_prefix_inventory=True,
        )
        if list(batch.urls) != requested or any(
            len(vector) != len(requested)
            for vector in (
                batch.payloads,
                batch.errors,
                batch.transport_receipts,
                batch.parser_input_envelopes,
            )
        ):
            raise RuntimeError(
                "Oklahoma complete-title PDF frontier returned unaligned acquisition rows"
            )
        failures = [
            {"url": url, "error": error or "empty parser input"}
            for url, payload, error in zip(
                batch.urls, batch.payloads, batch.errors, strict=True
            )
            if error is not None or not self._looks_like_official_pdf(bytes(payload or b""))
        ]
        if failures:
            raise RuntimeError(
                "Oklahoma complete-title PDF frontier is incomplete; "
                f"unresolved exact URLs: {failures}"
            )
        resolved: Dict[str, tuple[bytes, Dict[str, Any]]] = {}
        for url, payload, receipt in zip(
            batch.urls,
            batch.payloads,
            batch.transport_receipts,
            strict=True,
        ):
            body = bytes(payload)
            if not isinstance(receipt, Mapping):
                raise RuntimeError(
                    f"Oklahoma aligned title PDF lacks a transport receipt: {url}"
                )
            resolved[url] = (
                body,
                self._canonical_transport_receipt(
                    source_url=url,
                    payload=body,
                    raw_receipt=receipt,
                ),
            )
        self._oklahoma_complete_title_payloads = resolved
        return resolved

    async def _scrape_complete_title_pdf(
        self,
        *,
        declared_code_name: str,
        title_number: str,
        source_url: str,
        max_statutes: Optional[int],
    ) -> List[NormalizedStatute]:
        from ipfs_datasets_py.processors.web_archiving.unified_web_scraper import (
            UnifiedWebScraper,
        )

        from .oklahoma_title import (
            extract_oklahoma_title_pdf_text,
            inactive_title_frontier_from_text,
            parse_oklahoma_title_text,
        )

        frontier = await self._ensure_complete_title_frontier()
        live_url = str((frontier.get("member_urls") or {}).get(title_number) or source_url)
        if live_url != source_url:
            # The declared code frontier and fetched member must stay identical;
            # otherwise BaseStateScraper could not bind a zero-title exclusion.
            source_url = live_url
        if max_statutes is None:
            prefetched = await self._ensure_complete_title_payloads(frontier)
            payload, transport_receipt = prefetched[source_url]
        else:
            payload, transport_receipt = await self._fetch_official_bytes_with_receipt(
                source_url=source_url,
                content_validator=self._looks_like_official_pdf,
                timeout_seconds=90,
            )
        extraction_method = "oklahoma_title.extract_oklahoma_title_pdf_text"
        try:
            extracted_text = extract_oklahoma_title_pdf_text(payload)
        except Exception:
            # Compatibility for bounded synthetic fixtures and installations
            # without pdfplumber.  Valid production PDFs use the page-aware
            # path above so TOC candidates cannot collide with operative law.
            extraction_method = "UnifiedWebScraper._extract_pdf_text"
            extracted_text = str(
                await UnifiedWebScraper._extract_pdf_text(payload) or ""
            ).strip()
        if not extracted_text:
            raise RuntimeError(
                f"Oklahoma Title {title_number} PDF contained no extractable official text"
            )

        rows = parse_oklahoma_title_text(
            extracted_text,
            title_number=title_number,
            code_name=declared_code_name,
            source_url=source_url,
            max_statutes=max_statutes,
        )
        payload_digest = hashlib.sha256(payload).hexdigest()
        frontier_digest = str(frontier.get("member_digest_sha256") or "")
        for row in rows:
            structured = dict(row.structured_data or {})
            structured.update(
                {
                    "source_kind": "official_oklahoma_complete_title_pdf",
                    "source_authority_class": "official",
                    "discovery_method": "oklegislature_89_complete_title_frontier",
                    "extraction_method": extraction_method,
                    "source_document_sha256": payload_digest,
                    "source_frontier_url": str(frontier.get("source_url") or ""),
                    "source_frontier_content_sha256": str(
                        frontier.get("content_sha256") or ""
                    ),
                    "source_frontier_sha256": frontier_digest,
                    "source_frontier_expected_titles": self.OFFICIAL_TITLE_COUNT,
                    "source_frontier_transport_receipt": dict(
                        frontier.get("transport_receipt") or {}
                    ),
                    "transport_receipt": transport_receipt,
                    "full_corpus_admissible": True,
                    "skip_hydrate": True,
                }
            )
            row.structured_data = structured
            row.legal_area = self._identify_legal_area(
                f"{row.section_name} {declared_code_name}"
            )
        if rows:
            return rows

        observed_at = datetime.now(UTC).isoformat()
        exclusion = inactive_title_frontier_from_text(
            extracted_text,
            title_number=title_number,
            code_name=declared_code_name,
            source_url=source_url,
            content_sha256=payload_digest,
            observed_at=observed_at,
            transport_receipt=transport_receipt,
        )
        if exclusion is None:
            raise RuntimeError(
                f"Oklahoma Title {title_number} returned zero statutes without "
                "a closed official inactive-title frontier"
            )
        exclusions = getattr(self, "_oklahoma_zero_title_exclusions", None)
        if not isinstance(exclusions, dict):
            exclusions = {}
            self._oklahoma_zero_title_exclusions = exclusions
        exclusion_evidence = exclusion.to_dict()
        exclusion_evidence.update(
            {
                "source_frontier_url": str(frontier.get("source_url") or ""),
                "source_frontier_content_sha256": str(
                    frontier.get("content_sha256") or ""
                ),
                "source_frontier_sha256": frontier_digest,
                "source_frontier_expected_titles": self.OFFICIAL_TITLE_COUNT,
                "source_frontier_transport_receipt": dict(
                    frontier.get("transport_receipt") or {}
                ),
            }
        )
        exclusions[declared_code_name] = exclusion_evidence
        return []

    def _closed_zero_result_code_exclusion(
        self,
        code_info: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        exclusions = getattr(self, "_oklahoma_zero_title_exclusions", None)
        if not isinstance(exclusions, dict):
            return None
        evidence = exclusions.get(str(code_info.get("name") or ""))
        return dict(evidence) if isinstance(evidence, dict) else None

    async def _scrape_direct_seed_sections(
        self,
        code_name: str,
        max_statutes: int = 2,
    ) -> List[NormalizedStatute]:
        seeds = [
            "https://www.oscn.net/applications/oscn/DeliverDocument.asp?CiteID=69380",
            "https://www.oscn.net/applications/oscn/DeliverDocument.asp?CiteID=436720",
        ]
        headers = {"User-Agent": "Mozilla/5.0"}
        out: List[NormalizedStatute] = []
        for url in seeds[: max(1, int(max_statutes or 1))]:
            statute = await self._build_statute_from_jina_reader(
                code_name=code_name,
                document_url=url,
            )
            if statute is None:
                statute = await self._build_statute_from_document_url(
                    code_name=code_name,
                    document_url=url,
                    headers=headers,
                )
            if statute is None:
                continue
            structured = dict(statute.structured_data or {})
            structured.setdefault("source_kind", "official_oklahoma_oscn_html")
            structured.setdefault("discovery_method", "official_seed_document")
            structured["skip_hydrate"] = True
            statute.structured_data = structured
            if statute.metadata is None:
                statute.metadata = StatuteMetadata()
            out.append(statute)
        return out

    async def _build_statute_from_jina_reader(
        self,
        code_name: str,
        document_url: str,
    ) -> NormalizedStatute | None:
        reader_url = f"https://r.jina.ai/http://{document_url}"
        payload = await self._fetch_non_authoritative_reference_bytes(
            reader_url,
            timeout_seconds=20,
            enable_common_crawl=False,
        )
        markdown = payload.decode("utf-8", errors="replace") if payload else ""
        if not markdown:
            return None

        section_match = re.search(
            r"Section\s+([0-9A-Za-z.\-]+)\s+-\s*([^\n*]+)", markdown, flags=re.IGNORECASE
        )
        cite_match = re.search(
            r"Cite as:\s*([0-9]+\s+O\.S\.\s*§\s*[0-9A-Za-z.\-]+)", markdown, flags=re.IGNORECASE
        )
        body_start = cite_match.end() if cite_match else -1
        if body_start < 0 and section_match:
            body_start = section_match.end()
        if body_start < 0:
            return None

        tail = markdown[body_start:]
        end = len(tail)
        for marker in (
            "Historical Data",
            "Citationizer",
            "Oklahoma Attorney General",
            "Court of Criminal Appeals",
        ):
            idx = tail.find(marker)
            if idx >= 0:
                end = min(end, idx)
        body = self._normalize_legal_text(tail[:end])
        body = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", body)
        body = self._normalize_legal_text(body)
        if len(body) < 120:
            return None

        section_number = (
            section_match.group(1).strip() if section_match else self._extract_cite_id(document_url)
        )
        section_name = (
            section_match.group(2).strip()[:180] if section_match else f"Section {section_number}"
        )
        official_cite = (
            cite_match.group(1).strip() if cite_match else f"Okla. Stat. § {section_number}"
        )

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=section_name,
            full_text=body,
            legal_area=self._identify_legal_area(body),
            source_url=document_url,
            official_cite=official_cite,
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "jina_reader_oklahoma_oscn",
                "discovery_method": "official_seed_document_reader",
                "reader_url": reader_url,
                "skip_hydrate": True,
            },
        )

    async def _scrape_oscn_documents(
        self,
        code_name: str,
        max_statutes: int,
        *,
        seed_statutes: Optional[List[NormalizedStatute]] = None,
        checkpoint: Optional["_OklahomaCheckpoint"] = None,
    ) -> List[NormalizedStatute]:
        headers = {"User-Agent": "Mozilla/5.0"}
        statutes: List[NormalizedStatute] = []
        seen_statutes: Set[str] = set()
        seen_candidate_urls: Set[str] = set()

        for statute in list(seed_statutes or []):
            dedupe_key = _statute_dedupe_key(statute)
            if not dedupe_key or dedupe_key in seen_statutes:
                continue
            seen_statutes.add(dedupe_key)
            statutes.append(statute)
            source_url = str(statute.source_url or "").strip().lower()
            if source_url:
                seen_candidate_urls.add(source_url)

        candidate_urls = await self._collect_candidate_document_urls(headers=headers)
        candidate_timeout_raw = str(
            os.getenv("STATE_SCRAPER_OK_CANDIDATE_TIMEOUT_SECONDS", "") or ""
        ).strip()
        try:
            candidate_timeout_seconds = int(candidate_timeout_raw) if candidate_timeout_raw else 75
        except Exception:
            candidate_timeout_seconds = 75
        candidate_timeout_seconds = max(20, min(240, candidate_timeout_seconds))
        heartbeat_raw = str(os.getenv("STATE_SCRAPER_OK_SCAN_HEARTBEAT_SECONDS", "") or "").strip()
        try:
            scan_heartbeat_seconds = int(heartbeat_raw) if heartbeat_raw else 30
        except Exception:
            scan_heartbeat_seconds = 30
        scan_heartbeat_seconds = max(10, min(180, scan_heartbeat_seconds))
        heartbeat_every_raw = str(
            os.getenv("STATE_SCRAPER_OK_SCAN_HEARTBEAT_EVERY", "") or ""
        ).strip()
        try:
            scan_heartbeat_every = int(heartbeat_every_raw) if heartbeat_every_raw else 200
        except Exception:
            scan_heartbeat_every = 200
        scan_heartbeat_every = max(25, min(1000, scan_heartbeat_every))
        self.logger.info(
            "Oklahoma OSCN crawl: discovered_candidate_urls=%s max_statutes=%s",
            len(candidate_urls),
            max_statutes,
        )
        if checkpoint is not None:
            checkpoint.maybe_write(
                statutes,
                code_name=code_name,
                scanned_candidates=len(seen_candidate_urls),
                discovered_candidates=len(candidate_urls),
                progress={
                    "crawl_phase": "candidate_discovery_complete",
                    "seed_statutes": len(statutes),
                },
            )
        crawl_started_at = time.time()
        last_scan_heartbeat_at = crawl_started_at
        timeout_count = 0
        error_count = 0
        for link in candidate_urls:
            if len(statutes) >= max_statutes:
                break
            dedupe_key = str(link or "").strip().lower()
            if dedupe_key in seen_candidate_urls:
                continue
            seen_candidate_urls.add(dedupe_key)
            scanned_candidates = len(seen_candidate_urls)

            now = time.time()
            if (
                scanned_candidates == 1
                or scanned_candidates % scan_heartbeat_every == 0
                or now - last_scan_heartbeat_at >= scan_heartbeat_seconds
            ):
                elapsed = max(1.0, now - crawl_started_at)
                scan_rate_per_min = (float(scanned_candidates) / elapsed) * 60.0
                self.logger.info(
                    "Oklahoma OSCN crawl: scanned_candidates=%s statutes_so_far=%s discovered_candidates=%s scan_rate_per_min=%.2f",
                    scanned_candidates,
                    len(statutes),
                    len(candidate_urls),
                    scan_rate_per_min,
                )
                if checkpoint is not None:
                    checkpoint.write(
                        statutes,
                        code_name=code_name,
                        scanned_candidates=scanned_candidates,
                        discovered_candidates=len(candidate_urls),
                        progress={
                            "crawl_phase": "candidate_scan",
                            "scan_rate_per_minute": round(scan_rate_per_min, 4),
                            "timeout_count": int(timeout_count),
                            "error_count": int(error_count),
                        },
                    )
                last_scan_heartbeat_at = now

            try:
                statute = await asyncio.wait_for(
                    self._build_statute_from_document_url(
                        code_name=code_name,
                        document_url=link,
                        headers=headers,
                    ),
                    timeout=float(candidate_timeout_seconds),
                )
            except asyncio.TimeoutError:
                timeout_count += 1
                self.logger.warning(
                    "Oklahoma OSCN crawl: candidate_timeout scanned_candidates=%s timeout_seconds=%s url=%s",
                    scanned_candidates,
                    candidate_timeout_seconds,
                    link,
                )
                continue
            except Exception as exc:
                error_count += 1
                self.logger.warning(
                    "Oklahoma OSCN crawl: candidate_error scanned_candidates=%s url=%s error=%s",
                    scanned_candidates,
                    link,
                    exc,
                )
                continue
            if statute is None:
                continue
            statute_key = _statute_dedupe_key(statute)
            if statute_key and statute_key in seen_statutes:
                continue
            if statute_key:
                seen_statutes.add(statute_key)
            statutes.append(statute)
            if checkpoint is not None:
                checkpoint.maybe_write(
                    statutes,
                    code_name=code_name,
                    scanned_candidates=len(seen_candidate_urls),
                    discovered_candidates=len(candidate_urls),
                    progress={
                        "crawl_phase": "candidate_scan",
                        "timeout_count": int(timeout_count),
                        "error_count": int(error_count),
                    },
                )
            if len(statutes) == 1 or len(statutes) % 25 == 0:
                self.logger.info(
                    "Oklahoma OSCN crawl: statutes_so_far=%s scanned_candidates=%s",
                    len(statutes),
                    len(seen_candidate_urls),
                )

        self.logger.info(
            "Oklahoma OSCN crawl: completed statutes=%s scanned_candidates=%s discovered_candidates=%s timeout_count=%s error_count=%s",
            len(statutes),
            len(seen_candidate_urls),
            len(candidate_urls),
            timeout_count,
            error_count,
        )
        if checkpoint is not None:
            checkpoint.write(
                statutes,
                code_name=code_name,
                scanned_candidates=len(seen_candidate_urls),
                discovered_candidates=len(candidate_urls),
                progress={
                    "crawl_phase": "complete",
                    "timeout_count": int(timeout_count),
                    "error_count": int(error_count),
                },
            )
        return statutes

    async def _collect_candidate_document_urls(self, headers: Dict[str, str]) -> List[str]:
        candidates: List[str] = []
        seen: Set[str] = set()

        def _add(url_value: str) -> None:
            normalized = str(url_value or "").strip()
            if not normalized:
                return
            if "deliverdocument.asp?citeid=" not in normalized.lower():
                return
            if normalized in seen:
                return
            seen.add(normalized)
            candidates.append(normalized)

        bounded_limit = self._bounded_return_threshold(0)
        bounded_direct_only = str(
            os.getenv("STATE_SCRAPER_BOUNDED_DIRECT_ONLY", "")
        ).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if bounded_limit > 0 and bounded_direct_only:
            for seed_url in self._SEED_INDEX_URLS:
                _add(seed_url)
                if len(candidates) >= max(1, bounded_limit):
                    self.logger.info(
                        "Oklahoma OSCN discovery: bounded_direct_only candidates=%s",
                        len(candidates),
                    )
                    return candidates
            self.logger.info(
                "Oklahoma OSCN discovery: bounded_direct_only candidates=%s",
                len(candidates),
            )
            return candidates

        seed_fetch_timeout_raw = str(
            os.getenv("STATE_SCRAPER_OK_SEED_FETCH_TIMEOUT_SECONDS", "") or ""
        ).strip()
        try:
            seed_fetch_timeout_seconds = (
                int(seed_fetch_timeout_raw) if seed_fetch_timeout_raw else 90
            )
        except Exception:
            seed_fetch_timeout_seconds = 90
        seed_fetch_timeout_seconds = max(30, min(300, seed_fetch_timeout_seconds))

        seed_archive_timeout_raw = str(
            os.getenv("STATE_SCRAPER_OK_SEED_ARCHIVE_DISCOVERY_TIMEOUT_SECONDS", "") or ""
        ).strip()
        try:
            seed_archive_timeout_seconds = (
                int(seed_archive_timeout_raw) if seed_archive_timeout_raw else 60
            )
        except Exception:
            seed_archive_timeout_seconds = 60
        seed_archive_timeout_seconds = max(20, min(240, seed_archive_timeout_seconds))

        cdx_timeout_raw = str(
            os.getenv("STATE_SCRAPER_OK_CDX_DISCOVERY_TIMEOUT_SECONDS", "") or ""
        ).strip()
        try:
            cdx_timeout_seconds = int(cdx_timeout_raw) if cdx_timeout_raw else 120
        except Exception:
            cdx_timeout_seconds = 120
        cdx_timeout_seconds = max(30, min(360, cdx_timeout_seconds))

        self.logger.info(
            "Oklahoma OSCN discovery: seed_scan_start seed_count=%s full_corpus=%s",
            len(self._SEED_INDEX_URLS),
            self._full_corpus_enabled(),
        )
        for seed_url in self._SEED_INDEX_URLS:
            seed_started_at = time.time()
            self.logger.info(
                "Oklahoma OSCN discovery: scanning_seed_url=%s candidates_so_far=%s",
                seed_url,
                len(candidates),
            )
            _add(seed_url)
            try:
                html = await asyncio.wait_for(
                    self._request_text(seed_url, headers=headers, timeout=45),
                    timeout=float(seed_fetch_timeout_seconds),
                )
            except asyncio.TimeoutError:
                self.logger.warning(
                    "Oklahoma OSCN discovery: seed_fetch_timeout seed_url=%s timeout_seconds=%s",
                    seed_url,
                    seed_fetch_timeout_seconds,
                )
                html = ""
            except Exception as exc:
                self.logger.warning(
                    "Oklahoma OSCN discovery: seed_fetch_error seed_url=%s error=%s",
                    seed_url,
                    exc,
                )
                html = ""
            if not html:
                try:
                    archived_links = await asyncio.wait_for(
                        self._discover_links_from_archived_seed(seed_url=seed_url, headers=headers),
                        timeout=float(seed_archive_timeout_seconds),
                    )
                except asyncio.TimeoutError:
                    self.logger.warning(
                        "Oklahoma OSCN discovery: archived_seed_timeout seed_url=%s timeout_seconds=%s",
                        seed_url,
                        seed_archive_timeout_seconds,
                    )
                    archived_links = []
                except Exception as exc:
                    self.logger.warning(
                        "Oklahoma OSCN discovery: archived_seed_error seed_url=%s error=%s",
                        seed_url,
                        exc,
                    )
                    archived_links = []
                for archived_link in archived_links:
                    _add(archived_link)
                self.logger.info(
                    "Oklahoma OSCN discovery: finished_seed_url=%s candidates_so_far=%s elapsed_seconds=%.2f",
                    seed_url,
                    len(candidates),
                    max(0.0, time.time() - seed_started_at),
                )
                continue
            for live_link in self._extract_deliver_document_links(seed_url=seed_url, html=html):
                _add(live_link)
            self.logger.info(
                "Oklahoma OSCN discovery: finished_seed_url=%s candidates_so_far=%s elapsed_seconds=%.2f",
                seed_url,
                len(candidates),
                max(0.0, time.time() - seed_started_at),
            )

        # Archive-driven URL discovery helps when live index pages are sparse.
        self.logger.info(
            "Oklahoma OSCN discovery: cdx_scan_start candidates_so_far=%s",
            len(candidates),
        )
        try:
            cdx_discovered_urls = await asyncio.wait_for(
                self._discover_oscn_document_urls_via_cdx(headers=headers),
                timeout=float(cdx_timeout_seconds),
            )
        except asyncio.TimeoutError:
            self.logger.warning(
                "Oklahoma OSCN discovery: cdx_scan_timeout timeout_seconds=%s candidates_so_far=%s",
                cdx_timeout_seconds,
                len(candidates),
            )
            cdx_discovered_urls = []
        except Exception as exc:
            self.logger.warning(
                "Oklahoma OSCN discovery: cdx_scan_error error=%s candidates_so_far=%s",
                exc,
                len(candidates),
            )
            cdx_discovered_urls = []

        for archive_url in cdx_discovered_urls:
            _add(archive_url)
        self.logger.info(
            "Oklahoma OSCN discovery: cdx_scan_complete candidates_so_far=%s",
            len(candidates),
        )

        self.logger.info(
            "Oklahoma OSCN discovery: total_candidates=%s",
            len(candidates),
        )
        return candidates

    def _extract_deliver_document_links(self, *, seed_url: str, html: str) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        links: List[str] = []
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            full_url = urljoin(seed_url, href)
            if "deliverdocument.asp?citeid=" not in full_url.lower():
                continue
            links.append(full_url)
        return links

    async def _discover_links_from_archived_seed(
        self, *, seed_url: str, headers: Dict[str, str]
    ) -> List[str]:
        seed_citeid = self._extract_cite_id(seed_url)
        if not seed_citeid:
            return []

        capture_limit = 50 if self._full_corpus_enabled() else 8
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx"
            "?url=www.oscn.net/applications/oscn/DeliverDocument.asp"
            f"?CiteID={seed_citeid}&output=json"
            f"&fl=timestamp,original,statuscode&filter=statuscode:200&limit={capture_limit}"
        )
        try:
            payload = await self._fetch_page_content_with_archival_fallback(
                cdx_url,
                timeout_seconds=30,
            )
            if not payload:
                return []
            rows = json.loads(payload.decode("utf-8", errors="replace"))
        except Exception:
            return []

        if not isinstance(rows, list) or len(rows) <= 1:
            return []

        discovered: List[str] = []
        # Prefer latest captures first.
        for row in reversed(rows[1:]):
            if not isinstance(row, list) or len(row) < 2:
                continue
            ts = str(row[0] or "").strip()
            original = str(row[1] or "").strip()
            if not ts or not original:
                continue
            replay_url = self._normalize_wayback_url(
                f"https://web.archive.org/web/{ts}id_/{original}"
            )
            html = await self._request_text(replay_url, headers=headers, timeout=35)
            if not html:
                continue
            for link in self._extract_deliver_document_links(seed_url=replay_url, html=html):
                discovered.append(link)
            discovery_limit = 5000 if self._full_corpus_enabled() else 400
            if len(discovered) >= discovery_limit:
                break

        return discovered

    async def _discover_oscn_document_urls_via_cdx(self, headers: Dict[str, str]) -> List[str]:
        cdx_limit = 10000 if self._full_corpus_enabled() else 1200
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx"
            "?url=www.oscn.net/applications/oscn/DeliverDocument.asp*"
            f"&output=json&filter=statuscode:200&limit={cdx_limit}"
        )
        try:
            raw = await asyncio.wait_for(
                self._fetch_page_content_with_archival_fallback(
                    cdx_url,
                    timeout_seconds=35,
                ),
                timeout=55,
            )
            if not raw:
                self.logger.info("Oklahoma OSCN CDX discovery: no payload")
                return []
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except asyncio.TimeoutError:
            self.logger.warning("Oklahoma OSCN CDX discovery timed out after 55s")
            return []
        except Exception:
            return []

        urls: List[str] = []
        if not isinstance(payload, list) or len(payload) <= 1:
            return urls

        for row in payload[1:]:
            if not isinstance(row, list) or len(row) < 3:
                continue
            timestamp = str(row[1] or "").strip() if len(row) > 1 else ""
            original = str(row[2] or "").strip()
            if "deliverdocument.asp?citeid=" not in original.lower():
                continue
            if timestamp:
                replay = self._normalize_wayback_url(
                    f"https://web.archive.org/web/{timestamp}id_/{original}"
                )
                urls.append(replay)
            urls.append(original)
        return urls

    def _extract_document_body_text(self, soup: BeautifulSoup) -> str:
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        selectors = [
            "#oscn-content",
            "#content",
            "#body",
            "main",
            "article",
            "div.document",
            "div#doc",
        ]

        candidates: List[str] = []
        for selector in selectors:
            for node in soup.select(selector):
                text = self._normalize_legal_text(node.get_text(" ", strip=True))
                if len(text) >= 300:
                    candidates.append(text)

        if not candidates:
            body = soup.find("body")
            if body is not None:
                text = self._normalize_legal_text(body.get_text(" ", strip=True))
                if text:
                    candidates.append(text)

        if not candidates:
            return ""

        text = max(candidates, key=len)
        # Drop OSCN global navigation noise that often prefixes archived pages.
        text = re.sub(r"^\s*OSCN\s+navigation\s+.*?\bHelp\b\s*", "", text, flags=re.IGNORECASE)
        text = re.split(
            r"\bCitationizer\s+©\s+Summary\s+of\s+Documents\s+Citing\s+This\s+Document\b",
            text,
            maxsplit=1,
        )[0]
        return self._normalize_legal_text(text)

    async def _build_statute_from_document_url(
        self,
        code_name: str,
        document_url: str,
        headers: Dict[str, str],
    ) -> NormalizedStatute | None:
        html = await self._request_text(document_url, headers=headers, timeout=45)
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")
        text = self._extract_document_body_text(soup)
        if len(text) < 280:
            return None

        if self._ANTI_BOT_RE.search(text):
            return None

        document_lead = text[:1200]

        has_statute_signal = bool(
            re.search(r"\b\d+\s+O\.S\.\s*§?\s*[0-9A-Za-z.\-]+", text)
            or re.search(r"\bTitle\s+\d+.*?\bSection\s+[0-9A-Za-z.\-]+", text, flags=re.IGNORECASE)
        )

        if self._CASELAW_RE.search(document_lead) and not has_statute_signal:
            return None

        if self._NON_STATUTE_RE.search(document_lead) and not has_statute_signal:
            return None

        # Ignore obvious navigation/event pages that happen to be long.
        if self._looks_like_navigation_text(text) and not self._contains_statute_signals(text):
            return None

        section_number = self._extract_section_number(text) or self._extract_cite_id(document_url)
        if not section_number:
            section_number = "unknown"

        section_name_match = re.search(
            r"Section\s+[0-9A-Za-z.\-]+\s*-\s*([^\n\r]+)", text, flags=re.IGNORECASE
        )
        section_name = (
            section_name_match.group(1).strip()[:180]
            if section_name_match
            else f"Section {section_number}"
        )

        official_cite_match = re.search(
            r"\bCite\s+as:\s*(\d+\s+O\.S\.\s*§?\s*[0-9A-Za-z.\-]+)", text, flags=re.IGNORECASE
        ) or re.search(r"\b\d+\s+O\.S\.\s*§?\s*[0-9A-Za-z.\-]+\b", text)
        official_cite = (
            (
                official_cite_match.group(1)
                if official_cite_match and official_cite_match.lastindex
                else official_cite_match.group(0)
            )
            if official_cite_match
            else f"Okla. Stat. {section_number}"
        )

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=section_name,
            full_text=text,
            legal_area=self._identify_legal_area(text),
            source_url=document_url,
            official_cite=official_cite,
        )

    def _extract_cite_id(self, url: str) -> str:
        match = re.search(r"[?&]CiteID=(\d+)", str(url or ""), flags=re.IGNORECASE)
        return match.group(1) if match else ""

    async def _request_text(self, url: str, headers: Dict[str, str], timeout: int) -> str:
        normalized_url = str(url or "").strip()
        direct_oscn_text = await self._request_live_oscn_text(url, headers=headers, timeout=timeout)
        if direct_oscn_text:
            return direct_oscn_text
        direct_wayback_text = await self._request_wayback_text(
            url, headers=headers, timeout=timeout
        )
        if direct_wayback_text:
            return direct_wayback_text
        heavy_fallback_for_deliver_raw = (
            str(os.getenv("STATE_SCRAPER_OK_HEAVY_FALLBACK_FOR_DELIVERDOCUMENT", "") or "")
            .strip()
            .lower()
        )
        heavy_fallback_for_deliver = heavy_fallback_for_deliver_raw in {"1", "true", "yes", "on"}
        if (
            "oscn.net/applications/oscn/deliverdocument.asp" in normalized_url.lower()
            and not heavy_fallback_for_deliver
        ):
            # DeliverDocument pages are already handled by direct live/Wayback probes
            # above. Skipping unified archival fallback here avoids repeatedly
            # invoking throttled search providers for thousands of candidates.
            return ""

        try:
            request_url = self._normalize_wayback_url(url)
            content = await self._fetch_page_content_with_archival_fallback(
                request_url,
                timeout_seconds=max(20, int(timeout)),
            )
            if not content:
                return ""
            text = content.decode("utf-8", errors="replace")
            if self._ANTI_BOT_RE.search(str(text or "")):
                return ""
            return text
        except Exception:
            return ""

    async def _request_wayback_text(self, url: str, headers: Dict[str, str], timeout: int) -> str:
        """Attempt direct Wayback replay fetches before broader fallback chains."""
        normalized_url = self._normalize_wayback_url(url)
        lower_url = normalized_url.lower()
        if "web.archive.org/web/" not in lower_url:
            return ""

        candidates = self._wayback_replay_candidates(normalized_url)
        if not candidates:
            return ""

        for candidate in candidates:
            payload = await self._fetch_wayback_replay_parser_input(
                candidate,
                timeout_seconds=max(5, min(int(timeout or 25), 25)),
                content_validator=lambda body: bool(body)
                and b"object moved" not in body.lower()
                and self._ANTI_BOT_RE.search(
                    body.decode("utf-8", errors="replace")
                )
                is None,
                media_type="text/html",
            )
            text = payload.decode("utf-8", errors="replace") if payload else ""
            if not text:
                continue
            if "object moved" in text.lower():
                continue
            if self._ANTI_BOT_RE.search(text):
                continue
            self._record_fetch_event(provider="requests_wayback_direct", success=True)
            return text

        self._record_fetch_event(provider="requests_wayback_direct", success=False)
        return ""

    async def _request_live_oscn_text(self, url: str, headers: Dict[str, str], timeout: int) -> str:
        """Fetch live OSCN statute pages without invoking broader archival recovery.

        OSCN DeliverDocument pages are ordinary HTML, but the generic fetch
        stack can spend its bounded-run budget trying Wayback/Common Crawl
        fallbacks first. This narrow fast path keeps Oklahoma health checks
        from stalling when the live official page is already reachable.
        """
        normalized_url = str(url or "").strip()
        if "oscn.net/applications/oscn/deliverdocument.asp" not in normalized_url.lower():
            return ""
        if normalized_url.lower().startswith(
            ("https://web.archive.org/", "http://web.archive.org/")
        ):
            return ""

        request_timeout = max(1, min(int(timeout or 12), 12))

        def _valid_oscn_html(payload: bytes) -> bool:
            if not payload:
                return False
            return not bool(
                self._ANTI_BOT_RE.search(payload.decode("utf-8", errors="replace"))
            )

        try:
            payload = await self._fetch_parser_input_with_transport(
                normalized_url,
                headers={
                    "User-Agent": str(headers.get("User-Agent") or "Mozilla/5.0"),
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                },
                timeout_seconds=request_timeout,
                content_validator=_valid_oscn_html,
                allow_archival_fallback=False,
                media_type="text/html",
                provider="requests_oscn_direct",
            )
        except Exception:
            return ""
        return payload.decode("utf-8", errors="replace") if payload else ""

    def official_title_url(self, title_number: Any) -> str:
        from .oklahoma_title import title_pdf_url

        return title_pdf_url(str(title_number or ""))

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Oklahoma Statutes title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"ok:title-{number.lower()}",
                    "title_number": number,
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Oklahoma Statutes Title {number} ({name}) official "
                        f"catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return (
            host == "oscn.net"
            or host.endswith(".oscn.net")
            or host == "oklegislature.gov"
            or host.endswith(".oklegislature.gov")
        )

    def _official_http_get(self, url: str, timeout_seconds: int = 8) -> bytes:
        timeout = max(2, min(int(timeout_seconds or 8), 8))
        headers = {
            "User-Agent": "ipfs-datasets-oklahoma-official-catalog/1.0",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        }
        try:
            request = urllib.request.Request(url, headers=headers)
            context = ssl.create_default_context()
            with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                return bytes(response.read() or b"")
        except Exception:
            return b""

    def _parse_official_title_links(self, html: bytes) -> Dict[str, str]:
        if not html:
            return {}

        from .oklahoma_title import title_pdf_links

        known = {number for number, _name in self.OFFICIAL_TITLES}
        return {
            number: url
            for number, _name, url in title_pdf_links(
                html.decode("utf-8", errors="replace")
            )
            if number in known and self._host_is_official(url)
        }

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official Oklahoma Statutes title."""

        del page_url
        discovered = self._parse_official_title_links(html)
        rows = self.official_title_catalog()
        for row in rows:
            live_url = discovered.get(str(row["title_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                # The static URL is an official declared frontier member, but
                # callers can distinguish it from a member observed in these
                # particular TOC bytes.  ``fetch_official`` rejects an
                # incomplete live TOC rather than treating this declaration as
                # reacquisition evidence.
                row["source_link_disposition"] = "official"
                row["frontier_member_observed"] = False
                continue
            row["frontier_member_observed"] = True
        return rows

    def fetch_official(self, code: str = "OK"):
        """Acquire the exhaustive official Oklahoma Statutes catalog.

        Live HTTPS retains the Legislature's complete-title PDF TOC.  The hook
        fails closed unless all 89 exact title members are present, and never
        returns fixture bytes or a synthetic response.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "OK").strip().upper() or "OK"
        if normalized != "OK":
            raise ValueError(f"OklahomaScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        if not self._looks_like_official_titles_html(html):
            raise RuntimeError(
                "oklahoma official catalog fetch returned no valid Legislature TOC"
            )
        discovered = self._parse_official_title_links(html)
        expected_numbers = {number for number, _name in self.OFFICIAL_TITLES}
        if len(discovered) != self.OFFICIAL_TITLE_COUNT or set(discovered) != expected_numbers:
            raise RuntimeError(
                "oklahoma official catalog enumeration rejected incomplete "
                f"89-PDF frontier ({len(discovered)} observed)"
            )
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if (
            len(rows) != self.OFFICIAL_TITLE_COUNT
            or any(row.get("frontier_member_observed") is not True for row in rows)
        ):
            raise RuntimeError(
                "oklahoma official catalog enumeration rejected incomplete "
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
        frontier = {
            "bundle_closed": True,
            "closed": True,
            "enumerator_closed": True,
            "expected_index_units": self.OFFICIAL_TITLE_COUNT,
            "method": "complete_title_pdf_toc",
            "pagination_closed": False,
            "remaining_bundle_members": [],
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": self.OFFICIAL_TITLE_COUNT,
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return OfficialFetch(
            jurisdiction_code=normalized,
            request_bytes=request,
            response_bytes=html,
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
StateScraperRegistry.register("OK", OklahomaScraper)


_NORMALIZED_STATUTE_FIELD_NAMES = {field.name for field in dataclass_fields(NormalizedStatute)}
_STATUTE_METADATA_FIELD_NAMES = {field.name for field in dataclass_fields(StatuteMetadata)}


def _statute_dedupe_key(statute: NormalizedStatute) -> str:
    primary = str(statute.statute_id or "").strip().lower()
    if primary:
        return primary
    source = str(statute.source_url or "").strip().lower()
    if source:
        return source
    return ""


def _statute_from_checkpoint_row(
    row: Dict[str, Any],
    *,
    default_state_code: str,
    default_state_name: str,
    default_code_name: str,
) -> Optional[NormalizedStatute]:
    if not isinstance(row, dict):
        return None
    kwargs: Dict[str, Any] = {}
    for name in _NORMALIZED_STATUTE_FIELD_NAMES:
        if name in row:
            kwargs[name] = row.get(name)
    metadata_payload = kwargs.get("metadata")
    if isinstance(metadata_payload, dict):
        metadata_kwargs = {
            key: metadata_payload.get(key)
            for key in _STATUTE_METADATA_FIELD_NAMES
            if key in metadata_payload
        }
        history = metadata_kwargs.get("history")
        if history is None:
            metadata_kwargs["history"] = []
        elif not isinstance(history, list):
            metadata_kwargs["history"] = [str(history)]
        kwargs["metadata"] = StatuteMetadata(**metadata_kwargs)
    elif not isinstance(metadata_payload, StatuteMetadata):
        kwargs["metadata"] = None

    kwargs["state_code"] = str(kwargs.get("state_code") or default_state_code).upper()
    kwargs["state_name"] = (
        str(kwargs.get("state_name") or default_state_name).strip() or default_state_name
    )
    kwargs["code_name"] = (
        str(kwargs.get("code_name") or default_code_name).strip() or default_code_name
    )
    kwargs["statute_id"] = str(kwargs.get("statute_id") or "").strip()
    if not kwargs["statute_id"]:
        return None
    kwargs["source_url"] = str(kwargs.get("source_url") or "").strip()
    kwargs["scraped_at"] = str(kwargs.get("scraped_at") or datetime.now().isoformat())
    kwargs["scraper_version"] = str(kwargs.get("scraper_version") or "1.0")
    kwargs["structured_data"] = dict(kwargs.get("structured_data") or {})
    return NormalizedStatute(**kwargs)


class _OklahomaCheckpoint:
    """Best-effort partial progress checkpoint for Oklahoma's long crawl."""

    def __init__(self, state_code: str) -> None:
        raw_dir = current_partial_checkpoint_run_directory()
        if not raw_dir:
            self.path: Optional[Path] = None
        else:
            self.path = (
                Path(raw_dir).expanduser().resolve() / f"STATE-{state_code.upper()}-partial.json"
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state_code = state_code.upper()
        self.interval = max(
            1, int(float(os.getenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_INTERVAL", "500") or 500))
        )
        self.last_count = 0
        self.last_write_ts = 0.0

    def load(
        self,
        *,
        default_state_name: str,
        default_code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        if not self.path or not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []
        rows = payload.get("statutes") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return []
        loaded: List[NormalizedStatute] = []
        seen_keys: Set[str] = set()
        for row in rows:
            statute = _statute_from_checkpoint_row(
                row,
                default_state_code=self.state_code,
                default_state_name=default_state_name,
                default_code_name=default_code_name,
            )
            if statute is None:
                continue
            key = _statute_dedupe_key(statute)
            if key and key in seen_keys:
                continue
            if key:
                seen_keys.add(key)
            loaded.append(statute)
            if max_statutes is not None and len(loaded) >= int(max_statutes):
                break
        self.last_count = len(loaded)
        return loaded

    def maybe_write(
        self,
        statutes: List[NormalizedStatute],
        *,
        code_name: str,
        scanned_candidates: int,
        discovered_candidates: int,
        progress: Optional[Dict[str, Any]] = None,
    ) -> None:
        count = len(statutes)
        has_progress = isinstance(progress, dict) and bool(progress)
        if not self.path or (count <= 0 and not has_progress):
            return
        if count - self.last_count < self.interval and time.time() - self.last_write_ts < 120:
            return
        self.write(
            statutes,
            code_name=code_name,
            scanned_candidates=scanned_candidates,
            discovered_candidates=discovered_candidates,
            progress=progress,
        )

    def write(
        self,
        statutes: List[NormalizedStatute],
        *,
        code_name: str,
        scanned_candidates: int,
        discovered_candidates: int,
        progress: Optional[Dict[str, Any]] = None,
    ) -> None:
        has_progress = isinstance(progress, dict) and bool(progress)
        if not self.path or (not statutes and not has_progress):
            return
        payload = {
            "state_code": self.state_code,
            "updated_at": time.time(),
            "statutes_count": len(statutes),
            "code_name": code_name,
            "scanned_candidates": int(scanned_candidates),
            "discovered_candidates": int(discovered_candidates),
            "statutes": [statute.to_dict() for statute in statutes],
        }
        if has_progress:
            payload["progress"] = dict(progress or {})
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp_path.replace(self.path)
        self.last_count = len(statutes)
        self.last_write_ts = time.time()
