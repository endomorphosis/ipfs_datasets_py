"""Scraper for Iowa state laws.

This module contains the scraper for Iowa statutes from the official state legislative website.
"""

import asyncio
import json
import os
import re
import urllib.parse
import urllib.request
from typing import List, Dict, Optional
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class IowaScraper(BaseStateScraper):
    """Scraper for Iowa state laws from https://www.legis.iowa.gov"""

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
        if self._full_corpus_enabled() and max_statutes is None:
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
                "Iowa official section crawl returned %s rows (min=%s); falling back to legacy discovery",
                len(official_sections),
                accept_min,
            )

        return_threshold = self._bounded_return_threshold(160)
        if max_statutes is not None:
            return_threshold = max(1, min(return_threshold, int(max_statutes)))

        live_stubs = await self._scrape_live_code_stubs(code_name, max_statutes=max(10, return_threshold))

        archival_limit = max(10, return_threshold)
        if self._full_corpus_enabled() and max_statutes is None:
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
        if self._full_corpus_enabled() and max_statutes is None:
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
            "https://law.justia.com/codes/iowa/",
            "http://web.archive.org/web/20250101000000/https://law.justia.com/codes/iowa/",
        ]

        seen = set()
        best_statutes: List[NormalizedStatute] = list(merged)
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            statutes = await self._generic_scrape(code_name, candidate, "Iowa Code", max_sections=max(10, return_threshold))
            _merge(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(merged) > len(best_statutes):
                best_statutes = list(merged)
            if len(statutes) >= return_threshold:
                return list(merged) if len(merged) >= return_threshold else statutes

        if len(merged) > len(best_statutes):
            best_statutes = list(merged)

        return best_statutes

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
        chapter_rewind = max(
            0,
            int(os.getenv("STATE_SCRAPER_IA_RESUME_CHAPTER_REWIND", "8") or "8"),
        )
        resume_chapter_floor = max(0, resume_chapters_scanned - chapter_rewind)

        official_rows: List[NormalizedStatute] = []
        seen_section_keys = set()
        for statute in resumed:
            section_number = str(getattr(statute, "section_number", "") or "").strip()
            source_url = str(getattr(statute, "source_url", "") or "").strip()
            section_key = (section_number.lower(), source_url.lower())
            if section_key in seen_section_keys:
                continue
            seen_section_keys.add(section_key)
            official_rows.append(statute)

        chapter_urls: List[str] = []
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
            payload = await self._request_bytes_direct(title_url, timeout=chapter_page_timeout)
            if not payload and official_archival_fallback:
                payload = await self._fetch_page_content_with_archival_fallback(
                    title_url,
                    timeout_seconds=chapter_page_timeout,
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
            if official_rows and chapter_index <= resume_chapter_floor:
                if chapter_index % checkpoint_every_chapters == 0:
                    self._write_partial_checkpoint(
                        official_rows,
                        code_name=code_name,
                        stage_label="iowa:resume-skip",
                        extra=_progress_payload(chapters_scanned=chapter_index, codes_completed=0),
                    )
                continue
            chapter_payload = await self._request_bytes_direct(chapter_url, timeout=chapter_page_timeout)
            if not chapter_payload and official_archival_fallback:
                chapter_payload = await self._fetch_page_content_with_archival_fallback(
                    chapter_url,
                    timeout_seconds=chapter_page_timeout,
                )
            if not chapter_payload:
                if chapter_index % checkpoint_every_chapters == 0:
                    self._write_partial_checkpoint(
                        official_rows,
                        code_name=code_name,
                        stage_label="iowa:chapter-fetch-miss",
                        extra=_progress_payload(chapters_scanned=chapter_index, codes_completed=0),
                    )
                continue
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
            chapter_query = parse_qs(urlparse(chapter_url).query or "")
            chapter_number = str((chapter_query.get("codeChapter") or [""])[0]).strip() or None

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
                for candidate_url in [rtf_url, pdf_url]:
                    if not candidate_url:
                        continue
                    raw_bytes = await self._request_bytes_direct(
                        candidate_url,
                        timeout=section_doc_timeout,
                    )
                    if not raw_bytes and official_archival_fallback:
                        raw_bytes = await self._fetch_page_content_with_archival_fallback(
                            candidate_url,
                            timeout_seconds=section_doc_timeout,
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
                    if len(candidate_text) >= section_text_min_chars:
                        section_text = candidate_text
                        break

                if not section_text:
                    section_text = f"{section_label}. Source: {preferred_source}"

                official_rows.append(
                    NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § {section_number}",
                        code_name=code_name,
                        chapter_number=chapter_number,
                        section_number=section_number,
                        section_name=section_name[:200],
                        full_text=section_text,
                        source_url=preferred_source,
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
                )

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
        def _request() -> str:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except Exception:
                return ""

        try:
            return await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 2)
        except Exception:
            return ""

    async def _request_bytes_direct(self, url: str, timeout: int = 25) -> bytes:
        def _request() -> bytes:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=max(3, int(timeout or 25))) as resp:
                    return bytes(resp.read() or b"")
            except Exception:
                return b""

        try:
            return await asyncio.wait_for(asyncio.to_thread(_request), timeout=max(4, int(timeout or 25) + 2))
        except Exception:
            return b""

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
        # Prefer the shared archival/unified fetch chain so archive discovery
        # participates in provider fallback and fetch analytics.
        try:
            payload = await self._fetch_page_content_with_archival_fallback(
                cdx_url,
                timeout_seconds=timeout,
            )
            if payload:
                rows = json.loads(payload.decode("utf-8", errors="ignore"))
                if isinstance(rows, list):
                    return rows
        except Exception:
            pass

        # Direct HTTP fallback for environments where unified fetch cannot initialize.
        candidates = [str(cdx_url or "")]
        if candidates[0].startswith("https://"):
            candidates.append("http://" + candidates[0][8:])
        elif candidates[0].startswith("http://"):
            candidates.append("https://" + candidates[0][7:])

        for candidate in candidates:
            try:
                req = urllib.request.Request(candidate, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=max(1, int(timeout))) as resp:
                    rows = json.loads(resp.read().decode("utf-8", errors="ignore"))
                if isinstance(rows, list):
                    return rows
            except Exception:
                continue
        return []


# Register this scraper with the registry
StateScraperRegistry.register("IA", IowaScraper)
