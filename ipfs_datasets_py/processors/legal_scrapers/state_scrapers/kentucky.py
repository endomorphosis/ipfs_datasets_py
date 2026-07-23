"""Scraper for Kentucky state laws.

This module contains the scraper for Kentucky statutes from the official state legislative website.
"""

from typing import List, Dict, Optional, Tuple
import os
import re
import time
from urllib.parse import urljoin

from ipfs_datasets_py.utils import anyio_compat as asyncio

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class KentuckyScraper(BaseStateScraper):
    """Scraper for Kentucky state laws from https://legislature.ky.gov"""

    _KY_STATUTES_BASE = "https://apps.legislature.ky.gov/law/statutes/"
    _KY_SECTION_URL_RE = re.compile(r"/law/statutes/statute\.aspx\?id=\d+$", re.IGNORECASE)
    _KY_CHAPTER_URL_RE = re.compile(r"/law/statutes/chapter\.aspx\?id=\d+$", re.IGNORECASE)
    _CHAPTER_LABEL_RE = re.compile(r"^\s*chapter\s+(\d+[A-Za-z]?)\b", re.IGNORECASE)
    _SECTION_LABEL_RE = re.compile(r"^\s*(?:KRS\s+)?(?:§\s*)?(\d+\.\d+[A-Za-z0-9\.-]*|\.\d+[A-Za-z0-9\.-]*)\b")

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._KY_SECTION_URL_RE.search(source):
                section_name = str(statute.section_name or "")
                if str(statute.section_number or "").startswith("Section-"):
                    # KRS section rows often start with ".010" style identifiers.
                    m = re.search(r"^\.(\d+[A-Za-z0-9\.-]*)\b", section_name)
                    if m:
                        statute.section_number = m.group(1)
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for Kentucky's legislative website."""
        return "https://apps.legislature.ky.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Kentucky."""
        return [{
            "name": "Kentucky Revised Statutes",
            "url": self._KY_STATUTES_BASE,
            "type": "Code"
        }]

    async def _fetch_official_ky_bytes(self, url: str, timeout_seconds: int = 5) -> bytes:
        """Fetch Kentucky's official KRS pages directly.

        The official KRS index/chapter/section endpoints respond quickly to
        normal HTTP requests, while the generic archival fetch chain may import
        and initialize unrelated web/search infrastructure. Keep this official
        corpus path direct and bounded.
        """
        timeout = max(1, int(timeout_seconds or 5))
        cached = await self._load_page_bytes_from_any_cache(url)
        if cached:
            return cached

        def _request() -> bytes:
            try:
                import requests

                response = requests.get(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-kentucky-krs-scraper/2.0",
                        "Accept": "text/html,application/pdf,*/*;q=0.8",
                    },
                    timeout=timeout,
                )
                if int(response.status_code or 0) != 200:
                    return b""
                return bytes(response.content or b"")
            except Exception:
                return b""

        try:
            payload = await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 1)
        except asyncio.TimeoutError:
            self.logger.warning("Kentucky KRS direct fetch timed out after %ss: %s", timeout, url)
            payload = b""

        self._record_fetch_event(provider="requests_direct", success=bool(payload))
        if payload:
            await self._cache_successful_page_fetch(url=url, payload=payload, provider="requests_direct")
        return payload

    async def _fetch_html(self, url: str, timeout_seconds: int = 5) -> str:
        payload = await self._fetch_official_ky_bytes(url, timeout_seconds=timeout_seconds)
        if not payload:
            return ""
        return payload.decode("utf-8", errors="replace")

    def _extract_chapter_number(self, label: str) -> str:
        match = self._CHAPTER_LABEL_RE.search(str(label or ""))
        return match.group(1).strip() if match else ""

    def _section_number_from_label(self, label: str, chapter_number: str) -> str:
        match = self._SECTION_LABEL_RE.search(str(label or ""))
        if not match:
            return ""

        value = match.group(1).strip()
        if value.startswith("."):
            return f"{chapter_number}{value}" if chapter_number else value.lstrip(".")
        return value

    def _section_name_from_label(self, label: str, section_number: str) -> str:
        value = re.sub(r"\s+", " ", str(label or "")).strip()
        if not value:
            return ""
        variants = [
            rf"^\s*KRS\s+{re.escape(section_number)}\s*",
            rf"^\s*§\s*{re.escape(section_number)}\s*",
        ]
        if "." in section_number:
            suffix = "." + section_number.split(".", 1)[1]
            variants.append(rf"^\s*{re.escape(suffix)}\s*")
        variants.append(r"^\s*\.\d+[A-Za-z0-9\.-]*\s*")
        for pattern in variants:
            value = re.sub(pattern, "", value, count=1, flags=re.IGNORECASE).strip()
        return value

    def _looks_like_failed_pdf_extraction(self, text: str) -> bool:
        value = str(text or "").strip()
        if not value:
            return False
        if value.startswith("%PDF-") or " startxref " in value[:4000] or " endobj " in value[:4000]:
            return True
        sample = value[:2000]
        controlish = sum(1 for char in sample if char == "\ufffd" or (ord(char) < 32 and char not in "\n\r\t"))
        return bool(sample) and (controlish / len(sample)) > 0.05

    async def _discover_chapter_links(self) -> List[Tuple[str, str, str]]:
        """Discover official KRS chapter pages from the Kentucky statutes index."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        html = await self._fetch_html(self._KY_STATUTES_BASE, timeout_seconds=5)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        chapter_links: List[Tuple[str, str, str]] = []
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            href = urljoin(self._KY_STATUTES_BASE, str(link.get("href") or ""))
            if not self._KY_CHAPTER_URL_RE.search(href):
                continue
            if href in seen:
                continue
            if not label.upper().startswith("CHAPTER "):
                continue
            chapter_number = self._extract_chapter_number(label)
            if not chapter_number:
                continue
            seen.add(href)
            chapter_links.append((href, label, chapter_number))
        return chapter_links

    async def _discover_section_links(
        self,
        chapter_url: str,
        chapter_label: str,
        chapter_number: str,
    ) -> List[Tuple[str, str, str, str]]:
        """Discover section-level KRS PDF endpoints from one official chapter page."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        html = await self._fetch_html(chapter_url, timeout_seconds=5)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        section_links: List[Tuple[str, str, str, str]] = []
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            href = urljoin(chapter_url, str(link.get("href") or ""))
            if not self._KY_SECTION_URL_RE.search(href):
                continue
            if href in seen:
                continue
            section_number = self._section_number_from_label(label, chapter_number)
            if not section_number:
                continue
            seen.add(href)
            section_links.append((href, label, section_number, chapter_label))
        return section_links

    async def _build_statute_from_section_page(
        self,
        code_name: str,
        section_url: str,
        section_label: str,
        section_number: str,
        chapter_url: str,
        chapter_label: str,
        chapter_number: str,
    ) -> Optional[NormalizedStatute]:
        raw_bytes = await self._fetch_official_ky_bytes(section_url, timeout_seconds=5)
        extracted_text = ""
        method = "unknown"
        if raw_bytes:
            document_extraction = await self._extract_text_from_document_bytes(
                source_url=section_url,
                raw_bytes=raw_bytes,
            )
            if isinstance(document_extraction, dict):
                extracted_text = self._normalize_legal_text(str(document_extraction.get("text") or ""))
                method = str(document_extraction.get("method") or "document_processor")
            else:
                try:
                    extracted_text = self._normalize_legal_text(
                        self._extract_best_content_text(raw_bytes.decode("utf-8", errors="replace"))
                    )
                    method = "html_text"
                except Exception:
                    extracted_text = ""
        if self._looks_like_failed_pdf_extraction(extracted_text):
            extracted_text = ""
            method = "failed_pdf_extraction"

        section_name = self._section_name_from_label(section_label, section_number)
        if extracted_text:
            first_line = re.sub(r"\s+", " ", extracted_text.splitlines()[0] if "\n" in extracted_text else extracted_text[:240]).strip()
            parsed_name = self._section_name_from_label(first_line, section_number)
            if parsed_name:
                section_name = parsed_name[:200]

        effective_date = None
        history: List[str] = []
        if extracted_text:
            effective_match = re.search(r"\bEffective:\s*(.*?)(?:\s+History:|$)", extracted_text, re.IGNORECASE | re.DOTALL)
            if effective_match:
                effective_date = effective_match.group(1).strip()
            history_match = re.search(r"\bHistory:\s*(.+)$", extracted_text, re.IGNORECASE | re.DOTALL)
            if history_match:
                history = [self._normalize_legal_text(history_match.group(1))]

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"KRS-{section_number}",
            code_name=code_name,
            chapter_number=chapter_number,
            chapter_name=chapter_label,
            section_number=section_number,
            section_name=section_name or section_label[:200],
            short_title=section_name or section_label[:200],
            full_text=extracted_text or f"KRS {section_number}: {section_label}",
            legal_area=self._identify_legal_area(code_name),
            source_url=section_url,
            official_cite=f"Ky. Rev. Stat. § {section_number}",
            metadata=StatuteMetadata(effective_date=effective_date, history=history),
            structured_data={
                "source_kind": "official_krs_section_pdf",
                "discovery_method": "official_chapter_index",
                "chapter_url": chapter_url,
                "extraction_method": method,
                "skip_hydrate": bool(extracted_text) or method == "failed_pdf_extraction",
            },
        )
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: int | None = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Kentucky's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = max(1, int(max_statutes)) if max_statutes else None
        statutes: List[NormalizedStatute] = []

        chapter_links = await self._discover_chapter_links()
        chapter_cap_raw = str(os.getenv("KENTUCKY_FULL_CORPUS_MAX_CHAPTERS", "") or "").strip()
        chapter_cap = 0
        if chapter_cap_raw:
            try:
                chapter_cap = max(0, int(chapter_cap_raw))
            except Exception:
                chapter_cap = 0
        if chapter_cap > 0:
            chapter_links = chapter_links[:chapter_cap]

        total_chapters = len(chapter_links)
        self.logger.info(
            "Kentucky official KRS discovery: chapters=%s limit=%s fetch_cache=%s",
            total_chapters,
            limit or "unbounded",
            "on" if getattr(self, "_fetch_cache_enabled", False) else "off",
        )
        heartbeat_seconds = max(
            1,
            int(os.getenv("KENTUCKY_SCRAPER_HEARTBEAT_SECONDS", "30") or "30"),
        )
        section_heartbeat_every = max(
            1,
            int(os.getenv("KENTUCKY_SCRAPER_SECTION_HEARTBEAT_EVERY", "100") or "100"),
        )
        last_heartbeat = time.monotonic()
        total_sections_seen = 0

        for chapter_index, (chapter_url, chapter_label, chapter_number) in enumerate(chapter_links, start=1):
            if limit is not None and len(statutes) >= limit:
                break

            chapter_started_at = time.monotonic()
            self.logger.info(
                "Kentucky KRS chapter start: index=%s/%s chapter=%s statutes_so_far=%s url=%s",
                chapter_index,
                total_chapters,
                chapter_label,
                len(statutes),
                chapter_url,
            )
            section_links = await self._discover_section_links(
                chapter_url=chapter_url,
                chapter_label=chapter_label,
                chapter_number=chapter_number,
            )
            self.logger.info(
                "Kentucky KRS chapter discovered sections: index=%s/%s chapter=%s sections=%s",
                chapter_index,
                total_chapters,
                chapter_label,
                len(section_links),
            )
            for section_index, (section_url, section_label, section_number, discovered_chapter_label) in enumerate(section_links, start=1):
                if limit is not None and len(statutes) >= limit:
                    break
                total_sections_seen += 1
                now = time.monotonic()
                if (
                    section_index == 1
                    or section_index % section_heartbeat_every == 0
                    or now - last_heartbeat >= heartbeat_seconds
                ):
                    self.logger.info(
                        "Kentucky KRS section progress: chapter_index=%s/%s chapter=%s section_index=%s/%s total_sections_seen=%s statutes_so_far=%s section=%s",
                        chapter_index,
                        total_chapters,
                        chapter_label,
                        section_index,
                        len(section_links),
                        total_sections_seen,
                        len(statutes),
                        section_number,
                    )
                    last_heartbeat = now
                try:
                    statute = await self._build_statute_from_section_page(
                        code_name=code_name,
                        section_url=section_url,
                        section_label=section_label,
                        section_number=section_number,
                        chapter_url=chapter_url,
                        chapter_label=discovered_chapter_label,
                        chapter_number=chapter_number,
                    )
                except Exception as exc:
                    self.logger.warning(
                        "Kentucky KRS section failed: chapter=%s section=%s url=%s error=%s",
                        chapter_label,
                        section_number,
                        section_url,
                        exc,
                    )
                    continue
                if statute is not None and self._KY_SECTION_URL_RE.search(str(statute.source_url or "")):
                    statute.structured_data = {
                        **(statute.structured_data or {}),
                        "chapter_url": chapter_url,
                    }
                    statutes.append(statute)
            self.logger.info(
                "Kentucky KRS chapter done: index=%s/%s chapter=%s sections=%s statutes_so_far=%s elapsed=%.2fs",
                chapter_index,
                total_chapters,
                chapter_label,
                len(section_links),
                len(statutes),
                time.monotonic() - chapter_started_at,
            )

        if statutes:
            return statutes[:limit] if limit is not None else statutes

        fallback_limit = limit or 200
        fallback_candidates = [self._KY_STATUTES_BASE]
        if code_url and code_url not in fallback_candidates:
            fallback_candidates.append(code_url)

        best_statutes: List[NormalizedStatute] = []
        for candidate in fallback_candidates:
            try:
                generic_statutes = await self._generic_scrape(
                    code_name,
                    candidate,
                    "Ky. Rev. Stat.",
                    max_sections=fallback_limit,
                )
            except Exception:
                continue
            filtered = self._filter_section_level(generic_statutes)
            generic_statutes = (filtered or generic_statutes)[:fallback_limit]
            if len(generic_statutes) > len(best_statutes):
                best_statutes = generic_statutes
            if limit is not None and len(best_statutes) >= limit:
                break

        return best_statutes[:fallback_limit]


# Register this scraper with the registry
StateScraperRegistry.register("KY", KentuckyScraper)
