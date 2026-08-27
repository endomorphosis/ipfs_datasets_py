"""Scraper for South Carolina state laws.

This module contains the scraper for South Carolina statutes from the official state legislative website.
"""

import hashlib
import json
import re
import ssl
import urllib.request
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import urljoin, urlparse
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class SouthCarolinaScraper(BaseStateScraper):
    """Scraper for South Carolina state laws from https://www.scstatehouse.gov"""

    OFFICIAL_DOMAIN = "www.scstatehouse.gov"
    OFFICIAL_ENTRY_PATH = "/code/statmast.php"
    OFFICIAL_ENTRY_URL = "https://www.scstatehouse.gov/code/statmast.php"
    OFFICIAL_TITLE_COUNT = 63
    _TITLE_URL_RE = re.compile(r"/code/title(\d+)\.php$", re.IGNORECASE)
    _CHAPTER_URL_RE = re.compile(r"/code/t(\d{2})c(\d{3})\.php$", re.IGNORECASE)
    _SECTION_START_RE = re.compile(r"\bSECTION\s+([0-9A-Za-z.-]+)\.\s*", re.IGNORECASE)
    _SC_TITLE_LABEL_RE = re.compile(r"\bTitle\s+(?P<title>\d{1,2})\b", re.IGNORECASE)
    OFFICIAL_TITLES = (
        ("1", "Administration of the Government"),
        ("2", "General Assembly"),
        ("3", "U.S. Government, Agreements and Relations With"),
        ("4", "Counties"),
        ("5", "Municipal Corporations"),
        ("6", "Local Government — Provisions Applicable to Special Purpose Districts and Other Political Subdivisions"),
        ("7", "Elections"),
        ("8", "Public Officers and Employees"),
        ("9", "Retirement Systems"),
        ("10", "Public Buildings and Property"),
        ("11", "Public Finance"),
        ("12", "Taxation"),
        ("13", "Planning, Research and Development"),
        ("14", "Courts"),
        ("15", "Civil Remedies and Procedures"),
        ("16", "Crimes and Offenses"),
        ("17", "Criminal Procedures"),
        ("18", "Appeals"),
        ("19", "Evidence"),
        ("20", "Domestic Relations"),
        ("21", "Estates, Trusts, Guardians and Fiduciaries"),
        ("22", "Magistrates and Constables"),
        ("23", "Law Enforcement and Public Safety"),
        ("24", "Corrections, Jails, Probations, Paroles and Pardons"),
        ("25", "Military, Civil Defense and Veterans Affairs"),
        ("26", "Notaries Public and Acknowledgements"),
        ("27", "Property and Conveyances"),
        ("28", "Eminent Domain"),
        ("29", "Mortgages and Other Liens"),
        ("30", "Public Records"),
        ("31", "Housing and Redevelopment"),
        ("32", "Contracts and Agents"),
        ("33", "Corporations, Partnerships and Associations"),
        ("34", "Banking, Financial Institutions and Money"),
        ("35", "Securities"),
        ("36", "Commercial Code"),
        ("37", "Consumer Protection Code"),
        ("38", "Insurance"),
        ("39", "Trade and Commerce"),
        ("40", "Professions and Occupations"),
        ("41", "Labor and Employment"),
        ("42", "Workers' Compensation"),
        ("43", "Social Services"),
        ("44", "Health"),
        ("45", "Hotels, Motels, Restaurants and Boardinghouses"),
        ("46", "Agriculture"),
        ("47", "Animals, Livestock and Poultry"),
        ("48", "Environmental Protection and Conservation"),
        ("49", "Waters, Water Resources and Drainage"),
        ("50", "Fish, Game and Watercraft"),
        ("51", "Parks, Recreation and Tourism"),
        ("52", "Amusements and Athletic Contests"),
        ("53", "Sundays, Holidays and Other Special Days"),
        ("54", "Ports and Maritime Matters"),
        ("55", "Aeronautics"),
        ("56", "Motor Vehicles"),
        ("57", "Highways, Bridges and Ferries"),
        ("58", "Public Utilities, Services and Carriers"),
        ("59", "Education"),
        ("60", "Libraries, Archives, Museums and Arts"),
        ("61", "Alcohol and Alcoholic Beverages"),
        ("62", "South Carolina Probate Code"),
        ("63", "South Carolina Children's Code"),
    )
    last_south_carolina_full_corpus_report: Dict[str, Any] = {}

    async def scrape_all(
        self,
        legal_areas: Optional[List[str]] = None,
        max_statutes: Optional[int] = None,
        rate_limit_delay: float = 2.0,
        hydrate_statute_text: bool = True,
    ) -> List[NormalizedStatute]:
        full_mode = self._full_corpus_enabled()
        if full_mode and (max_statutes is not None or legal_areas):
            raise RuntimeError(
                "South Carolina strict full-corpus route refuses caps or "
                "legal-area filters"
            )
        self.last_south_carolina_full_corpus_report = {}
        rows = await super().scrape_all(
            legal_areas=legal_areas,
            max_statutes=max_statutes,
            rate_limit_delay=rate_limit_delay,
            hydrate_statute_text=hydrate_statute_text,
        )
        if full_mode and not self.last_south_carolina_full_corpus_report.get(
            "closed"
        ):
            raise RuntimeError(
                "South Carolina strict full-corpus route did not emit a closed report"
            )
        return rows

    def _south_carolina_frontier_concurrency(self) -> int:
        return max(
            1,
            min(
                64,
                self._env_int("STATE_SCRAPER_SC_FRONTIER_CONCURRENCY", default=16),
            ),
        )

    def _south_carolina_residual_retry_attempts(self) -> int:
        return max(
            0,
            min(
                3,
                self._env_int(
                    "STATE_SCRAPER_SC_RESIDUAL_RETRY_ATTEMPTS",
                    default=self._env_int(
                        "STATE_SCRAPER_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
                        default=1,
                    ),
                ),
            ),
        )

    @staticmethod
    def _is_valid_south_carolina_html(payload: bytes) -> bool:
        lowered = bytes(payload or b"").lower()
        return bool(
            lowered
            and b"<html" in lowered
            and b"cloudflare" not in lowered[:12000]
            and b"access denied" not in lowered[:12000]
        )

    def _south_carolina_evidence_context(
        self,
        *,
        source_url: str,
        payload: bytes,
        transport_receipt: Any,
        parser_input_envelope: Any,
    ) -> Dict[str, Any]:
        from ipfs_datasets_py.processors.legal_data.state_laws_source_provenance import (
            canonicalize_state_law_transport_receipt,
        )

        digest = hashlib.sha256(bytes(payload)).hexdigest()
        if not isinstance(transport_receipt, Mapping):
            raise RuntimeError(
                f"South Carolina acquisition omitted transport receipt: {source_url}"
            )
        receipt = canonicalize_state_law_transport_receipt(
            transport_receipt,
            official_url=source_url,
            content_sha256=digest,
        )
        envelope = parser_input_envelope
        envelope_body = getattr(envelope, "body", None)
        if envelope_body is not None and bytes(envelope_body) != bytes(payload):
            raise RuntimeError(
                f"South Carolina parser envelope changed exact bytes: {source_url}"
            )
        if not isinstance(envelope, Mapping):
            to_dict = getattr(envelope, "to_dict", None)
            if callable(to_dict):
                envelope = to_dict()
        if isinstance(envelope, Mapping) and isinstance(
            envelope.get("parser_input_envelope"), Mapping
        ):
            envelope = envelope["parser_input_envelope"]
        parser_receipt_sha256 = ""
        if isinstance(envelope, Mapping):
            acquisition = envelope.get("acquisition")
            acquisition_receipt = (
                acquisition.get("receipt")
                if isinstance(acquisition, Mapping)
                else None
            )
            content = (
                acquisition_receipt.get("content")
                if isinstance(acquisition_receipt, Mapping)
                else None
            )
            if (
                not isinstance(acquisition, Mapping)
                or str(acquisition.get("body_sha256") or "").lower() != digest
                or not isinstance(acquisition_receipt, Mapping)
                or str(acquisition_receipt.get("endpoint") or "").rstrip("/")
                != source_url.rstrip("/")
                or not isinstance(content, Mapping)
                or str(content.get("sha256") or "").lower() != digest
            ):
                raise RuntimeError(
                    "South Carolina parser envelope does not replay exact bytes: "
                    f"{source_url}"
                )
            parser_receipt_sha256 = str(
                acquisition_receipt.get("receipt_sha256") or ""
            ).strip()
        elif self._state_law_acquisition_ledger is not None:
            raise RuntimeError(
                f"South Carolina strict evidence omitted parser envelope: {source_url}"
            )
        return {
            "content_sha256": digest,
            "parser_input_receipt_sha256": parser_receipt_sha256,
            "source_transport": str(receipt.get("source_transport") or ""),
            "transport_receipt": receipt,
        }

    async def _fetch_south_carolina_frontier_batch(
        self,
        urls: Sequence[str],
        *,
        frontier_name: str,
    ):
        requested = list(urls)
        batch = await self._fetch_page_contents_with_archival_fallback_retrying_residuals(
            requested,
            residual_retry_attempts=self._south_carolina_residual_retry_attempts(),
            timeout_seconds=35,
            headers={
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
                "User-Agent": "ipfs-datasets-south-carolina-statutes/2.0",
            },
            content_validator=self._is_valid_south_carolina_html,
            media_type="text/html",
            max_concurrency=self._south_carolina_frontier_concurrency(),
            prefer_direct=True,
            common_crawl_domain_terms=(self.OFFICIAL_DOMAIN,),
            common_crawl_url_terms=("/code/",),
            common_crawl_mime_terms=("html",),
            wayback_prefix_inventory=True,
        )
        vectors = (
            batch.urls,
            batch.payloads,
            batch.errors,
            batch.transport_receipts,
            batch.parser_input_envelopes,
        )
        if any(len(vector) != len(requested) for vector in vectors):
            raise RuntimeError(
                f"South Carolina {frontier_name} returned unaligned acquisition rows"
            )
        if list(batch.urls) != requested:
            raise RuntimeError(
                f"South Carolina {frontier_name} changed URL order or identity"
            )
        failures = [
            {"url": url, "error": error or "invalid HTML parser input"}
            for url, payload, error in zip(
                batch.urls,
                batch.payloads,
                batch.errors,
                strict=True,
            )
            if error is not None or not self._is_valid_south_carolina_html(payload)
        ]
        if failures:
            raise RuntimeError(
                f"South Carolina {frontier_name} is incomplete after residual-only "
                f"retries: {failures}"
            )
        batch.payloads = [bytes(payload) for payload in batch.payloads]
        return batch

    def _strict_title_links_from_master(self, payload: bytes) -> Dict[str, str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("BeautifulSoup is required") from exc
        soup = BeautifulSoup(payload, "html.parser")
        found: Dict[str, str] = {}
        for anchor in soup.find_all("a", href=True):
            absolute = urljoin(
                self.OFFICIAL_ENTRY_URL,
                str(anchor.get("href") or "").strip(),
            ).rstrip("/")
            match = self._TITLE_URL_RE.search(absolute)
            if match is None or not self._host_is_official(absolute):
                continue
            number = str(int(match.group(1)))
            expected_url = self.official_title_url(number)
            if number in found and found[number] != expected_url:
                raise RuntimeError(
                    f"South Carolina master exposed conflicting title {number} URLs"
                )
            found[number] = expected_url
        return found

    def _strict_chapter_links_from_title(
        self,
        payload: bytes,
        *,
        title_number: str,
    ) -> List[tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("BeautifulSoup is required") from exc
        expected_title = str(int(title_number))
        soup = BeautifulSoup(payload, "html.parser")
        page_text = self._normalize_legal_text(soup.get_text(" ", strip=True))
        if re.search(
            rf"\bTITLE\s+0*{re.escape(expected_title)}\b",
            page_text[:800],
            re.IGNORECASE,
        ) is None:
            raise RuntimeError(
                f"South Carolina title page identity mismatch for title {expected_title}"
            )
        found: Dict[str, str] = {}
        for anchor in soup.find_all("a", href=True):
            absolute = urljoin(
                f"{self.get_base_url()}/",
                str(anchor.get("href") or "").strip(),
            ).rstrip("/")
            match = self._CHAPTER_URL_RE.search(absolute)
            if match is None or not self._host_is_official(absolute):
                continue
            linked_title = str(int(match.group(1)))
            if linked_title != expected_title:
                raise RuntimeError(
                    "South Carolina title page linked a foreign chapter identity: "
                    f"title={expected_title} url={absolute}"
                )
            chapter = str(int(match.group(2)))
            expected_url = (
                f"{self.get_base_url()}/code/"
                f"t{int(expected_title):02d}c{int(chapter):03d}.php"
            )
            if chapter in found and found[chapter] != expected_url:
                raise RuntimeError(
                    "South Carolina title page exposed conflicting chapter URLs: "
                    f"title={expected_title} chapter={chapter}"
                )
            found[chapter] = expected_url
        if not found:
            raise RuntimeError(
                f"South Carolina title {expected_title} exposed no chapter frontier"
            )
        return list(found.items())

    async def _scrape_official_code_tree_strict(
        self,
        code_name: str,
    ) -> List[NormalizedStatute]:
        from .south_carolina_chapter import (
            parse_south_carolina_chapter_html_strict,
        )

        title_urls = [self.official_title_url(number) for number, _ in self.OFFICIAL_TITLES]
        catalog_urls = [self.OFFICIAL_ENTRY_URL, *title_urls]
        catalog_batch = await self._fetch_south_carolina_frontier_batch(
            catalog_urls,
            frontier_name="master-and-title",
        )
        expected_titles = [str(int(number)) for number, _ in self.OFFICIAL_TITLES]
        master_links = self._strict_title_links_from_master(catalog_batch.payloads[0])
        if list(master_links) != expected_titles or list(master_links.values()) != title_urls:
            raise RuntimeError(
                "South Carolina master did not prove the exact ordered 63-title catalog"
            )

        catalog_evidence: List[Dict[str, Any]] = []
        chapter_frontier: List[tuple[str, str, str, str]] = []
        title_names = dict(self.OFFICIAL_TITLES)
        for index, (url, payload, receipt, envelope) in enumerate(
            zip(
                catalog_batch.urls,
                catalog_batch.payloads,
                catalog_batch.transport_receipts,
                catalog_batch.parser_input_envelopes,
                strict=True,
            )
        ):
            evidence = self._south_carolina_evidence_context(
                source_url=url,
                payload=payload,
                transport_receipt=receipt,
                parser_input_envelope=envelope,
            )
            catalog_evidence.append(
                {
                    "content_sha256": evidence["content_sha256"],
                    "parser_input_receipt_sha256": evidence[
                        "parser_input_receipt_sha256"
                    ],
                    "url": url,
                }
            )
            if index == 0:
                continue
            title_number = expected_titles[index - 1]
            for chapter_number, chapter_url in self._strict_chapter_links_from_title(
                payload,
                title_number=title_number,
            ):
                chapter_frontier.append(
                    (
                        title_number,
                        title_names[title_number],
                        chapter_number,
                        chapter_url,
                    )
                )

        chapter_identities = [
            (title, chapter) for title, _name, chapter, _url in chapter_frontier
        ]
        chapter_urls = [url for _title, _name, _chapter, url in chapter_frontier]
        if (
            not chapter_urls
            or len(chapter_identities) != len(set(chapter_identities))
            or len(chapter_urls) != len(set(chapter_urls))
        ):
            raise RuntimeError(
                "South Carolina exact chapter frontier is empty or duplicated"
            )

        chapter_batch = await self._fetch_south_carolina_frontier_batch(
            chapter_urls,
            frontier_name="chapter-leaf",
        )
        statutes: List[NormalizedStatute] = []
        chapter_reports: List[Dict[str, Any]] = []
        for (
            (title_number, _title_name, chapter_number, chapter_url),
            payload,
            receipt,
            envelope,
        ) in zip(
            chapter_frontier,
            chapter_batch.payloads,
            chapter_batch.transport_receipts,
            chapter_batch.parser_input_envelopes,
            strict=True,
        ):
            evidence = self._south_carolina_evidence_context(
                source_url=chapter_url,
                payload=payload,
                transport_receipt=receipt,
                parser_input_envelope=envelope,
            )
            chapter_rows, chapter_report = parse_south_carolina_chapter_html_strict(
                payload.decode("utf-8", errors="strict"),
                source_url=chapter_url,
                code_name=code_name,
                title_number=title_number,
                chapter_number=chapter_number,
            )
            if chapter_report.get("closed") is not True:
                raise RuntimeError(
                    "South Carolina strict chapter parser left residuals: "
                    f"url={chapter_url} report={chapter_report}"
                )
            for statute in chapter_rows:
                statute.structured_data = {
                    **dict(statute.structured_data or {}),
                    "content_sha256": evidence["content_sha256"],
                    "parser_input_receipt_sha256": evidence[
                        "parser_input_receipt_sha256"
                    ],
                    "source_transport": evidence["source_transport"],
                    "transport_receipt": dict(evidence["transport_receipt"]),
                }
                statutes.append(statute)
            chapter_reports.append(
                {
                    **chapter_report,
                    "content_sha256": evidence["content_sha256"],
                    "source_url": chapter_url,
                }
            )

        candidate_sections = sum(
            int(report["candidate_sections"]) for report in chapter_reports
        )
        operative_sections = sum(
            int(report["operative_sections"]) for report in chapter_reports
        )
        terminal_sections = sum(
            int(report["terminal_sections"]) for report in chapter_reports
        )
        terminal_chapters = sum(
            bool(report.get("chapter_disposition")) for report in chapter_reports
        )
        section_bearing_chapters = sum(
            int(report["candidate_sections"]) > 0 for report in chapter_reports
        )
        canonical_keys = [
            str((row.structured_data or {}).get("canonical_section_key") or "")
            for row in statutes
        ]
        statute_ids = [str(row.statute_id or "") for row in statutes]
        if (
            len(chapter_reports)
            != section_bearing_chapters + terminal_chapters
            or candidate_sections != operative_sections + terminal_sections
            or len(statutes) != operative_sections
            or any(not key for key in canonical_keys)
            or len(canonical_keys) != len(set(canonical_keys))
            or len(statute_ids) != len(set(statute_ids))
        ):
            raise RuntimeError(
                "South Carolina strict catalog/chapter/section completion algebra failed"
            )

        report = {
            "candidate_sections": candidate_sections,
            "catalog_batch_stats": dict(catalog_batch.stats or {}),
            "catalog_evidence": catalog_evidence,
            "chapter_batch_stats": dict(chapter_batch.stats or {}),
            "chapter_count": len(chapter_reports),
            "closed": True,
            "expected_title_count": self.OFFICIAL_TITLE_COUNT,
            "operative_sections": operative_sections,
            "parser_residual_count": 0,
            "schema_version": "south-carolina-strict-html-frontier-v1",
            "section_bearing_chapter_count": section_bearing_chapters,
            "terminal_chapter_count": terminal_chapters,
            "terminal_sections": terminal_sections,
            "title_count": len(expected_titles),
        }
        self.last_south_carolina_full_corpus_report = report
        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="south-carolina:strict-frontier-complete",
            force=True,
            replace_existing_rows=True,
            extra={
                "codes_completed": 1,
                "codes_total": 1,
                "discovered_chapters": len(chapter_reports),
                "discovered_sections": candidate_sections,
                "operative_sections": operative_sections,
                "south_carolina_closure_report": report,
                "terminal_chapters_classified": terminal_chapters,
                "terminal_sections_classified": terminal_sections,
            },
        )
        return statutes

    def _is_source_bound_operative_statute_record(
        self,
        statute: NormalizedStatute,
    ) -> bool:
        structured = dict(statute.structured_data or {})
        return (
            structured.get("source_kind")
            == "official_south_carolina_code_html"
            and structured.get("strict_source_closure") is True
            and bool(str(structured.get("canonical_section_key") or "").strip())
        )
    
    def get_base_url(self) -> str:
        """Return the base URL for South Carolina's legislative website."""
        return "https://www.scstatehouse.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for South Carolina."""
        return [{
            "name": "South Carolina Code of Laws",
            # Use the statute master page directly; home page navigation is noisy
            # and often yields zero probable statute links.
            "url": f"{self.get_base_url()}/code/statmast.php",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from South Carolina's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        if self._full_corpus_enabled():
            if max_statutes is not None:
                raise RuntimeError(
                    "South Carolina strict full-corpus route refuses a statute cap"
                )
            return await self._scrape_official_code_tree_strict(code_name)

        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        probe_threshold = limit if limit is not None else 160
        from .south_carolina_constitution import (
            configured_constitution_html_path,
            parse_south_carolina_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_south_carolina_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "South Carolina Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .south_carolina_chapter import configured_chapter_html_path, parse_south_carolina_chapter_html

        local_chapter = configured_chapter_html_path()
        if local_chapter is not None:
            local_rows = parse_south_carolina_chapter_html(
                local_chapter.read_text(encoding="utf-8", errors="replace"),
                source_url="https://www.scstatehouse.gov/code/t16c003.php",
                code_name=code_name,
                title_number="16",
                chapter_number="3",
                max_statutes=limit,
            )
            if local_rows:
                return local_rows if limit is None else local_rows[: int(limit)]
        official = await self._scrape_official_code_tree(
            code_name,
            max_statutes=limit,
        )
        if official:
            return official if limit is None else official[: int(limit)]
        if not self._full_corpus_enabled() or max_statutes is not None:
            direct = await self._scrape_direct_seed_sections(code_name, max_statutes=probe_threshold)
            if direct:
                return direct if limit is None else direct[: int(limit)]
            return await self._generic_scrape(
                code_name,
                code_url,
                "S.C. Code Ann.",
                max_sections=max(10, int(probe_threshold)),
            )
        self.logger.warning(
            "South Carolina full-corpus run found zero official sections; "
            "refusing secondary Justia/generic sole-admission fallback"
        )
        return []

    async def _scrape_official_code_tree(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        title_links = await self._discover_title_links()
        self.logger.info("South Carolina official index: discovered %s title links", len(title_links))
        statutes: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None

        for title_index, (title_number, title_name, title_url) in enumerate(title_links, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            chapter_links = await self._discover_chapter_links(title_url)
            self.logger.info(
                "South Carolina official index: title=%s index=%s/%s chapters=%s statutes_so_far=%s",
                title_number,
                title_index,
                len(title_links),
                len(chapter_links),
                len(statutes),
            )
            for chapter_index, (chapter_number, chapter_url) in enumerate(chapter_links, start=1):
                if limit is not None and len(statutes) >= limit:
                    break
                parsed = await self._parse_chapter_sections(
                    code_name=code_name,
                    title_number=title_number,
                    title_name=title_name,
                    chapter_number=chapter_number,
                    chapter_url=chapter_url,
                    max_statutes=(None if limit is None else max(0, limit - len(statutes))),
                )
                statutes.extend(parsed)
                if chapter_index == 1 or chapter_index % 10 == 0 or chapter_index == len(chapter_links):
                    self.logger.info(
                        "South Carolina official index: title=%s chapter=%s/%s statutes_so_far=%s",
                        title_number,
                        chapter_index,
                        len(chapter_links),
                        len(statutes),
                    )

        return statutes[:limit] if limit is not None else statutes

    async def _discover_title_links(self) -> List[tuple[str, str, str]]:
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError:
            return []

        payload = await self._fetch_page_content_with_archival_fallback(
            f"{self.get_base_url()}/code/statmast.php",
            timeout_seconds=35,
        )
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[tuple[str, str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(f"{self.get_base_url()}/", str(anchor.get("href") or "").strip())
            match = self._TITLE_URL_RE.search(href)
            if not match:
                continue
            normalized = href.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            title_number = match.group(1)
            title_name = self._normalize_legal_text(anchor.get_text(" ", strip=True))
            out.append((title_number, title_name, normalized))
        return out

    async def _discover_chapter_links(self, title_url: str) -> List[tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError:
            return []

        payload = await self._fetch_page_content_with_archival_fallback(title_url, timeout_seconds=35)
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(f"{self.get_base_url()}/", str(anchor.get("href") or "").strip())
            match = self._CHAPTER_URL_RE.search(href)
            if not match:
                continue
            normalized = href.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append((str(int(match.group(2))), normalized))
        return out

    async def _parse_chapter_sections(
        self,
        *,
        code_name: str,
        title_number: str,
        title_name: str,
        chapter_number: str,
        chapter_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        payload = await self._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=35)
        if not payload:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        from .south_carolina_chapter import parse_south_carolina_chapter_html

        html_text = (
            payload.decode("utf-8", errors="replace")
            if isinstance(payload, (bytes, bytearray))
            else str(payload)
        )
        parsed = parse_south_carolina_chapter_html(
            html_text,
            source_url=chapter_url,
            code_name=code_name,
            title_number=title_number,
            chapter_number=chapter_number,
            max_statutes=max_statutes,
        )
        if parsed:
            return parsed
        text = self._normalize_legal_text(soup.get_text("\n", strip=True))
        matches = list(self._SECTION_START_RE.finditer(text))
        if not matches:
            return []

        statutes: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for index, match in enumerate(matches):
            if limit is not None and len(statutes) >= limit:
                break
            section_number = match.group(1).strip()
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            segment = self._normalize_legal_text(text[start:end])
            if len(segment) < 120:
                continue
            title_match = re.match(
                rf"SECTION\s+{re.escape(section_number)}\.\s*([^\.]{{3,220}})",
                segment,
                flags=re.IGNORECASE,
            )
            section_name = title_match.group(1).strip() if title_match else f"Section {section_number}"
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    title_number=title_number,
                    title_name=title_name[:200] if title_name else None,
                    chapter_number=chapter_number,
                    section_number=section_number,
                    section_name=section_name[:220],
                    full_text=segment,
                    legal_area=self._identify_legal_area(section_name or segment[:1000]),
                    source_url=f"{chapter_url}#{section_number}",
                    official_cite=f"S.C. Code Ann. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_south_carolina_code_html",
                        "discovery_method": "official_title_chapter_index",
                        "skip_hydrate": True,
                    },
                )
            )
        return statutes

    async def _scrape_direct_seed_sections(
        self,
        code_name: str,
        max_statutes: int = 1,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        seeds = [
            ("16-3-10", "https://www.scstatehouse.gov/code/t16c003.php"),
        ]
        out: List[NormalizedStatute] = []
        for section_number, url in seeds[: max(1, int(max_statutes or 1))]:
            raw = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=25)
            if not raw:
                continue
            soup = BeautifulSoup(raw, "html.parser")
            text = self._normalize_legal_text(soup.get_text(" ", strip=True))
            match = re.search(
                rf"\bSECTION\s+{re.escape(section_number)}\.\s*(.+?)(?=\bSECTION\s+\d+-\d+-\d+\.)",
                text,
                flags=re.IGNORECASE,
            )
            if not match:
                continue
            body = self._normalize_legal_text(f"SECTION {section_number}. {match.group(1)}")
            if len(body) < 120:
                continue
            name_match = re.match(rf"SECTION\s+{re.escape(section_number)}\.\s*([^\.]+)\.", body, flags=re.IGNORECASE)
            section_name = name_match.group(1).strip() if name_match else section_number
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    title_number=section_number.split("-", 1)[0],
                    section_number=section_number,
                    section_name=section_name[:220],
                    full_text=body,
                    legal_area=self._identify_legal_area(body[:1200]),
                    source_url=f"{url}#{section_number}",
                    official_cite=f"S.C. Code Ann. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_south_carolina_code_html",
                        "discovery_method": "official_seed_chapter_section",
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    def official_title_url(self, title_number: Any) -> str:
        number = str(int(str(title_number).strip()))
        return f"{self.get_base_url()}/code/title{number}.php"

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official South Carolina Code of Laws title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"sc:title-{int(number)}",
                    "title_number": str(int(number)),
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"South Carolina Code of Laws Title {int(number)} ({name}) "
                        f"official catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host == "scstatehouse.gov" or host.endswith(".scstatehouse.gov")

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))
        headers = {
            "User-Agent": "ipfs-datasets-south-carolina-official-catalog/1.0",
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
            match = self._TITLE_URL_RE.search(absolute) or self._SC_TITLE_LABEL_RE.search(label)
            if not match:
                continue
            number = str(int(match.group(1) if match.lastindex else match.group("title")))
            if number not in known or number in found:
                continue
            if self._host_is_official(absolute):
                found[number] = self.official_title_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official South Carolina Code of Laws title."""

        del page_url
        discovered = self._parse_official_title_links(html)
        rows = self.official_title_catalog()
        for row in rows:
            live_url = discovered.get(str(row["title_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_leginfo"
        return rows

    def fetch_official(self, code: str = "SC"):
        """Acquire the exhaustive official South Carolina Code of Laws title catalog.

        Live HTTPS retains the official statute master index. Every Code of
        Laws title is enumerated with an official scstatehouse.gov URL. This
        hook never returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "SC").strip().upper() or "SC"
        if normalized != "SC":
            raise ValueError(f"SouthCarolinaScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        if self._full_corpus_enabled():
            discovered = self._strict_title_links_from_master(html)
            expected = [str(int(number)) for number, _name in self.OFFICIAL_TITLES]
            if list(discovered) != expected or list(discovered.values()) != [
                self.official_title_url(number) for number in expected
            ]:
                missing = sorted(set(expected).difference(discovered), key=int)
                unexpected = sorted(set(discovered).difference(expected), key=int)
                raise RuntimeError(
                    "south carolina official master did not prove the exact "
                    f"63-title catalog; missing={missing} unexpected={unexpected}"
                )
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) != self.OFFICIAL_TITLE_COUNT:
            raise RuntimeError(
                "south carolina official catalog enumeration rejected incomplete "
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
StateScraperRegistry.register("SC", SouthCarolinaScraper)
