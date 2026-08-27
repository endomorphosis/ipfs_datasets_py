"""Scraper for Iowa state laws.

This module contains the scraper for Iowa statutes from the official state legislative website.
"""

import asyncio
import hashlib
import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Mapping, Optional, Tuple
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class IowaScraper(BaseStateScraper):
    """Scraper for Iowa state laws from https://www.legis.iowa.gov"""

    OFFICIAL_DOMAIN = "www.legis.iowa.gov"
    OFFICIAL_ENTRY_PATH = "/law/statutory"
    OFFICIAL_ENTRY_URL = "https://www.legis.iowa.gov/law/statutory"
    OFFICIAL_CODE_YEAR = "2026"
    _IOWA_TITLE_TOKENS = (
        "I",
        "II",
        "III",
        "IV",
        "V",
        "VI",
        "VII",
        "VIII",
        "IX",
        "X",
        "XI",
        "XII",
        "XIII",
        "XIV",
        "XV",
        "XVI",
    )
    _TITLE_QUERY_RE = re.compile(r"(?:[?&]title=|/title/)([IVXLCDM]+|\d+)", re.IGNORECASE)

    def state_law_frontier_source_dependencies(self) -> tuple[object, ...]:
        """Bind the chapter-XML parser bytes into prospective evidence."""

        from . import iowa_chapter_xml

        return (iowa_chapter_xml,)

    def get_base_url(self) -> str:
        """Return the base URL for Iowa's legislative website."""
        return "https://www.legis.iowa.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Iowa."""
        return [{
            "name": "Iowa Code",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]

    @staticmethod
    def _has_exact_parser_input_provenance(statute: NormalizedStatute) -> bool:
        structured = dict(statute.structured_data or {})
        digest = str(structured.get("content_sha256") or "").strip().lower()
        receipt = structured.get("transport_receipt")
        receipt_digest = (
            str(receipt.get("content_sha256") or "").strip().lower()
            if isinstance(receipt, Mapping)
            else ""
        )
        return bool(
            re.fullmatch(r"[a-f0-9]{64}", digest)
            and receipt_digest == digest
        )

    def _bind_parser_input_provenance(
        self,
        statutes: List[NormalizedStatute],
        *,
        parser_input_url: str,
    ) -> List[NormalizedStatute]:
        """Bind rows from one XML/document response to its retained bytes."""

        if not statutes:
            return statutes
        provenance = self._last_parser_input_row_provenance()
        receipt = provenance.get("transport_receipt")
        retained_url = (
            str(receipt.get("official_url") or "").strip()
            if isinstance(receipt, Mapping)
            else ""
        )
        exact_input = bool(
            provenance
            and parser_input_url
            and retained_url
            and self._canonical_fetch_url(retained_url)
            == self._canonical_fetch_url(parser_input_url)
        )
        if not exact_input:
            if self._state_law_acquisition_ledger is not None:
                raise RuntimeError(
                    "Iowa rows lack exact retained parser-input provenance"
                )
            return statutes
        for statute in statutes:
            structured = dict(statute.structured_data or {})
            structured.update(provenance)
            statute.structured_data = structured
        return statutes

    def _enrich_statute_structure(
        self,
        statute: NormalizedStatute,
    ) -> NormalizedStatute:
        """Carry retained Iowa XML/document provenance into JSON-LD."""

        enriched = super()._enrich_statute_structure(statute)
        structured = dict(enriched.structured_data or {})
        if str(structured.get("source_kind") or "").strip() not in {
            "official_iowa_chapter_slim_xml",
            "official_iowa_code_section_document",
        }:
            return enriched
        if not self._has_exact_parser_input_provenance(enriched):
            if self._state_law_acquisition_ledger is not None:
                raise RuntimeError(
                    "Iowa row lacks canonical retained parser-input provenance"
                )
            return enriched

        digest = str(structured.get("content_sha256") or "").strip().lower()
        receipt = structured["transport_receipt"]
        jsonld = structured.get("jsonld")
        if not isinstance(jsonld, Mapping):
            if self._state_law_acquisition_ledger is not None:
                raise RuntimeError(
                    "Iowa row lacks canonical retained parser-input provenance"
                )
            return enriched
        jsonld_payload = dict(jsonld)
        prior = jsonld_payload.get("provenance")
        provenance = dict(prior) if isinstance(prior, Mapping) else {}
        provenance.update(
            {
                "content_sha256": digest,
                "transport_receipt": dict(receipt),
            }
        )
        jsonld_payload["provenance"] = provenance
        structured["jsonld"] = jsonld_payload
        enriched.structured_data = structured
        return enriched

    @staticmethod
    def _is_exact_reserved_section_text(text: str, section_number: str) -> bool:
        normalized = re.sub(r"\s+", " ", str(text or "")).strip()
        section = str(section_number or "").strip()
        return bool(
            section
            and normalized.casefold()
            in {"reserved.", f"{section} reserved.".casefold()}
        )
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Iowa's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .iowa_constitution import (
            configured_constitution_html_path,
            parse_iowa_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_iowa_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Iowa Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        local_xml = self._scrape_configured_chapter_xml(code_name, max_statutes)
        if local_xml:
            return local_xml
        full_corpus = self._full_corpus_enabled()
        allow_justia = str(
            os.getenv("IOWA_ALLOW_JUSTIA_FALLBACK")
            or os.getenv("STATE_SCRAPER_IA_ALLOW_JUSTIA_FALLBACK")
            or ""
        ).strip().lower() in {"1", "true", "yes", "on"}

        if full_corpus and max_statutes is None:
            official_sections = await self._scrape_official_iowa_sections(code_name)
            accept_min = max(
                1,
                int(os.getenv("IOWA_OFFICIAL_FULL_CORPUS_ACCEPT_MIN", "500") or "500"),
            )
            if len(official_sections) >= accept_min:
                self.logger.info(
                    "Iowa official section crawl accepted %s rows (min=%s)",
                    len(official_sections),
                    accept_min,
                )
                return official_sections
            self.logger.warning(
                "Iowa official section crawl returned %s rows (min=%s); refusing capped legacy recovery in full-corpus mode",
                len(official_sections),
                accept_min,
            )
            return []

        return_threshold = self._bounded_return_threshold(160)
        if max_statutes is not None:
            return_threshold = max(1, min(return_threshold, int(max_statutes)))

        # Bounded probes prefer official HTML section seeds with real full text.
        if max_statutes is not None:
            direct_sections = await self._scrape_direct_seed_sections(
                code_name, max_statutes=return_threshold
            )
            if direct_sections:
                return direct_sections[:return_threshold]

        live_stubs = await self._scrape_live_code_stubs(code_name, max_statutes=max(10, return_threshold))

        archival_limit = max(10, return_threshold)
        if full_corpus and max_statutes is None:
            archival_limit = min(
                archival_limit,
                int(os.getenv("IOWA_ARCHIVAL_STUB_LIMIT", "5000") or "5000"),
            )
        archival_stubs = await self._scrape_archived_code_stubs(code_name, max_statutes=archival_limit)

        merged: List[NormalizedStatute] = []
        merged_keys = set()

        def _merge(items: List[NormalizedStatute]) -> None:
            for statute in items:
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if not key or key in merged_keys:
                    continue
                merged_keys.add(key)
                merged.append(statute)

        _merge(live_stubs)
        _merge(archival_stubs)
        if full_corpus and max_statutes is None:
            accept_min = max(1, int(os.getenv("IOWA_FULL_CORPUS_ACCEPT_MIN", "500") or "500"))
            if len(merged) >= accept_min:
                self.logger.info(
                    "Iowa full-corpus crawl accepting %s merged official/archive rows before generic fallback",
                    len(merged),
                )
                return merged
        if len(merged) >= return_threshold:
            return merged

        if not self._full_corpus_enabled():
            direct_sections = await self._scrape_direct_seed_sections(code_name, max_statutes=return_threshold)
            if direct_sections:
                return direct_sections[:return_threshold]

        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/docs/code//",
            f"{self.get_base_url()}/docs/code/",
        ]
        if allow_justia or not full_corpus:
            candidate_urls.extend(
                [
                    "https://law.justia.com/codes/iowa/",
                    "http://web.archive.org/web/20250101000000/https://law.justia.com/codes/iowa/",
                ]
            )

        seen = set()
        best_statutes: List[NormalizedStatute] = list(merged)
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            statutes = await self._generic_scrape(code_name, candidate, "Iowa Code", max_sections=max(10, return_threshold))
            if full_corpus and not allow_justia:
                statutes = [
                    row
                    for row in statutes
                    if "justia.com" not in str(getattr(row, "source_url", "") or "").lower()
                ]
            _merge(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(merged) > len(best_statutes):
                best_statutes = list(merged)
            if len(statutes) >= return_threshold:
                return list(merged) if len(merged) >= return_threshold else statutes

        if len(merged) > len(best_statutes):
            best_statutes = list(merged)

        if full_corpus and not allow_justia:
            official_only = [
                row
                for row in best_statutes
                if "justia.com" not in str(getattr(row, "source_url", "") or "").lower()
            ]
            if not official_only:
                self.logger.warning(
                    "Iowa full-corpus crawl found no official legis.iowa.gov rows; refusing Justia-only admission"
                )
                return []
            return official_only

        return best_statutes

    def _scrape_configured_chapter_xml(
        self,
        code_name: str,
        max_statutes: Optional[int],
    ) -> List[NormalizedStatute]:
        from .iowa_chapter_xml import configured_chapter_xml_path, parse_iowa_chapter_xml

        path = configured_chapter_xml_path()
        if path is None:
            return []
        try:
            return parse_iowa_chapter_xml(
                path.read_bytes(),
                chapter=path.stem.split("_", 1)[0],
                year=self.OFFICIAL_CODE_YEAR,
                code_name=code_name,
                max_statutes=max_statutes,
            )
        except Exception as exc:
            self.logger.warning("Iowa official chapter XML failed: %s", exc)
            return []

    async def _scrape_official_iowa_sections(self, code_name: str) -> List[NormalizedStatute]:
        """Scrape Iowa Code from title/chapter pages and per-section RTF/PDF files."""
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import parse_qs, urljoin, urlparse
        except ImportError:
            return []

        year = str(os.getenv("IOWA_CODE_YEAR", "2026") or "2026").strip() or "2026"
        resumed = self._load_partial_checkpoint_statutes(code_name=code_name, max_statutes=None)
        checkpoint_progress = self._load_partial_checkpoint_progress()
        resume_chapters_scanned = max(0, int(checkpoint_progress.get("chapters_scanned") or 0))
        resume_sections_scanned = max(0, int(checkpoint_progress.get("sections_scanned") or 0))
        resume_discovered_sections = max(0, int(checkpoint_progress.get("discovered_sections") or 0))
        if (
            self._state_law_acquisition_ledger is not None
            and resumed
            and any(
                not self._has_exact_parser_input_provenance(statute)
                for statute in resumed
            )
        ):
            # A legacy checkpoint predating prospective row provenance cannot
            # be promoted or partially resumed.  Reparse the immutable ledger
            # inputs so every retained row receives its exact XML/document
            # digest; this does not require reacquiring already retained bytes.
            self.logger.warning(
                "Iowa is ignoring %s unbound checkpoint rows and replaying retained inputs",
                len(resumed),
            )
            resumed = []
            checkpoint_progress = {}
            resume_chapters_scanned = 0
            resume_sections_scanned = 0
            resume_discovered_sections = 0
        chapter_rewind = max(
            0,
            int(os.getenv("STATE_SCRAPER_IA_RESUME_CHAPTER_REWIND", "8") or "8"),
        )
        resume_chapter_floor = max(0, resume_chapters_scanned - chapter_rewind)

        official_rows: List[NormalizedStatute] = []
        seen_section_keys = set()
        terminal_section_dispositions: Dict[str, Dict[str, object]] = {}
        self._last_iowa_terminal_dispositions = []
        for statute in resumed:
            section_number = str(getattr(statute, "section_number", "") or "").strip()
            source_url = str(getattr(statute, "source_url", "") or "").strip()
            section_key = (section_number.lower(), source_url.lower())
            if section_key in seen_section_keys:
                continue
            seen_section_keys.add(section_key)
            official_rows.append(statute)

        chapter_urls: List[str] = []
        chapter_frontier: Dict[str, Dict[str, object]] = {}
        seen_chapters = set()

        chapter_page_timeout = max(
            8,
            int(os.getenv("IOWA_CHAPTER_PAGE_TIMEOUT_SECONDS", "25") or "25"),
        )
        section_doc_timeout = max(
            8,
            int(os.getenv("IOWA_SECTION_DOC_TIMEOUT_SECONDS", "18") or "18"),
        )
        official_archival_fallback = str(
            os.getenv("IOWA_OFFICIAL_USE_ARCHIVAL_FALLBACK", "0")
        ).strip().lower() in {"1", "true", "yes", "on"}

        for title_token in self._IOWA_TITLE_TOKENS:
            title_url = (
                f"{self.get_base_url()}/law/iowaCode/chapters"
                f"?title={title_token}&year={year}"
            )
            payload = await self._request_bytes(
                title_url,
                timeout=chapter_page_timeout,
                allow_archival_fallback=official_archival_fallback,
            )
            if not payload:
                continue
            try:
                html = payload.decode("utf-8", errors="replace")
            except Exception:
                continue

            soup = BeautifulSoup(html, "html.parser")
            for anchor in soup.find_all("a", href=True):
                href = str(anchor.get("href") or "").strip()
                if "/law/iowaCode/sections?codeChapter=" not in href:
                    continue
                chapter_url = urljoin(title_url, href)
                if chapter_url in seen_chapters:
                    continue
                seen_chapters.add(chapter_url)
                chapter_urls.append(chapter_url)
                parent_row = anchor.find_parent("tr")
                row_text = (
                    self._normalize_legal_text(
                        parent_row.get_text(" ", strip=True) or ""
                    )
                    if parent_row is not None
                    else ""
                )
                row_links = (
                    [
                        urljoin(
                            title_url,
                            str(link.get("href") or "").strip(),
                        )
                        for link in parent_row.find_all("a", href=True)
                    ]
                    if parent_row is not None
                    else []
                )
                chapter_frontier[chapter_url] = {
                    "label": row_text,
                    "reserved": bool(
                        re.search(r"\bRESERVED\b", row_text, re.IGNORECASE)
                    ),
                    "xml_url": next(
                        (
                            candidate
                            for candidate in row_links
                            if candidate.lower().endswith("_slim.xml")
                        ),
                        "",
                    ),
                }

        chapter_limit = int(os.getenv("IOWA_OFFICIAL_CHAPTER_LIMIT", "0") or "0")
        if chapter_limit > 0:
            chapter_urls = chapter_urls[:chapter_limit]
        discovered_chapters = int(len(chapter_urls))

        section_text_min_chars = max(
            80,
            int(os.getenv("IOWA_SECTION_TEXT_MIN_CHARS", "120") or "120"),
        )
        section_extract_timeout = max(
            4,
            int(os.getenv("IOWA_SECTION_EXTRACT_TIMEOUT_SECONDS", "12") or "12"),
        )
        section_limit = int(os.getenv("IOWA_OFFICIAL_SECTION_LIMIT", "0") or "0")
        checkpoint_every_statutes = max(
            10,
            int(os.getenv("IOWA_CHECKPOINT_EVERY_STATUTES", "50") or "50"),
        )
        checkpoint_every_chapters = max(
            1,
            int(os.getenv("IOWA_CHECKPOINT_EVERY_CHAPTERS", "8") or "8"),
        )
        sections_scanned_total = int(max(len(official_rows), resume_sections_scanned))
        sections_discovered_total = int(max(len(official_rows), resume_discovered_sections))

        def _progress_payload(*, chapters_scanned: int, codes_completed: int) -> Dict[str, int]:
            return {
                "titles_scanned": int(len(self._IOWA_TITLE_TOKENS)),
                "discovered_titles": int(len(self._IOWA_TITLE_TOKENS)),
                "chapters_scanned": int(max(0, chapters_scanned)),
                "discovered_chapters": int(discovered_chapters),
                "sections_scanned": int(max(0, sections_scanned_total)),
                "discovered_sections": int(max(0, sections_discovered_total)),
                "codes_completed": int(max(0, codes_completed)),
                "codes_total": 1,
                "resume_chapter_floor": int(max(0, resume_chapter_floor)),
            }

        def _append_xml_rows(
            xml_payload: bytes,
            *,
            chapter_number: str,
            xml_url: str,
        ) -> int:
            nonlocal sections_discovered_total, sections_scanned_total
            from .iowa_chapter_xml import (
                parse_iowa_chapter_xml,
                reserved_section_numbers,
            )

            provenance = self._last_parser_input_row_provenance()
            receipt = provenance.get("transport_receipt")
            digest = str(provenance.get("content_sha256") or "").strip().lower()
            if not re.fullmatch(r"[a-f0-9]{64}", digest):
                digest = hashlib.sha256(xml_payload).hexdigest()
            for section_number in reserved_section_numbers(xml_payload):
                key = section_number.casefold()
                terminal_section_dispositions[key] = {
                    "chapter_number": chapter_number,
                    "content_sha256": digest,
                    "disposition": "reserved",
                    "section_number": section_number,
                    "source_url": xml_url,
                    **(
                        {"transport_receipt": dict(receipt)}
                        if isinstance(receipt, Mapping)
                        else {}
                    ),
                }
            self._last_iowa_terminal_dispositions = list(
                terminal_section_dispositions.values()
            )

            remaining = (
                None
                if section_limit <= 0
                else max(0, section_limit - len(official_rows))
            )
            xml_rows = parse_iowa_chapter_xml(
                xml_payload,
                chapter=chapter_number,
                year=year,
                code_name=code_name,
                max_statutes=remaining,
            )
            xml_rows = self._bind_parser_input_provenance(
                xml_rows,
                parser_input_url=xml_url,
            )
            sections_discovered_total += len(xml_rows)
            sections_scanned_total += len(xml_rows)
            added = 0
            for row in xml_rows:
                section_key = (
                    str(row.section_number or "").lower(),
                    str(row.source_url or "").lower(),
                )
                if section_key in seen_section_keys:
                    continue
                seen_section_keys.add(section_key)
                official_rows.append(row)
                added += 1
            return added

        self._write_partial_checkpoint(
            official_rows,
            code_name=code_name,
            stage_label="iowa:chapter-discovery",
            extra=_progress_payload(chapters_scanned=0, codes_completed=0),
        )

        if official_rows:
            self.logger.info(
                "Iowa official tree: resumed %s statutes from partial checkpoint",
                len(official_rows),
            )
        if resume_chapter_floor > 0 and official_rows:
            self.logger.info(
                "Iowa official tree: resuming with chapter rewind floor=%s (prior chapters_scanned=%s)",
                resume_chapter_floor,
                resume_chapters_scanned,
            )

        for chapter_index, chapter_url in enumerate(chapter_urls, start=1):
            frontier_entry = dict(chapter_frontier.get(chapter_url) or {})
            if frontier_entry.get("reserved") is True:
                # The exact retained title row is the terminal disposition for
                # a reserved chapter (e.g. current Iowa Code chapter 763).
                continue
            if official_rows and chapter_index <= resume_chapter_floor:
                if chapter_index % checkpoint_every_chapters == 0:
                    self._write_partial_checkpoint(
                        official_rows,
                        code_name=code_name,
                        stage_label="iowa:resume-skip",
                        extra=_progress_payload(chapters_scanned=chapter_index, codes_completed=0),
                    )
                continue
            chapter_query = parse_qs(urlparse(chapter_url).query or "")
            chapter_number = str(
                (chapter_query.get("codeChapter") or [""])[0]
            ).strip()
            xml_url = str(frontier_entry.get("xml_url") or "").strip()
            if not xml_url and chapter_number:
                xml_url = (
                    f"{self.get_base_url()}/docs/publications/ICC/{year}"
                    f"/attachments/{chapter_number}_slim.xml"
                )

            chapter_payload = await self._request_bytes(
                chapter_url,
                timeout=chapter_page_timeout,
                allow_archival_fallback=official_archival_fallback,
            )
            if not chapter_payload:
                # The exact title frontier also exposes a chapter-level slim
                # XML locator.  It is the narrow official fallback when the
                # interactive section index is unavailable (203A in the
                # retained 2026 frontier).  The shared byte adapter retains a
                # direct/archive/cache body before it reaches this parser.
                xml_payload = (
                    await self._request_bytes(
                        xml_url,
                        timeout=section_doc_timeout,
                        allow_archival_fallback=official_archival_fallback,
                    )
                    if xml_url
                    else b""
                )
                if (
                    xml_payload
                    and chapter_number
                    and _append_xml_rows(
                        xml_payload,
                        chapter_number=chapter_number,
                        xml_url=xml_url,
                    )
                    > 0
                ):
                    continue
                raise RuntimeError(
                    "Iowa active official chapter lacked a retained chapter or "
                    "slim-XML parser input: "
                    f"chapter_url={chapter_url} xml_url={xml_url or 'missing'} "
                    f"label={frontier_entry.get('label') or 'missing'}"
                )
            try:
                chapter_html = chapter_payload.decode("utf-8", errors="replace")
            except Exception:
                if chapter_index % checkpoint_every_chapters == 0:
                    self._write_partial_checkpoint(
                        official_rows,
                        code_name=code_name,
                        stage_label="iowa:chapter-decode-miss",
                        extra=_progress_payload(chapters_scanned=chapter_index, codes_completed=0),
                    )
                continue

            chapter_soup = BeautifulSoup(chapter_html, "html.parser")
            if chapter_number:
                xml_payload = await self._request_bytes(
                    xml_url,
                    timeout=section_doc_timeout,
                    allow_archival_fallback=official_archival_fallback,
                )
                if xml_payload:
                    added = _append_xml_rows(
                        xml_payload,
                        chapter_number=chapter_number,
                        xml_url=xml_url,
                    )
                    if added:
                        continue

            for row in chapter_soup.find_all("tr"):
                if section_limit > 0 and len(official_rows) >= section_limit:
                    self._write_partial_checkpoint(
                        official_rows,
                        code_name=code_name,
                        stage_label="iowa:section-limit",
                        force=True,
                        extra=_progress_payload(chapters_scanned=chapter_index, codes_completed=0),
                    )
                    return official_rows
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue

                section_label = self._normalize_legal_text(cells[0].get_text(" ", strip=True))
                if not section_label:
                    continue

                links = [str(link.get("href") or "").strip() for link in row.find_all("a", href=True)]
                rtf_href = next((href for href in links if href.lower().endswith(".rtf")), "")
                pdf_href = next((href for href in links if href.lower().endswith(".pdf")), "")
                if not rtf_href and not pdf_href:
                    continue

                sections_discovered_total += 1
                rtf_url = urljoin(chapter_url, rtf_href) if rtf_href else ""
                pdf_url = urljoin(chapter_url, pdf_href) if pdf_href else ""
                preferred_source = rtf_url or pdf_url
                if not preferred_source:
                    continue

                section_number = self._extract_section_number(section_label) or ""
                if not section_number:
                    number_match = re.search(
                        r"(?:^|\s|§)(\d+[A-Za-z]?(?:\.\d+[A-Za-z]*)+)",
                        section_label,
                    )
                    if number_match:
                        section_number = str(number_match.group(1) or "").strip()
                if not section_number and rtf_href:
                    filename = str(rtf_href).split("/")[-1]
                    section_number = re.sub(r"\.rtf$", "", filename, flags=re.IGNORECASE)
                if not section_number:
                    continue

                if section_number.casefold() in terminal_section_dispositions:
                    sections_scanned_total += 1
                    continue

                section_name = re.sub(
                    rf"^§\s*{re.escape(section_number)}\s*[-–—:]?\s*",
                    "",
                    section_label,
                ).strip()
                section_name = section_name or f"Iowa Code {section_number}"

                section_key = (section_number.lower(), preferred_source.lower())
                sections_scanned_total += 1
                if section_key in seen_section_keys:
                    continue
                seen_section_keys.add(section_key)

                section_text = ""
                parser_input_url = ""
                for candidate_url in [rtf_url, pdf_url]:
                    if not candidate_url:
                        continue
                    raw_bytes = await self._request_bytes(
                        candidate_url,
                        timeout=section_doc_timeout,
                        allow_archival_fallback=official_archival_fallback,
                    )
                    if not raw_bytes:
                        continue

                    try:
                        document_extract = await asyncio.wait_for(
                            self._extract_text_from_document_bytes(
                                source_url=candidate_url,
                                raw_bytes=raw_bytes,
                            ),
                            timeout=float(section_extract_timeout),
                        )
                    except asyncio.TimeoutError:
                        self.logger.warning(
                            "Iowa extract timeout for %s after %ss",
                            candidate_url,
                            section_extract_timeout,
                        )
                        document_extract = {}
                    except Exception:
                        document_extract = {}
                    if isinstance(document_extract, dict):
                        candidate_text = self._normalize_legal_text(str(document_extract.get("text") or ""))
                    else:
                        try:
                            candidate_text = self._normalize_legal_text(
                                raw_bytes.decode("utf-8", errors="replace")
                            )
                        except Exception:
                            candidate_text = ""
                    if self._is_exact_reserved_section_text(
                        candidate_text,
                        section_number,
                    ):
                        provenance = self._last_parser_input_row_provenance()
                        receipt = provenance.get("transport_receipt")
                        digest = str(
                            provenance.get("content_sha256") or ""
                        ).strip().lower()
                        if not re.fullmatch(r"[a-f0-9]{64}", digest):
                            digest = hashlib.sha256(raw_bytes).hexdigest()
                        terminal_section_dispositions[section_number.casefold()] = {
                            "chapter_number": chapter_number,
                            "content_sha256": digest,
                            "disposition": "reserved",
                            "section_number": section_number,
                            "source_url": candidate_url,
                            **(
                                {"transport_receipt": dict(receipt)}
                                if isinstance(receipt, Mapping)
                                else {}
                            ),
                        }
                        self._last_iowa_terminal_dispositions = list(
                            terminal_section_dispositions.values()
                        )
                        parser_input_url = candidate_url
                        break
                    if len(candidate_text) >= section_text_min_chars:
                        section_text = candidate_text
                        parser_input_url = candidate_url
                        break

                if section_number.casefold() in terminal_section_dispositions:
                    continue

                if not section_text:
                    if self._state_law_acquisition_ledger is not None:
                        raise RuntimeError(
                            "Iowa section lacked a retained substantive parser input: "
                            f"section={section_number} chapter={chapter_number}"
                        )
                    section_text = f"{section_label}. Source: {preferred_source}"

                statute = NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § {section_number}",
                        code_name=code_name,
                        chapter_number=chapter_number,
                        section_number=section_number,
                        section_name=section_name[:200],
                        full_text=section_text,
                        source_url=parser_input_url or preferred_source,
                        legal_area=self._identify_legal_area(section_name or section_text),
                        official_cite=f"Iowa Code § {section_number}",
                        metadata=StatuteMetadata(),
                        structured_data={
                            "source_kind": "official_iowa_code_section_document",
                            "discovery_method": "official_iowa_title_chapter_sections",
                            "code_year": year,
                            "chapter_number": chapter_number,
                            "skip_hydrate": len(section_text) >= section_text_min_chars,
                        },
                    )
                self._bind_parser_input_provenance(
                    [statute],
                    parser_input_url=parser_input_url,
                )
                official_rows.append(statute)

                if len(official_rows) == 1 or len(official_rows) % checkpoint_every_statutes == 0:
                    self.logger.info(
                        "Iowa official tree: chapters_scanned=%s/%s statutes_so_far=%s discovered_sections=%s",
                        chapter_index,
                        discovered_chapters,
                        len(official_rows),
                        sections_discovered_total,
                    )
                    self._write_partial_checkpoint(
                        official_rows,
                        code_name=code_name,
                        stage_label="iowa:section-scan",
                        extra=_progress_payload(chapters_scanned=chapter_index, codes_completed=0),
                    )

            if chapter_index % checkpoint_every_chapters == 0:
                self._write_partial_checkpoint(
                    official_rows,
                    code_name=code_name,
                    stage_label="iowa:chapter-scan",
                    extra=_progress_payload(chapters_scanned=chapter_index, codes_completed=0),
                )

        self._write_partial_checkpoint(
            official_rows,
            code_name=code_name,
            stage_label="iowa:complete",
            force=True,
            extra=_progress_payload(chapters_scanned=discovered_chapters, codes_completed=1),
        )
        return official_rows

    async def _scrape_direct_seed_sections(self, code_name: str, max_statutes: int = 2) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        seeds = [
            ("1.1", "https://www.legis.iowa.gov/docs/code/1.1.html"),
            ("1.2", "https://www.legis.iowa.gov/docs/code/1.2.html"),
        ]
        out: List[NormalizedStatute] = []
        for section_number, source_url in seeds[: max(1, int(max_statutes or 1))]:
            html = await self._request_text_direct(source_url, timeout=18)
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            text = self._normalize_legal_text(soup.get_text(" ", strip=True))
            if len(text) < 80:
                continue
            first_sentence = text.split(".", 2)
            section_name = first_sentence[1].strip() if len(first_sentence) > 1 else f"Iowa Code {section_number}"
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:200] or f"Iowa Code {section_number}",
                    full_text=text,
                    source_url=source_url,
                    legal_area=self._identify_legal_area(text),
                    official_cite=f"Iowa Code § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_iowa_code_html",
                        "discovery_method": "official_seed_section",
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    async def _request_text_direct(self, url: str, timeout: int = 18) -> str:
        payload = await self._fetch_parser_input_with_transport(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout_seconds=max(1, int(timeout or 18)),
            # Full-corpus callers preserve the existing opt-in archival policy.
            allow_archival_fallback=False,
            media_type="text/html",
            provider="iowa_direct",
        )
        return payload.decode("utf-8", errors="replace") if payload else ""

    async def _request_bytes_direct(self, url: str, timeout: int = 25) -> bytes:
        return await self._request_bytes(
            url,
            timeout=timeout,
            allow_archival_fallback=False,
        )

    async def _request_bytes(
        self,
        url: str,
        *,
        timeout: int = 25,
        allow_archival_fallback: bool = False,
    ) -> bytes:
        return await self._fetch_parser_input_with_transport(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout_seconds=max(3, int(timeout or 25)),
            # The caller controls opt-in archival recovery for official HTML,
            # XML, RTF, and PDF locators.
            allow_archival_fallback=allow_archival_fallback,
            provider="iowa_direct",
        )

    async def _scrape_live_code_stubs(self, code_name: str, max_statutes: int = 160) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError:
            return []

        url = "https://www.legis.iowa.gov/docs/code/"
        try:
            payload = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=35)
            if not payload:
                return []
        except Exception:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        out: List[NormalizedStatute] = []
        seen = set()
        for a in soup.find_all("a", href=True):
            if len(out) >= max_statutes:
                break
            href = str(a.get("href") or "").strip()
            text = str(a.get_text(" ", strip=True) or "").strip()
            if not href:
                continue
            full_url = urljoin(url, href)
            if "/docs/code/" not in full_url.lower():
                continue
            if not any(ch.isdigit() for ch in text + href):
                continue

            section_number = self._extract_section_number(text) or re.sub(r"[^0-9A-Za-z.-]+", "-", href).strip("-/")
            if not section_number:
                continue
            key = section_number.lower()
            if key in seen:
                continue
            seen.add(key)
            section_name = text[:200] if text else f"Iowa Code {section_number}"

            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name,
                    full_text=f"Iowa Code {section_name}: {full_url}",
                    source_url=full_url,
                    legal_area=self._identify_legal_area(section_name),
                    official_cite=f"Iowa Code {section_number}",
                    metadata=StatuteMetadata(),
                )
            )

        return out

    async def _scrape_archived_code_stubs(self, code_name: str, max_statutes: int = 120) -> List[NormalizedStatute]:
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx?url=www.legis.iowa.gov/docs/code/*"
            "&output=json&filter=statuscode:200&collapse=digest"
            f"&limit={max(1, int(max_statutes) * 8)}"
        )
        rows = await self._fetch_cdx_rows(cdx_url, timeout=45)
        if not rows:
            return []

        if not isinstance(rows, list) or len(rows) < 2:
            return []

        out: List[NormalizedStatute] = []
        seen = set()
        for row in rows[1:]:
            if len(out) >= max_statutes:
                break
            if not isinstance(row, list) or len(row) < 3:
                continue
            ts = str(row[1] or "").strip()
            original = str(row[2] or "").strip()
            if not ts or not original:
                continue
            if "/docs/code/" not in original:
                continue

            path = original.split("/docs/code/", 1)[-1]
            label = path.strip("/")
            if not label:
                continue
            label = re.sub(r"\.[A-Za-z0-9]+$", "", label)
            label = label.replace("/", "-")
            label = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-")
            if not label:
                continue
            key = label.lower()
            if key in seen:
                continue
            seen.add(key)

            encoded = urllib.parse.quote(original, safe=':/?=&%.-_')
            source_url = f"https://web.archive.org/web/{ts}/{encoded}"
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {label}",
                    code_name=code_name,
                    section_number=label,
                    section_name=f"Iowa Code {label}",
                    full_text=f"Iowa Code {label}: {source_url}",
                    source_url=source_url,
                    legal_area=self._identify_legal_area(label),
                    official_cite=f"Iowa Code {label}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "iowa_wayback_code_stub",
                        "discovery_method": "wayback_cdx",
                        "skip_hydrate": True,
                    },
                )
            )

        return out

    async def _fetch_cdx_rows(self, cdx_url: str, timeout: int = 45) -> List[List[object]]:
        return await self._fetch_wayback_cdx_rows(
            cdx_url,
            timeout_seconds=timeout,
        )

    def official_title_url(self, title_token: str, year: str | None = None) -> str:
        code_year = str(year or self.OFFICIAL_CODE_YEAR).strip() or self.OFFICIAL_CODE_YEAR
        token = str(title_token or "").strip().upper()
        return (
            f"{self.get_base_url()}/law/iowaCode/chapters"
            f"?title={urllib.parse.quote(token)}&year={urllib.parse.quote(code_year)}"
        )

    def official_title_catalog(self, year: str | None = None) -> List[Dict[str, str]]:
        """Return the exhaustive official Iowa Code title catalog."""

        rows: List[Dict[str, str]] = []
        for token in self._IOWA_TITLE_TOKENS:
            url = self.official_title_url(token, year=year)
            rows.append(
                {
                    "canonical_key": f"ia:title-{token.lower()}",
                    "source_url": url,
                    "label": f"Title {token}",
                    "title_token": token,
                    "text": (
                        f"Iowa Code Title {token} official catalog unit retained from {url}"
                    ),
                }
            )
        return rows

    def _official_ssl_context(self, *, unverified: bool = False):
        if unverified:
            return ssl._create_unverified_context()
        return ssl.create_default_context()

    def _official_http_get(self, url: str, timeout: int = 20) -> Tuple[bytes, bytes, bytes]:
        """Fetch one official Iowa URL and retain request/response/body bytes."""

        parsed = urllib.parse.urlparse(url)
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
                "User-Agent": "ipfs-datasets-open-us-law-iowa/1.0",
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            },
            method="GET",
        )
        last_exc: Exception | None = None
        body = b""
        status = 0
        header_block = ""
        for unverified in (True, False):
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
            raise RuntimeError(f"official Iowa GET failed for {url}: {last_exc}") from last_exc
        if status != 200 or not body:
            raise RuntimeError(f"official Iowa GET returned HTTP {status} for {url}")
        response_bytes = f"HTTP/1.1 {status} OK\n{header_block}\n".encode("utf-8") + body
        return request_bytes, response_bytes, body

    def _parse_official_title_index(self, html: str, index_url: str) -> List[Dict[str, str]]:
        """Parse official Iowa Code title units from a live statutory index page."""

        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError("BeautifulSoup is required for official Iowa discovery") from exc

        soup = BeautifulSoup(html, "html.parser")
        units: List[Dict[str, str]] = []
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            href = urllib.parse.urljoin(index_url, str(link.get("href") or "").strip())
            match = self._TITLE_QUERY_RE.search(href)
            if not match:
                continue
            token = match.group(1).strip().upper()
            if token not in self._IOWA_TITLE_TOKENS:
                continue
            key = f"ia:title-{token.lower()}"
            if key in seen:
                continue
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            if not label:
                label = f"Title {token}"
            seen.add(key)
            units.append(
                {
                    "canonical_key": key,
                    "source_url": href,
                    "label": label,
                    "title_token": token,
                    "text": (
                        f"Iowa Code Title {token} official title index entry "
                        f"retained from {href}"
                    ),
                }
            )
        return units

    def fetch_official(self, code: str = "IA"):
        """Acquire the uncapped official Iowa Code title frontier.

        Live HTTPS retains the official statutory landing page. Every Iowa
        Code title is enumerated with an official legislature URL.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or self.state_code or "IA").strip().upper()
        if normalized != "IA":
            raise ValueError(f"IowaScraper cannot acquire {normalized}")
        index_url = self.OFFICIAL_ENTRY_URL
        request_bytes, response_bytes, index_body = self._official_http_get(index_url)
        html = index_body.decode("utf-8", errors="replace")
        discovered = {
            unit["title_token"]: unit for unit in self._parse_official_title_index(html, index_url)
        }
        units = self.official_title_catalog()
        for unit in units:
            live = discovered.get(unit["title_token"])
            if live:
                unit["source_url"] = live["source_url"]
                unit["label"] = live["label"]
                unit["text"] = live["text"]
        if len(units) < 3:
            raise RuntimeError(
                f"official Iowa title catalog is incomplete: {len(units)} units"
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
            jurisdiction_code="IA",
            request_bytes=request_bytes,
            response_bytes=response_bytes,
            body_bytes=catalog,
            source_domain=self.OFFICIAL_DOMAIN,
            source_path=self.OFFICIAL_ENTRY_PATH,
            frontier=frontier,
            rows=rows,
            transport_kind="live_https",
            fixture=False,
            first_hierarchy_unit=rows[0]["canonical_key"],
            last_hierarchy_unit=rows[-1]["canonical_key"],
        )


# Register this scraper with the registry
StateScraperRegistry.register("IA", IowaScraper)
