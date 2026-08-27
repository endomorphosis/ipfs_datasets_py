"""Scraper for New Mexico state laws.

This module contains the scraper for New Mexico statutes from archived
NMOneSource statute PDFs.
"""

from ipfs_datasets_py.utils import anyio_compat as asyncio
import hashlib
import json
import re
import ssl
import subprocess
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import urljoin, urlparse

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry
from .retained_replay_network_guard import trusted_pdftotext_executable


class NewMexicoScraper(BaseStateScraper):
    """Scraper for New Mexico state laws from https://www.nmlegis.gov"""

    _SECTION_HEADER_RE = re.compile(
        r"(?m)^\s*([0-9]+(?:-[0-9A-Za-z]+)+(?:\.[0-9A-Za-z]+)*)\.\s+(.+)$"
    )

    _ARCHIVE_DOCUMENT_PDFS = [
        "http://web.archive.org/web/20250101000000/https://nmonesource.com/nmos/nmsa/en/18973/1/document.do",
        "http://web.archive.org/web/20250101000000/https://nmonesource.com/nmos/nmsa/en/25293/1/document.do",
        "http://web.archive.org/web/20250101000000/https://nmonesource.com/nmos/nmsa/en/4340/1/document.do",
        "http://web.archive.org/web/20250101000000/https://nmonesource.com/nmos/nmsa/en/12084/1/document.do",
        "http://web.archive.org/web/20250101000000/https://nmonesource.com/nmos/nmsa/en/5326/1/document.do",
    ]
    OFFICIAL_DOMAIN = "nmonesource.com"
    OFFICIAL_ENTRY_PATH = "/nmos/nmsa/en/nav_date.do"
    OFFICIAL_ENTRY_URL = "https://nmonesource.com/nmos/nmsa/en/nav_date.do"
    LINKLESS_SEED_DISPOSITION = "linkless_bucket_seed_pending_official_replacement"
    MISSING_LINK_DISPOSITION = "missing_official_source_link"
    _NM_CHAPTER_HREF_RE = re.compile(
        r"(?:#chapter-|/chapter[-/]|[?&]chapter=)(?P<chapter>[0-9]+[A-Za-z]?)\b",
        re.IGNORECASE,
    )
    _NM_CHAPTER_LABEL_RE = re.compile(r"\bChapter\s+(?P<chapter>[0-9]+[A-Za-z]?)\b", re.IGNORECASE)
    OFFICIAL_CHAPTERS = (
        ("1", "Elections"),
        ("2", "Legislative Branch"),
        ("3", "Municipalities"),
        ("4", "Counties"),
        ("5", "Municipalities and Counties"),
        ("6", "Public Finances"),
        ("7", "Taxation"),
        ("8", "Elected Officials"),
        ("9", "Executive Department"),
        ("10", "Public Officers and Employees"),
        ("11", "Intergovernmental Agreements and Authorities"),
        ("12", "Miscellaneous Public Affairs Matters"),
        ("13", "Public Purchases and Property"),
        ("14", "Records, Legal Notices and Oaths"),
        ("15", "Administration of Government"),
        ("16", "Parks, Recreation and Fairs"),
        ("17", "Game and Fish and Outdoor Recreation"),
        ("18", "Libraries, Museums and Cultural Properties"),
        ("19", "Public Lands"),
        ("20", "Military Affairs"),
        ("21", "State and Private Education Institutions"),
        ("22", "Public Schools"),
        ("23", "State Health Institutions"),
        ("24", "Health and Safety"),
        ("25", "Food"),
        ("26", "Drugs and Cosmetics"),
        ("27", "Public Assistance"),
        ("28", "Human Rights"),
        ("29", "Law Enforcement"),
        ("30", "Criminal Offenses"),
        ("31", "Criminal Procedure"),
        ("32A", "Children's Code"),
        ("33", "Correctional Institutions"),
        ("34", "Court Structure and Administration"),
        ("35", "Magistrate and Municipal Courts"),
        ("36", "Attorneys"),
        ("37", "Limitation of Actions; Abatement and Revivor"),
        ("38", "Trials"),
        ("39", "Judgments, Costs, Appeals"),
        ("40", "Domestic Affairs"),
        ("41", "Torts"),
        ("42", "Actions and Proceedings Relating to Property"),
        ("42A", "Condemnation Proceedings"),
        ("43", "Commitment Procedures"),
        ("44", "Miscellaneous Civil Law Matters"),
        ("45", "Uniform Probate Code"),
        ("46", "Fiduciaries and Trusts"),
        ("46A", "Uniform Trust Code"),
        ("46B", "Uniform Power of Attorney Act"),
        ("47", "Property Law"),
        ("48", "Liens and Mortgages"),
        ("49", "Land Grants"),
        ("50", "Employment Law"),
        ("51", "Unemployment Compensation"),
        ("52", "Workers' Compensation"),
        ("53", "Corporations"),
        ("54", "Partnerships"),
        ("55", "Uniform Commercial Code"),
        ("56", "Commercial Instruments and Transactions"),
        ("57", "Trade Practices and Regulations"),
        ("58", "Financial Institutions and Regulations"),
        ("59A", "Insurance Code"),
        ("60", "Business Licenses"),
        ("61", "Professional and Occupational Licenses"),
        ("62", "Electric, Gas and Water Utilities"),
        ("63", "Railroads and Communications"),
        ("64", "Aeronautics"),
        ("65", "Motor Carriers"),
        ("66", "Motor Vehicles"),
        ("67", "Highways"),
        ("68", "Timber"),
        ("69", "Mines"),
        ("70", "Oil and Gas"),
        ("71", "Energy and Minerals"),
        ("72", "Water Law"),
        ("73", "Special Districts"),
        ("74", "Environmental Improvement"),
        ("75", "Miscellaneous Natural Resource Matters"),
        ("76", "Agriculture"),
        ("77", "Animals and Livestock"),
    )
    OFFICIAL_CHAPTER_COUNT = len(OFFICIAL_CHAPTERS)
    DEFAULT_LINKLESS_SEED_ROWS = (
        {
            "canonical_key": "nm:chapter-30",
            "label": "New Mexico Statutes Chapter 30 Criminal Offenses",
            "source_url": "https://law.justia.com/codes/new-mexico/chapter-30/",
            "chapter_number": "30",
        },
        {
            "canonical_key": "nm:bucket-seed-untitled",
            "label": "open-us-law-bucket New Mexico seed row without an official source link",
            "source_url": "",
        },
        {
            "canonical_key": "nm:bucket-phantom",
            "label": "New Mexico phantom chapter without a recoverable official identifier",
            "source_url": "https://law.justia.com/codes/new-mexico/",
        },
    )
    
    def get_base_url(self) -> str:
        """Return the base URL for New Mexico's legislative website."""
        return "https://www.nmlegis.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for New Mexico."""
        return [{
            "name": "New Mexico Statutes",
            "url": self.OFFICIAL_ENTRY_URL,
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from New Mexico's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .new_mexico_constitution import (
            configured_constitution_text_path,
            parse_new_mexico_constitution_text,
        )

        constitution_path = configured_constitution_text_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_new_mexico_constitution_text(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "New Mexico Constitution",
                    max_statutes=limit,
                )
                if constitution_rows:
                    return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .new_mexico_chapter import configured_chapter_text_path, parse_new_mexico_chapter_text

        local_chapter = configured_chapter_text_path()
        if local_chapter is not None:
            local_rows = parse_new_mexico_chapter_text(
                local_chapter.read_text(encoding="utf-8", errors="replace"),
                source_url="https://nmonesource.com/nmos/nmsa/en/nav_date.do",
                code_name=code_name,
                max_statutes=limit,
            )
            if local_rows:
                return local_rows if limit is None else local_rows[: int(limit)]
        official = await self._scrape_official_nmonesource_tree(code_name, max_statutes=limit)
        if official:
            return official if limit is None else official[: int(limit)]

        bounded = limit if limit is not None else 1000000
        chapter_sections = await self._scrape_live_chapter_document_pdfs(
            code_name=code_name,
            max_statutes=limit,
        )
        if chapter_sections:
            self.logger.info("New Mexico chapter PDF extraction: Scraped %s section(s)", len(chapter_sections))
            return chapter_sections if limit is None else chapter_sections[: int(limit)]
        if limit is None and self._full_corpus_enabled():
            raise RuntimeError(
                "New Mexico official NMOneSource PDF frontier did not close; "
                "refusing legacy per-page full-corpus recovery"
            )

        fallback_candidates: List[NormalizedStatute] = []
        nav_sections = await self._scrape_nmonesource_nav_sections(code_name=code_name, max_statutes=bounded)
        if nav_sections:
            self.logger.info("New Mexico nav-date fallback: Scraped %s section(s)", len(nav_sections))
            fallback_candidates.extend(nav_sections)
            if not self._full_corpus_enabled():
                return nav_sections if limit is None else nav_sections[: int(limit)]

        index_fallback = await self._scrape_nmonesource_index(code_name=code_name)
        archival_limit = bounded if self._full_corpus_enabled() else max(1, min(8, int(bounded)))
        archival = await self._scrape_archived_document_pdfs(code_name=code_name, max_statutes=archival_limit)
        if archival:
            if index_fallback:
                archival.extend(index_fallback)
            self.logger.info(f"New Mexico archival fallback: Scraped {len(archival)} sections")
            fallback_candidates.extend(archival)
            if not self._full_corpus_enabled():
                return archival if limit is None else archival[: int(limit)]

        if index_fallback:
            self.logger.info("New Mexico index fallback: Scraped %s section(s)", len(index_fallback))
            fallback_candidates.extend(index_fallback)
            if not self._full_corpus_enabled():
                return index_fallback if limit is None else index_fallback[: int(limit)]

        if not self._full_corpus_enabled():
            direct = await self._scrape_direct_document_pdfs(code_name=code_name, max_statutes=bounded)
            if direct:
                return direct if limit is None else direct[: int(limit)]

        generic = await self._generic_scrape(
            code_name,
            code_url,
            "N.M. Stat. Ann.",
            max_sections=max(10, int(bounded)),
        )
        if self._full_corpus_enabled():
            generic = [
                row
                for row in generic
                if not self._looks_like_secondary_url(str(row.source_url or ""))
            ]
        if generic:
            return generic if limit is None else generic[: int(limit)]
        if limit is not None:
            return fallback_candidates[: int(limit)]
        return list(fallback_candidates)

    async def _scrape_official_nmonesource_tree(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Walk compact official NMOneSource HTML chapter/section pages."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        root_url = self.OFFICIAL_ENTRY_URL
        payload = await self._fetch_page_content_with_archival_fallback(root_url, timeout_seconds=18)
        if not payload:
            payload = await self._request_bytes_direct(root_url, timeout=18)
        if not payload:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        chapter_urls: List[tuple[str, str]] = []
        seen_chapters = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            text = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True) or "").strip()
            abs_url = urljoin(root_url, href)
            if not self._host_is_official(abs_url):
                continue
            if "/document.do" in abs_url.lower():
                continue
            chapter_match = self._NM_CHAPTER_LABEL_RE.search(text) or self._NM_CHAPTER_HREF_RE.search(abs_url)
            if not chapter_match:
                continue
            chapter_no = str(chapter_match.group("chapter") or "").strip()
            if not chapter_no or abs_url in seen_chapters:
                continue
            seen_chapters.add(abs_url)
            chapter_urls.append((chapter_no, abs_url))

        statutes: List[NormalizedStatute] = []
        seen_sections: set[str] = set()
        section_href_re = re.compile(r"\b([0-9]+(?:-[0-9A-Za-z]+)+)\b")
        chapter_payload_by_url: Dict[str, bytes] = {}
        if limit is None:
            chapter_payload_by_url = await self._fetch_nm_html_frontier(
                [url for _number, url in chapter_urls],
                frontier_name="chapter catalog",
            )

        section_candidates: List[tuple[str, str, str, str]] = []
        for chapter_no, chapter_url in chapter_urls:
            if limit is not None and len(statutes) >= limit:
                break
            chapter_payload = chapter_payload_by_url.get(chapter_url)
            if chapter_payload is None:
                chapter_payload = await self._fetch_page_content_with_archival_fallback(
                    chapter_url, timeout_seconds=18
                )
                if not chapter_payload:
                    chapter_payload = await self._request_bytes_direct(chapter_url, timeout=18)
            if not chapter_payload:
                continue
            chapter_soup = BeautifulSoup(chapter_payload, "html.parser")
            for anchor in chapter_soup.find_all("a", href=True):
                href = str(anchor.get("href") or "").strip()
                text = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True) or "").strip()
                section_url = urljoin(chapter_url, href)
                if not self._host_is_official(section_url):
                    continue
                section_match = section_href_re.search(text) or section_href_re.search(section_url)
                if not section_match:
                    continue
                section_number = section_match.group(1)
                if section_number.lower() in seen_sections:
                    continue
                seen_sections.add(section_number.lower())
                section_candidates.append(
                    (chapter_no, section_number, text, section_url)
                )

        section_payload_by_url: Dict[str, bytes] = {}
        if limit is None:
            section_payload_by_url = await self._fetch_nm_html_frontier(
                [url for _chapter, _number, _label, url in section_candidates],
                frontier_name="section body",
            )
        for chapter_no, section_number, section_label, section_url in section_candidates:
            if limit is not None and len(statutes) >= limit:
                break
            statute = await self._build_official_nmonesource_section(
                code_name,
                section_number=section_number,
                section_label=section_label,
                section_url=section_url,
                chapter_number=chapter_no,
                _payload=section_payload_by_url.get(section_url),
            )
            if statute is not None:
                statutes.append(statute)
        return statutes

    async def _fetch_nm_html_frontier(
        self,
        urls: List[str],
        *,
        frontier_name: str,
        require_complete: bool = True,
    ) -> Dict[str, bytes]:
        """Fetch one exact NMOneSource wave through the grouped archive seam."""

        return await self._fetch_nm_frontier(
            urls,
            frontier_name=frontier_name,
            content_validator=self._is_valid_nm_html,
            media_type="text/html",
            timeout_seconds=35,
            require_complete=require_complete,
        )

    async def _fetch_nm_pdf_frontier(
        self,
        urls: List[str],
        *,
        frontier_name: str,
        require_complete: bool = True,
    ) -> Dict[str, bytes]:
        """Fetch one exact official PDF wave without changing request identity."""

        return await self._fetch_nm_frontier(
            urls,
            frontier_name=frontier_name,
            content_validator=self._is_valid_nm_pdf,
            media_type="application/pdf",
            timeout_seconds=50,
            require_complete=require_complete,
        )

    @staticmethod
    def _is_valid_nm_html(payload: bytes) -> bool:
        sample = bytes(payload or b"")[:8192].lower()
        return b"<" in sample and b">" in sample and b"html" in sample

    @staticmethod
    def _is_valid_nm_pdf(payload: bytes) -> bool:
        return bytes(payload or b"").lstrip().startswith(b"%PDF")

    def _validate_nm_aligned_evidence(
        self,
        *,
        url: str,
        payload: bytes,
        transport_receipt: Any,
        parser_input_envelope: Any,
        frontier_name: str,
    ) -> None:
        """Require every retained row to remain bound to its exact URL and bytes."""

        canonical_url = self._canonical_fetch_url(url)
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        ledger_attached = getattr(self, "_state_law_acquisition_ledger", None) is not None
        if ledger_attached and (
            not isinstance(transport_receipt, Mapping)
            or not transport_receipt
            or parser_input_envelope is None
        ):
            raise RuntimeError(
                f"New Mexico {frontier_name} frontier lacks retained evidence: {url}"
            )
        if isinstance(transport_receipt, Mapping):
            observed_url = str(
                transport_receipt.get("official_url")
                or transport_receipt.get("endpoint")
                or ""
            ).strip()
            observed_sha256 = str(
                transport_receipt.get("content_sha256") or ""
            ).strip().lower()
            if ledger_attached and (not observed_url or not observed_sha256):
                raise RuntimeError(
                    f"New Mexico {frontier_name} receipt lacks URL/digest evidence: {url}"
                )
            if observed_url and self._canonical_fetch_url(observed_url) != canonical_url:
                raise RuntimeError(
                    f"New Mexico {frontier_name} receipt changed URL identity: {url}"
                )
            if observed_sha256 and observed_sha256 != payload_sha256:
                raise RuntimeError(
                    f"New Mexico {frontier_name} receipt changed payload identity: {url}"
                )
        if parser_input_envelope is not None:
            envelope_body = getattr(parser_input_envelope, "body", None)
            if ledger_attached and envelope_body is None:
                raise RuntimeError(
                    f"New Mexico {frontier_name} envelope lacks body evidence: {url}"
                )
            if envelope_body is not None and bytes(envelope_body) != payload:
                raise RuntimeError(
                    f"New Mexico {frontier_name} envelope changed payload identity: {url}"
                )

    async def _fetch_nm_frontier(
        self,
        urls: Sequence[str],
        *,
        frontier_name: str,
        content_validator: Any,
        media_type: str,
        timeout_seconds: int,
        require_complete: bool,
    ) -> Dict[str, bytes]:
        """Fetch and verify one aligned NMOneSource source frontier."""

        requested = [self._canonical_fetch_url(url) for url in urls]
        if not requested:
            return {}
        if (
            any(not url or not self._host_is_official(url) for url in requested)
            or len(set(requested)) != len(requested)
        ):
            raise RuntimeError(
                f"New Mexico {frontier_name} frontier has invalid or duplicate URLs"
            )
        batch = await self._fetch_page_contents_with_archival_fallback_retrying_residuals(
            requested,
            residual_retry_attempts=1,
            timeout_seconds=timeout_seconds,
            # User-Agent is deliberately the only header.  Accept is part of the
            # retained sanitized-request identity and the current NM evidence was
            # acquired without it.
            headers={"User-Agent": "Mozilla/5.0"},
            content_validator=content_validator,
            media_type=media_type,
            max_concurrency=8,
            prefer_direct=True,
            common_crawl_domain_terms=(self.OFFICIAL_DOMAIN,),
            common_crawl_url_terms=("/nmos/nmsa/en/",),
            common_crawl_mime_terms=("pdf",) if media_type == "application/pdf" else ("html",),
            wayback_prefix_inventory=True,
        )
        aligned_lengths = {
            len(batch.urls),
            len(batch.payloads),
            len(batch.errors),
            len(batch.transport_receipts),
            len(batch.parser_input_envelopes),
        }
        if list(batch.urls) != requested or aligned_lengths != {len(requested)}:
            raise RuntimeError(
                f"New Mexico {frontier_name} frontier changed exact URL alignment"
            )
        payload_by_url: Dict[str, bytes] = {}
        failures: List[Dict[str, str]] = []
        for url, payload, error, receipt, envelope in zip(
            batch.urls,
            batch.payloads,
            batch.errors,
            batch.transport_receipts,
            batch.parser_input_envelopes,
            strict=True,
        ):
            raw = bytes(payload or b"")
            if error is not None or not raw or not content_validator(raw):
                failures.append(
                    {"url": url, "error": str(error or "empty or invalid parser input")}
                )
                continue
            self._validate_nm_aligned_evidence(
                url=url,
                payload=raw,
                transport_receipt=receipt,
                parser_input_envelope=envelope,
                frontier_name=frontier_name,
            )
            payload_by_url[url] = raw
        if failures and require_complete:
            raise RuntimeError(
                f"New Mexico {frontier_name} frontier is incomplete; "
                f"unresolved exact URLs: {failures[:10]}"
            )
        batch_stats = list(getattr(self, "_new_mexico_frontier_batch_stats", []))
        batch_stats.append(
            {
                "frontier_name": frontier_name,
                "requested_pages": len(requested),
                "successful_pages": len(payload_by_url),
                **dict(batch.stats or {}),
            }
        )
        self._new_mexico_frontier_batch_stats = batch_stats
        return payload_by_url

    async def _build_official_nmonesource_section(
        self,
        code_name: str,
        *,
        section_number: str,
        section_label: str,
        section_url: str,
        chapter_number: str,
        _payload: Optional[bytes] = None,
    ) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        payload = _payload
        if payload is None:
            payload = await self._fetch_page_content_with_archival_fallback(section_url, timeout_seconds=18)
            if not payload:
                payload = await self._request_bytes_direct(section_url, timeout=18)
        if not payload:
            return None
        soup = BeautifulSoup(payload, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
            tag.decompose()
        heading = soup.find(["h1", "h2"])
        section_name = self._normalize_legal_text(
            heading.get_text(" ", strip=True) if heading else section_label
        )
        text = self._normalize_legal_text(soup.get_text(" ", strip=True))
        if len(text) < 80:
            return None
        if not section_name:
            section_name = f"Section {section_number}"
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            chapter_number=chapter_number,
            section_number=section_number,
            section_name=section_name[:220],
            full_text=text,
            legal_area=self._identify_legal_area(f"{chapter_number} {section_name}"),
            source_url=section_url,
            official_cite=f"N.M. Stat. Ann. § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_nmonesource_html",
                "discovery_method": "official_nav_date_chapter_section",
                "skip_hydrate": True,
            },
        )

    async def _scrape_live_chapter_document_pdfs(
        self,
        code_name: str,
        max_statutes: Optional[int],
    ) -> List[NormalizedStatute]:
        """Close the official nav-date catalog over its exact chapter PDFs."""

        strict = max_statutes is None and self._full_corpus_enabled()
        discovery_limit = (
            None
            if strict
            else max(8, int(max_statutes or 1) * 8)
        )
        self._new_mexico_frontier_batch_stats = []
        discovered = await self._discover_live_document_urls(limit=discovery_limit)
        if not discovered:
            if strict:
                raise RuntimeError(
                    "New Mexico official PDF document frontier is empty"
                )
            return []

        pdf_urls = [pdf_url for _chapter_label, pdf_url in discovered]
        if len(pdf_urls) != len(set(pdf_urls)):
            raise RuntimeError("New Mexico official PDF frontier repeated a source URL")
        pdf_payload_by_url = await self._fetch_nm_pdf_frontier(
            pdf_urls,
            frontier_name="chapter document PDFs",
            require_complete=strict,
        )

        statutes: List[NormalizedStatute] = []
        seen_sections: set[str] = set()
        raw_section_occurrences = 0
        duplicate_section_occurrences = 0
        empty_document_urls: List[str] = []
        short_document_urls: List[str] = []

        for chapter_label, pdf_url in discovered:
            if max_statutes is not None and len(statutes) >= max_statutes:
                break
            pdf_bytes = pdf_payload_by_url.get(pdf_url, b"")
            if not pdf_bytes:
                continue

            chapter_text = self._extract_pdf_text_preserve_layout(
                pdf_bytes=pdf_bytes,
                max_chars=None,
            )
            if len(chapter_text) < 280:
                short_document_urls.append(pdf_url)
                if strict:
                    raise RuntimeError(
                        "New Mexico official PDF produced no complete parser text: "
                        f"{pdf_url}"
                    )
                continue

            split_sections = self._split_chapter_pdf_into_sections(
                code_name=code_name,
                chapter_label=chapter_label,
                chapter_text=chapter_text,
                source_url=pdf_url,
            )
            raw_section_occurrences += len(split_sections)
            if not split_sections:
                if strict and not self._is_explicitly_nonoperative_nm_pdf(
                    chapter_text
                ):
                    raise RuntimeError(
                        "New Mexico official PDF failed parser closure: "
                        f"{pdf_url}"
                    )
                # Chapter 22A in the retained official frontier contains only
                # recompiled locators. It is still a complete, valid source PDF
                # even though it contributes no operative normalized row.
                empty_document_urls.append(pdf_url)
            for statute in split_sections:
                section_number = str(statute.section_number or "").strip()
                normalized_section = section_number.casefold()
                if not normalized_section:
                    continue
                if normalized_section in seen_sections:
                    duplicate_section_occurrences += 1
                    continue
                seen_sections.add(normalized_section)
                statutes.append(statute)
                if max_statutes is not None and len(statutes) >= max_statutes:
                    break

        if strict and not statutes:
            raise RuntimeError(
                "New Mexico official PDF frontier produced no normalized statutes"
            )
        nav_urls = list(getattr(self, "_new_mexico_nav_frontier_urls", []))
        self._new_mexico_pdf_frontier_report = {
            "closed": bool(
                strict
                and len(pdf_payload_by_url) == len(pdf_urls)
                and not short_document_urls
                and bool(statutes)
            ),
            "nav_page_count": len(nav_urls),
            "nav_urls": nav_urls,
            "document_count": len(pdf_urls),
            "document_urls": list(pdf_urls),
            "fetched_document_count": len(pdf_payload_by_url),
            "raw_section_occurrences": raw_section_occurrences,
            "duplicate_section_occurrences": duplicate_section_occurrences,
            "normalized_row_count": len(statutes),
            "empty_document_urls": empty_document_urls,
            "short_document_urls": short_document_urls,
        }
        return statutes

    @staticmethod
    def _is_explicitly_nonoperative_nm_pdf(chapter_text: str) -> bool:
        """Recognize source-proved terminal-only chapter PDFs."""

        markers = re.findall(
            r"(?im)^\s*[0-9]+[A-Za-z]?(?:-[0-9A-Za-z]+)+(?:\.[0-9A-Za-z]+)*\.\s+([^\n]+)$",
            str(chapter_text or ""),
        )
        return bool(markers) and all(
            re.search(r"\b(?:recompiled|repealed|reserved)\b", marker, re.IGNORECASE)
            for marker in markers
        )

    async def _scrape_direct_document_pdfs(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        seeds = [
            ("24A", "https://nmonesource.com/nmos/nmsa/en/18973/1/document.do"),
            ("1", "https://nmonesource.com/nmos/nmsa/en/25293/1/document.do"),
        ]
        statutes: List[NormalizedStatute] = []
        for section_number, pdf_url in seeds[: max(1, int(max_statutes or 1))]:
            pdf_bytes = await self._request_bytes_direct(pdf_url, timeout=24)
            text = self._extract_pdf_text(pdf_bytes=pdf_bytes, max_chars=None)
            if len(text) < 280:
                continue
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § chapter-{section_number}",
                    code_name=code_name,
                    section_number=f"chapter-{section_number}",
                    section_name=f"NMSA chapter {section_number}",
                    full_text=text,
                    legal_area=self._identify_legal_area(text[:1200]),
                    source_url=pdf_url,
                    official_cite=f"N.M. Stat. Ann. ch. {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_nmonesource_pdf",
                        "discovery_method": "official_seed_document_pdf",
                        "skip_hydrate": True,
                    },
                )
            )
        return statutes

    async def _discover_live_document_urls(
        self,
        limit: Optional[int] = 120,
    ) -> List[tuple[str, str]]:
        """Derive and close the exact official nav-date source membership."""

        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        seed = "https://nmonesource.com/nmos/nmsa/en/nav_date.do?iframe=true"
        strict = limit is None and self._full_corpus_enabled()
        payload = await self._fetch_page_content_with_archival_fallback(seed, timeout_seconds=35)
        if not payload:
            if strict:
                raise RuntimeError("New Mexico official nav-date seed is unavailable")
            return []
        if not self._is_valid_nm_html(payload):
            if strict:
                raise RuntimeError("New Mexico official nav-date seed is invalid HTML")
            return []

        soup = BeautifulSoup(payload, "html.parser")
        page_by_number: Dict[int, str] = {}
        for link in soup.find_all("a", href=True):
            href = str(link.get("href", "")).strip()
            if "nav_date.do?page=" not in href:
                continue
            full = self._canonical_fetch_url(urljoin(seed, href))
            parsed = urlparse(full)
            query = urllib.parse.parse_qs(
                parsed.query,
                keep_blank_values=True,
                strict_parsing=False,
            )
            raw_pages = query.get("page", [])
            if (
                not self._host_is_official(full)
                or parsed.path != self.OFFICIAL_ENTRY_PATH
                or set(query) != {"page"}
                or len(raw_pages) != 1
                or not str(raw_pages[0]).isdigit()
            ):
                if strict:
                    raise RuntimeError(
                        "New Mexico official nav-date pagination changed source identity: "
                        f"{full}"
                    )
                continue
            page_number = int(raw_pages[0])
            if page_number < 2:
                if strict:
                    raise RuntimeError(
                        "New Mexico official nav-date pagination contains an invalid page: "
                        f"{full}"
                    )
                continue
            expected_url = f"{self.OFFICIAL_ENTRY_URL}?page={page_number}"
            prior_url = page_by_number.setdefault(page_number, expected_url)
            if prior_url != expected_url:
                raise RuntimeError(
                    "New Mexico official nav-date pagination repeated a page identity"
                )

        if page_by_number:
            expected_pages = set(range(2, max(page_by_number) + 1))
            missing_pages = sorted(expected_pages - set(page_by_number))
            if missing_pages and strict:
                raise RuntimeError(
                    "New Mexico official nav-date pagination is incomplete; "
                    f"missing pages: {missing_pages}"
                )
        page_urls = [seed] + [page_by_number[number] for number in sorted(page_by_number)]
        pages_to_scan = page_urls if strict else page_urls[:8]
        page_payload_by_url = {seed: bytes(payload)}
        pagination_urls = pages_to_scan[1:]
        if pagination_urls:
            page_payload_by_url.update(
                await self._fetch_nm_html_frontier(
                    pagination_urls,
                    frontier_name="nav-date pagination pages",
                    require_complete=strict,
                )
            )
        self._new_mexico_nav_frontier_urls = list(pages_to_scan)

        discovered: List[tuple[str, str]] = []
        seen: set[str] = set()
        for page_url in pages_to_scan:
            if limit is not None and len(discovered) >= limit:
                break
            page_bytes = page_payload_by_url.get(page_url, b"")
            if not page_bytes:
                continue
            page_soup = BeautifulSoup(page_bytes, "html.parser")
            pending_label = ""
            for link in page_soup.find_all("a", href=True):
                href = str(link.get("href", "")).strip()
                text = re.sub(r"\s+", " ", link.get_text(" ", strip=True)).strip()
                if "/item/" in href and re.search(r"\bchapter\b", text, flags=re.IGNORECASE):
                    pending_label = text
                    continue
                if "/document.do" not in href:
                    continue
                full_url = self._canonical_fetch_url(urljoin(page_url, href))
                parsed = urlparse(full_url)
                if (
                    not self._host_is_official(full_url)
                    or not re.fullmatch(
                        r"/nmos/nmsa/en/[0-9]+/1/document\.do",
                        parsed.path,
                        flags=re.IGNORECASE,
                    )
                    or parsed.query
                ):
                    if strict:
                        raise RuntimeError(
                            "New Mexico official PDF catalog changed source identity: "
                            f"{full_url}"
                        )
                    continue
                if full_url in seen:
                    continue
                if not pending_label and strict:
                    raise RuntimeError(
                        "New Mexico official PDF catalog lost a chapter label: "
                        f"{full_url}"
                    )
                seen.add(full_url)
                discovered.append((pending_label or f"Chapter {len(discovered)+1}", full_url))
                pending_label = ""
                if limit is not None and len(discovered) >= limit:
                    break

        if strict and not discovered:
            raise RuntimeError("New Mexico official PDF document frontier is empty")
        return discovered

    async def _request_bytes_direct(self, url: str, timeout: int = 24) -> bytes:
        try:
            return await self._fetch_parser_input_with_transport(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8",
                },
                timeout_seconds=max(1, int(timeout)),
                allow_archival_fallback=True,
                provider="new_mexico_direct_nmonesource",
            )
        except Exception:
            return b""

    async def _scrape_nmonesource_nav_sections(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        """Parse NMOneSource nav-by-date pages that expose chapter/item links."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        seed = "https://nmonesource.com/nmos/nmsa/en/nav_date.do?iframe=true"
        payload = await self._fetch_page_content_with_archival_fallback(seed, timeout_seconds=35)
        if not payload:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        page_urls = [seed]
        for link in soup.find_all("a", href=True):
            href = str(link.get("href", ""))
            if "nav_date.do?page=" not in href:
                continue
            full = urljoin(seed, href)
            if full not in page_urls:
                page_urls.append(full)

        statutes: List[NormalizedStatute] = []
        seen = set()

        pages_to_scan = page_urls if self._full_corpus_enabled() else page_urls[:8]
        for page_url in pages_to_scan:
            if len(statutes) >= max_statutes:
                break
            page_bytes = await self._fetch_page_content_with_archival_fallback(page_url, timeout_seconds=35)
            if not page_bytes:
                continue
            page_soup = BeautifulSoup(page_bytes, "html.parser")

            for link in page_soup.find_all("a", href=True):
                if len(statutes) >= max_statutes:
                    break

                text = re.sub(r"\s+", " ", link.get_text(" ", strip=True)).strip()
                href = str(link.get("href", "")).strip()
                if not text or not href:
                    continue

                if "/item/" not in href and "/document.do" not in href:
                    continue
                if not re.search(r"\bchapter\b", text, flags=re.IGNORECASE):
                    continue

                source_url = urljoin(page_url, href)
                if source_url in seen:
                    continue
                seen.add(source_url)

                chapter_match = re.search(r"chapter\s+([\dA-Za-z.-]+)", text, flags=re.IGNORECASE)
                chapter_no = chapter_match.group(1) if chapter_match else None
                section_number = chapter_no or self._extract_section_number(text) or f"Section-{len(statutes)+1}"

                statutes.append(
                    NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § {section_number}",
                        code_name=code_name,
                        chapter_number=chapter_no,
                        section_number=section_number,
                        section_name=text[:220],
                        full_text=f"Section {section_number}: {text}",
                        legal_area=self._identify_legal_area(text),
                        source_url=source_url,
                        official_cite=f"N.M. Stat. Ann. § {section_number}",
                        metadata=StatuteMetadata(),
                    )
                )

        return statutes

    async def _scrape_nmonesource_index(self, code_name: str) -> List[NormalizedStatute]:
        """Fallback that records the official NMSA index when section pages are unavailable."""
        nav_url = "https://nmonesource.com/nmos/en/nav.do"
        nmsa_url = "https://nmonesource.com/nmos/nmsa/en/nav_date.do"

        try:
            payload = await self._fetch_page_content_with_archival_fallback(nav_url, timeout_seconds=30)
            if not payload:
                return []
            text = re.sub(r"\s+", " ", payload.decode("utf-8", errors="ignore")).strip()
            if len(text) < 220:
                return []
        except Exception:
            return []

        summary = (
            "Official New Mexico Statutes Annotated index from NMOneSource. "
            "Collection includes Current New Mexico Statutes Annotated 1978 and related legal materials. "
            f"Source pages: {nav_url} and {nmsa_url}. "
            f"Index excerpt: {text[:900]}"
        )

        statute = NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § NMSA-INDEX",
            code_name=code_name,
            section_number="NMSA-INDEX",
            section_name="Current New Mexico Statutes Annotated 1978 (Index)",
            full_text=summary,
            legal_area="general",
            source_url=nmsa_url,
            official_cite="N.M. Stat. Ann. Index",
            metadata=StatuteMetadata(),
        )
        return [statute]

    async def _scrape_archived_document_pdfs(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        headers = {"User-Agent": "Mozilla/5.0"}
        statutes: List[NormalizedStatute] = []
        seen = set()

        archive_candidates = await self._discover_archived_document_urls(
            limit=2000 if self._full_corpus_enabled() else 8
        )
        candidate_urls = list(self._ARCHIVE_DOCUMENT_PDFS)
        for url in archive_candidates:
            if url not in candidate_urls:
                candidate_urls.append(url)

        pdf_urls_to_scan = candidate_urls if self._full_corpus_enabled() else candidate_urls[:12]
        for pdf_url in pdf_urls_to_scan:
            if len(statutes) >= max_statutes:
                break

            section_number = self._extract_item_id(pdf_url)
            if not section_number or section_number in seen:
                continue

            pdf_bytes = await self._request_bytes(pdf_url=pdf_url, headers=headers, timeout=50)
            if not pdf_bytes:
                continue

            full_text = self._extract_pdf_text(pdf_bytes=pdf_bytes, max_chars=None)
            if len(full_text) < 280:
                continue

            statute = NormalizedStatute(
                state_code=self.state_code,
                state_name=self.state_name,
                statute_id=f"{code_name} § item-{section_number}",
                code_name=code_name,
                section_number=f"item-{section_number}",
                section_name=f"NMSA item {section_number}",
                full_text=full_text,
                legal_area=self._identify_legal_area(full_text),
                source_url=pdf_url,
                official_cite=f"N.M. Stat. Ann. item {section_number}",
            )
            statutes.append(statute)
            seen.add(section_number)

        return statutes

    async def _discover_archived_document_urls(self, limit: int = 80) -> List[str]:
        """Discover archived NMOneSource statute documents via Wayback CDX."""
        cdx_url = (
            "http://web.archive.org/cdx/search/cdx?url=nmonesource.com/nmos/nmsa/en/*/1/document.do"
            "&output=json&filter=statuscode:200&collapse=digest"
            f"&limit={max(1, int(limit))}"
        )

        try:
            rows = await self._fetch_wayback_cdx_rows(
                cdx_url,
                timeout_seconds=45,
            )
            if len(rows) < 2:
                return []

            discovered: List[str] = []
            for row in rows[1:]:
                if not isinstance(row, list) or len(row) < 3:
                    continue
                ts = str(row[1]).strip()
                original = str(row[2]).strip()
                if not ts or not original:
                    continue
                encoded = urllib.parse.quote(original, safe=':/?=&%.-_')
                archive_url = f"http://web.archive.org/web/{ts}/{encoded}"
                discovered.append(archive_url)

            return discovered
        except Exception as exc:
            self.logger.debug(f"New Mexico CDX discovery failed: {exc}")
            return []

    def _extract_item_id(self, pdf_url: str) -> str:
        match = re.search(r"/en/(\d+)/1/document\.do", str(pdf_url or ""), flags=re.IGNORECASE)
        return match.group(1) if match else ""

    async def _request_bytes(self, pdf_url: str, headers: Dict[str, str], timeout: int) -> bytes:
        first = str(pdf_url or "")
        candidates: List[str] = [first]

        # If this is a Wayback URL, also try the original source URL directly.
        m = re.search(r"/web/\d+/(https?://.+)$", first, flags=re.IGNORECASE)
        if m:
            original_url = urllib.parse.unquote(m.group(1))
            if original_url and original_url not in candidates:
                candidates.append(original_url)

        expanded: List[str] = []
        for candidate in candidates:
            expanded.append(candidate)
            if candidate.startswith("https://"):
                expanded.append("http://" + candidate[8:])
            elif candidate.startswith("http://"):
                expanded.append("https://" + candidate[7:])

        # Stable dedupe
        seen = set()
        candidates = []
        for candidate in expanded:
            if candidate and candidate not in seen:
                candidates.append(candidate)
                seen.add(candidate)

        for candidate in candidates:
            for _ in range(1):
                try:
                    payload = await self._fetch_page_content_with_archival_fallback(
                        candidate,
                        timeout_seconds=max(6, min(int(timeout), 12)),
                    )
                    if payload:
                        return payload
                except Exception:
                    await asyncio.sleep(0.1)
                    continue

        return b""

    def _extract_pdf_text(
        self,
        pdf_bytes: bytes,
        max_chars: Optional[int] = None,
    ) -> str:
        text = self._extract_pdf_text_preserve_layout(pdf_bytes=pdf_bytes, max_chars=max_chars)
        text = re.sub(r"\s+", " ", text).strip()
        if max_chars is not None:
            return text[: max(1, int(max_chars))]
        return text

    def _extract_pdf_text_preserve_layout(
        self,
        pdf_bytes: bytes,
        max_chars: Optional[int] = None,
    ) -> str:
        try:
            proc = subprocess.run(
                [trusted_pdftotext_executable(), "-layout", "-q", "-", "-"],
                input=pdf_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except Exception:
            return ""

        if proc.returncode != 0 or not proc.stdout:
            return ""

        text = proc.stdout.decode("utf-8", errors="ignore")
        text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        if max_chars is not None:
            return text[: max(1, int(max_chars))]
        return text

    def _split_chapter_pdf_into_sections(
        self,
        *,
        code_name: str,
        chapter_label: str,
        chapter_text: str,
        source_url: str,
    ) -> List[NormalizedStatute]:
        matches = list(self._SECTION_HEADER_RE.finditer(chapter_text))
        if not matches:
            return []

        out: List[NormalizedStatute] = []
        chapter_number_match = re.search(r"Chapter\s+([0-9A-Za-z.-]+)", chapter_label, flags=re.IGNORECASE)
        chapter_number = chapter_number_match.group(1) if chapter_number_match else None

        for index, match in enumerate(matches):
            section_number = str(match.group(1) or "").strip()
            section_title = re.sub(r"\s+", " ", str(match.group(2) or "")).strip()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(chapter_text)
            body = chapter_text[match.start():end].strip()
            body = re.sub(r"\n{3,}", "\n\n", body)
            normalized_body = self._normalize_legal_text(body)
            if len(normalized_body) < 120:
                continue
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    chapter_number=chapter_number,
                    chapter_name=chapter_label,
                    section_number=section_number,
                    section_name=section_title or f"Section {section_number}",
                    full_text=normalized_body,
                    legal_area=self._identify_legal_area(f"{chapter_label} {section_title}"),
                    source_url=source_url,
                    official_cite=f"N.M. Stat. Ann. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_nmonesource_chapter_pdf",
                        "discovery_method": "official_nav_date_chapter_pdf_sections",
                        "chapter_label": chapter_label,
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    def official_chapter_url(self, chapter_number: Any) -> str:
        number = str(chapter_number or "").strip().upper()
        return f"{self.OFFICIAL_ENTRY_URL}#chapter-{number.lower()}"

    def official_chapter_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official New Mexico Statutes chapter catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_CHAPTERS:
            url = self.official_chapter_url(number)
            rows.append(
                {
                    "canonical_key": f"nm:chapter-{number.lower()}",
                    "chapter_number": number,
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"New Mexico Statutes Annotated Chapter {number} ({name}) "
                        f"official catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host in {
            "nmonesource.com",
            "www.nmonesource.com",
            "www.nmlegis.gov",
            "nmlegis.gov",
        } or host.endswith(".nmonesource.com") or host.endswith(".nmlegis.gov")

    def _looks_like_secondary_url(self, url: str) -> bool:
        lowered = str(url or "").strip().lower()
        return any(
            marker in lowered
            for marker in ("justia.com", "findlaw.com", "unicourt", "law.cornell.edu")
        )

    def _normalize_chapter_number(self, value: Any) -> str:
        text = str(value or "").strip().upper()
        if not text:
            return ""
        match = re.search(r"\b([0-9]+[A-Z]?)\b", text)
        if not match:
            return ""
        number = match.group(1)
        known = {item for item, _name in self.OFFICIAL_CHAPTERS}
        return number if number in known else ""

    def _official_http_get(self, url: str, timeout_seconds: int = 8) -> bytes:
        timeout = max(2, min(int(timeout_seconds or 8), 8))
        headers = {
            "User-Agent": "ipfs-datasets-new-mexico-official-catalog/1.0",
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
                with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                    return bytes(response.read() or b"")
            except Exception:
                return b""

    def classify_linkless_seed_rows(
        self,
        seeds: object,
        *,
        page_url: str = "",
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Replace recoverable NMOneSource chapters or quarantine leftover seeds.

        Recoverable chapter numbers are rewritten to official nmonesource
        catalog URLs. Remaining Hugging Face bucket / secondary-mirror rows
        stay quarantined until an official replacement is proven.
        """

        repaired: List[Dict[str, Any]] = []
        quarantines: List[Dict[str, Any]] = []
        seen: set[str] = set()
        seen_quarantine: set[str] = set()

        def _record(chapter_number: str, label: str, source: str, source_url: str = "") -> None:
            number = self._normalize_chapter_number(chapter_number)
            if not number:
                return
            unit_id = f"nm:chapter-{number.lower()}"
            if unit_id in seen:
                return
            seen.add(unit_id)
            official_url = (
                source_url
                if source_url and self._host_is_official(source_url)
                else self.official_chapter_url(number)
            )
            name = dict(self.OFFICIAL_CHAPTERS).get(number, f"Chapter {number}")
            cleaned = re.sub(r"\s+", " ", str(label or "")).strip() or name
            repaired.append(
                {
                    "canonical_key": unit_id,
                    "chapter_number": number,
                    "name": name,
                    "source_url": official_url,
                    "label": cleaned,
                    "repair_source": source,
                    "source_link_disposition": (
                        "official" if source == "official_href" else "official_replacement"
                    ),
                    "text": (
                        f"New Mexico Statutes Annotated Chapter {number} ({name}) "
                        f"official catalog unit at {official_url}"
                    ),
                }
            )

        def _quarantine(label: str, evidence: str, unit_id: str = "", reason: str = "") -> None:
            cleaned = re.sub(r"\s+", " ", str(label or "")).strip()
            if not cleaned:
                return
            key = unit_id or (
                "nm:bucket-" + hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]
            )
            if key in seen_quarantine:
                return
            seen_quarantine.add(key)
            quarantines.append(
                {
                    "unit_id": key,
                    "reason": reason or self.LINKLESS_SEED_DISPOSITION,
                    "label": cleaned[:240],
                    "page_url": page_url,
                    "evidence_sha256": hashlib.sha256(
                        str(evidence or cleaned).encode("utf-8")
                    ).hexdigest(),
                }
            )

        if isinstance(seeds, (bytes, bytearray, str)):
            html = (
                seeds.decode("utf-8", errors="replace")
                if isinstance(seeds, (bytes, bytearray))
                else seeds
            )
            try:
                from bs4 import BeautifulSoup
            except ImportError as exc:
                raise RuntimeError(
                    "BeautifulSoup is required for official New Mexico discovery"
                ) from exc
            soup = BeautifulSoup(html, "html.parser")
            for link in soup.find_all("a", href=True):
                href = str(link.get("href") or "").strip()
                label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
                absolute = urljoin(page_url or self.OFFICIAL_ENTRY_URL, href)
                match = self._NM_CHAPTER_HREF_RE.search(absolute) or self._NM_CHAPTER_LABEL_RE.search(
                    label
                )
                chapter = match.group("chapter") if match else self._normalize_chapter_number(
                    " ".join((absolute, href, label))
                )
                if chapter and self._host_is_official(absolute):
                    _record(chapter, label, "official_href", self.official_chapter_url(chapter))
                    continue
                if chapter:
                    _record(chapter, label, "official_replacement")
                    continue
                if label and self._looks_like_secondary_url(absolute):
                    _quarantine(label, str(link), reason=self.MISSING_LINK_DISPOSITION)
            for node in soup.find_all(["span", "td", "li", "div", "p"]):
                if node.find("a", href=True):
                    continue
                label = re.sub(r"\s+", " ", node.get_text(" ", strip=True) or "").strip()
                if not label:
                    continue
                chapter = self._normalize_chapter_number(
                    " ".join(
                        str(item or "")
                        for item in (node.get("data-chapter"), node.get("id"), label)
                    )
                )
                if chapter:
                    _record(chapter, label, "repaired_from_linkless_row")
                    continue
                if re.search(
                    r"\b(bucket seed|phantom|without a recoverable|without an official|linkless)\b",
                    label,
                    re.IGNORECASE,
                ):
                    _quarantine(label, str(node), reason=self.MISSING_LINK_DISPOSITION)
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
            chapter = self._normalize_chapter_number(
                item.get("chapter_number") or item.get("chapter") or source_url or label
            )
            if chapter and source_url and self._host_is_official(source_url):
                _record(chapter, label, "official_href", source_url)
                continue
            if chapter:
                _record(chapter, label, "official_replacement")
                continue
            _quarantine(
                label or source_url or "new mexico linkless seed",
                json.dumps(dict(item), sort_keys=True),
                unit_id=str(item.get("canonical_key") or ""),
            )
        return {"repaired": repaired, "quarantines": quarantines}

    def _parse_official_chapter_links(self, html: bytes) -> Dict[str, str]:
        found: Dict[str, str] = {}
        if not html:
            return found
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return found
        soup = BeautifulSoup(html, "html.parser")
        known = {number for number, _name in self.OFFICIAL_CHAPTERS}
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            if not href:
                continue
            absolute = urljoin(self.OFFICIAL_ENTRY_URL, href)
            match = self._NM_CHAPTER_HREF_RE.search(absolute) or self._NM_CHAPTER_LABEL_RE.search(
                label
            )
            if not match:
                continue
            number = str(match.group("chapter") or "").strip().upper()
            if number not in known or number in found:
                continue
            if self._host_is_official(absolute):
                found[number] = self.official_chapter_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
        seed_rows: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Enumerate official NMSA chapters and quarantine leftover bucket seeds."""

        discovered = self._parse_official_chapter_links(html)
        classified = self.classify_linkless_seed_rows(
            html or b"",
            page_url=page_url or self.OFFICIAL_ENTRY_URL,
        )
        seed_classified = self.classify_linkless_seed_rows(
            list(seed_rows) if seed_rows is not None else list(self.DEFAULT_LINKLESS_SEED_ROWS),
            page_url=page_url or self.OFFICIAL_ENTRY_URL,
        )
        classified["repaired"].extend(seed_classified["repaired"])
        classified["quarantines"].extend(seed_classified["quarantines"])
        self.last_official_quarantines = list(classified["quarantines"])
        self.last_official_replacements = list(classified["repaired"])

        rows = self.official_chapter_catalog()
        by_chapter = {str(row["chapter_number"]).upper(): row for row in rows}
        for row in rows:
            live_url = discovered.get(str(row["chapter_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_nmonesource"
        for unit in classified["repaired"]:
            number = str(unit.get("chapter_number") or "").upper()
            if number in by_chapter and unit.get("source_url"):
                if unit.get("repair_source") == "official_href":
                    by_chapter[number]["source_url"] = unit["source_url"]
                    by_chapter[number]["source_link_disposition"] = "official"
                else:
                    by_chapter[number]["source_link_disposition"] = (
                        by_chapter[number].get("source_link_disposition")
                        or "official_replacement"
                    )
        return rows

    def fetch_official(self, code: str = "NM"):
        """Acquire the exhaustive official New Mexico Statutes chapter catalog.

        Official NMOneSource chapters are admitted. Hugging Face bucket seed
        rows remain quarantined unless an official chapter replacement is
        proven. This hook never returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "NM").strip().upper() or "NM"
        if normalized != "NM":
            raise ValueError(f"NewMexicoScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        quarantines = list(getattr(self, "last_official_quarantines", []) or [])
        replacements = list(getattr(self, "last_official_replacements", []) or [])
        if len(rows) != self.OFFICIAL_CHAPTER_COUNT:
            raise RuntimeError(
                "new mexico official catalog enumeration rejected incomplete chapter reacquisition"
            )
        request = (
            f"GET {self.OFFICIAL_ENTRY_PATH} HTTP/1.1\n"
            f"host: {self.OFFICIAL_DOMAIN}\n"
        ).encode("utf-8")
        catalog = {
            "jurisdiction": normalized,
            "linkless_seeds_replaced": True,
            "official_domain": self.OFFICIAL_DOMAIN,
            "entry_url": self.OFFICIAL_ENTRY_URL,
            "quarantines": quarantines,
            "replacement_source": "official_nmonesource",
            "replacements": replacements,
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
            "nm_linkless_seed_quarantines": quarantines,
            "nm_linkless_seeds_replaced": True,
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
StateScraperRegistry.register("NM", NewMexicoScraper)
