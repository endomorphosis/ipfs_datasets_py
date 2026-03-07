"""Scraper for Indiana state laws.

This module contains the scraper for Indiana statutes from archived official
Indiana General Assembly static-document chapter PDFs.
"""

import re
import subprocess
from urllib.parse import quote
from typing import Dict, List

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class IndianaScraper(BaseStateScraper):
    """Scraper for Indiana state laws from archived iga.in.gov sources."""

    _ARCHIVE_CHAPTER_PDFS = [
        "http://web.archive.org/web/20170215063144/http://iga.in.gov/static-documents/0/0/5/2/005284ae/TITLE6_AR1.1_ch15.pdf",
        "http://web.archive.org/web/20170127104730/http://iga.in.gov/static-documents/0/0/b/3/00b3e7df/TITLE32_AR28_ch3.pdf",
        "http://web.archive.org/web/20200213045523/http://iga.in.gov/static-documents/0/0/b/3/00b3e7df/TITLE32_AR28_ch3.pdf",
        "http://web.archive.org/web/20201111174818/http://iga.in.gov/static-documents/0/0/b/3/00b3e7df/TITLE32_AR28_ch3.pdf",
        "http://web.archive.org/web/20170125194211/http://iga.in.gov/static-documents/0/0/6/f/006f3b19/SB0465.05.ENRS.pdf",
        "http://web.archive.org/web/20161229103815/http://iga.in.gov/static-documents/0/0/7/3/0073b205/SB0374.03.ENGS.pdf",
    ]
    _TITLE_ARTICLE_CHAPTER_RE = re.compile(
        r"TITLE(?P<title>\d+)_AR(?P<article>[0-9.]+)_ch(?P<chapter>\d+)\.pdf$",
        re.IGNORECASE,
    )

    def get_base_url(self) -> str:
        """Return the base URL for Indiana's legislative website."""
        return "http://iga.in.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Indiana."""
        return [
            {
                "name": "Indiana Code",
                "url": "http://web.archive.org/web/20231201000000/http://iga.in.gov/legislative/laws/2023/ic/titles/",
                "type": "Code",
            }
        ]

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape Indiana code statutes.

        Indiana's live site is currently SPA-only in headless contexts.
        We prefer stable Wayback chapter PDFs that contain substantial text.
        """
        archival = await self._scrape_archived_chapter_pdfs(code_name=code_name, max_statutes=60)
        title_page_statutes = await self._scrape_archived_title_pages(code_name=code_name, max_statutes=60)

        merged: List[NormalizedStatute] = []
        merged_keys = set()

        def _merge(items: List[NormalizedStatute]) -> None:
            for statute in items:
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if not key or key in merged_keys:
                    continue
                merged_keys.add(key)
                merged.append(statute)

        _merge(archival)
        _merge(title_page_statutes)

        if merged:
            self.logger.info(f"Indiana archival fallback: Scraped {len(merged)} sections")
            return merged

        # Keep a final generic fallback for resilience.
        return await self._generic_scrape(code_name, code_url, "Ind. Code")

    async def _scrape_archived_title_pages(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        title_urls = await self._discover_archived_title_urls(limit=180)
        out: List[NormalizedStatute] = []
        seen = set()

        for title_url in title_urls:
            if len(out) >= max_statutes:
                break
            try:
                statutes = await self._generic_scrape(code_name, title_url, "Ind. Code", max_sections=80)
            except Exception:
                statutes = []
            for statute in statutes:
                if self._is_low_quality_statute_record(statute):
                    continue
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                out.append(statute)
                if len(out) >= max_statutes:
                    break

        return out

    async def _discover_archived_title_urls(self, limit: int = 160) -> List[str]:
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx"
            "?url=iga.in.gov/legislative/laws/*/ic/titles/*"
            "&output=json&filter=statuscode:200"
            f"&limit={max(1, int(limit))}"
        )

        try:
            payload = await self._fetch_page_content_with_archival_fallback(cdx_url, timeout_seconds=35)
            rows = self._parse_json_rows(payload)
        except Exception:
            return []

        out: List[str] = []
        seen = set()
        for row in rows:
            if len(row) < 3:
                continue
            ts = str(row[1] or "").strip()
            original = str(row[2] or "").strip()
            if not ts or not original:
                continue
            replay = f"https://web.archive.org/web/{ts}/{quote(original, safe=':/?=&._-')}"
            if replay in seen:
                continue
            seen.add(replay)
            out.append(replay)
            if len(out) >= limit:
                break

        return out

    async def _scrape_archived_chapter_pdfs(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        headers = {"User-Agent": "Mozilla/5.0"}
        statutes: List[NormalizedStatute] = []
        seen_ids = set()

        candidate_urls = list(self._ARCHIVE_CHAPTER_PDFS)
        for discovered_url in await self._discover_archived_pdf_urls(limit=max(max_statutes * 8, 200)):
            if discovered_url not in candidate_urls:
                candidate_urls.append(discovered_url)

        for pdf_url in candidate_urls:
            if len(statutes) >= max_statutes:
                break

            statute = await self._build_statute_from_pdf_url(code_name=code_name, pdf_url=pdf_url, headers=headers)
            if statute is None:
                continue
            if statute.statute_id in seen_ids:
                continue

            seen_ids.add(statute.statute_id)
            statutes.append(statute)

        return statutes

    async def _discover_archived_pdf_urls(self, limit: int = 240) -> List[str]:
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx"
            "?url=iga.in.gov/static-documents/*.pdf"
            "&output=json"
            "&filter=statuscode:200"
            f"&limit={max(1, int(limit))}"
        )

        try:
            payload = await self._fetch_page_content_with_archival_fallback(cdx_url, timeout_seconds=35)
            rows = self._parse_json_rows(payload)
        except Exception:
            return []

        out: List[str] = []
        for row in rows:
            if len(row) < 3:
                continue
            ts = str(row[1] or "").strip()
            original = str(row[2] or "").strip()
            if not ts or not original or not original.lower().endswith(".pdf"):
                continue
            if not self._TITLE_ARTICLE_CHAPTER_RE.search(original):
                continue
            out.append(f"https://web.archive.org/web/{ts}/{quote(original, safe=':/?=&._-')}")

        return out

    async def _build_statute_from_pdf_url(
        self,
        code_name: str,
        pdf_url: str,
        headers: Dict[str, str],
    ) -> NormalizedStatute | None:
        doc_id = self._extract_doc_id(pdf_url)
        if not doc_id:
            return None

        pdf_bytes = await self._request_bytes(pdf_url=pdf_url, headers=headers, timeout=45)
        if not pdf_bytes:
            return None

        full_text = self._extract_pdf_text(pdf_bytes, max_chars=14000)
        if len(full_text) < 280:
            # Preserve discoverable archived statute PDFs even when extraction is partial.
            full_text = (
                f"Archived Indiana Code document for {doc_id}. "
                "Source PDF was reachable but full text extraction was limited in this run."
            )

        section_name = f"Indiana Code {doc_id}"
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {doc_id}",
            code_name=code_name,
            section_number=doc_id,
            section_name=section_name,
            full_text=full_text,
            legal_area=self._identify_legal_area(full_text),
            source_url=pdf_url,
            official_cite=f"Ind. Code {doc_id}",
            metadata=StatuteMetadata(),
        )

    def _extract_doc_id(self, pdf_url: str) -> str:
        match = self._TITLE_ARTICLE_CHAPTER_RE.search(str(pdf_url or ""))
        if match:
            title = str(int(match.group("title")))
            article = match.group("article")
            chapter = str(int(match.group("chapter")))
            return f"tit. {title}, art. {article}, ch. {chapter}"

        filename = str(pdf_url or "").rsplit("/", 1)[-1]
        filename = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE)
        filename = re.sub(r"[^A-Za-z0-9._-]+", " ", filename).strip()
        return filename[:80] if filename else "archived-pdf"

    async def _request_bytes(self, pdf_url: str, headers: Dict[str, str], timeout: int) -> bytes:
        candidates = [str(pdf_url or "")]
        # Wayback often serves an HTML shell unless we request iframe/raw replay.
        wayback_iframe = self._to_wayback_iframe_url(candidates[0])
        if wayback_iframe and wayback_iframe not in candidates:
            candidates.insert(0, wayback_iframe)

        if candidates[0].startswith("https://"):
            candidates.append("http://" + candidates[0][8:])
        elif candidates[0].startswith("http://"):
            candidates.append("https://" + candidates[0][7:])

        for candidate in candidates:
            try:
                payload = await self._fetch_page_content_with_archival_fallback(
                    candidate,
                    timeout_seconds=timeout,
                )
                if payload:
                    return payload
            except Exception:
                continue

        return b""

    def _to_wayback_iframe_url(self, url: str) -> str:
        if not url or "web.archive.org/web/" not in url:
            return ""

        if "/if_/" in url:
            return url

        return re.sub(r"(web\.archive\.org/web/\d+)/(https?://)", r"\1if_/\2", url, count=1)

    def _extract_pdf_text(self, pdf_bytes: bytes, max_chars: int) -> str:
        """Extract text using pdftotext if available in the runtime."""
        try:
            proc = subprocess.run(
                ["pdftotext", "-layout", "-q", "-", "-"],
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
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]


# Register this scraper with the registry
StateScraperRegistry.register("IN", IndianaScraper)
