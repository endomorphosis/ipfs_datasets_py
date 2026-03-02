"""Scraper for Indiana state laws.

This module contains the scraper for Indiana statutes from archived official
Indiana General Assembly static-document chapter PDFs.
"""

import re
import subprocess
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
        archival = await self._scrape_archived_chapter_pdfs(code_name=code_name, max_statutes=20)
        if archival:
            self.logger.info(f"Indiana archival fallback: Scraped {len(archival)} sections")
            return archival

        # Keep a final generic fallback for resilience.
        return await self._generic_scrape(code_name, code_url, "Ind. Code")

    async def _scrape_archived_chapter_pdfs(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        headers = {"User-Agent": "Mozilla/5.0"}
        statutes: List[NormalizedStatute] = []
        seen_ids = set()

        for pdf_url in self._ARCHIVE_CHAPTER_PDFS:
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
            return None

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
