"""Scraper for New Mexico state laws.

This module contains the scraper for New Mexico statutes from archived
NMOneSource statute PDFs.
"""

import asyncio
import json
import re
import subprocess
import urllib.parse
import urllib.request
from typing import Dict, List

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class NewMexicoScraper(BaseStateScraper):
    """Scraper for New Mexico state laws from https://www.nmlegis.gov"""

    _ARCHIVE_DOCUMENT_PDFS = [
        "http://web.archive.org/web/20250101000000/https://nmonesource.com/nmos/nmsa/en/18973/1/document.do",
        "http://web.archive.org/web/20250101000000/https://nmonesource.com/nmos/nmsa/en/25293/1/document.do",
        "http://web.archive.org/web/20250101000000/https://nmonesource.com/nmos/nmsa/en/4340/1/document.do",
        "http://web.archive.org/web/20250101000000/https://nmonesource.com/nmos/nmsa/en/12084/1/document.do",
        "http://web.archive.org/web/20250101000000/https://nmonesource.com/nmos/nmsa/en/5326/1/document.do",
    ]
    
    def get_base_url(self) -> str:
        """Return the base URL for New Mexico's legislative website."""
        return "https://www.nmlegis.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for New Mexico."""
        return [{
            "name": "New Mexico Statutes",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from New Mexico's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        archival = await self._scrape_archived_document_pdfs(code_name=code_name, max_statutes=24)
        if archival:
            self.logger.info(f"New Mexico archival fallback: Scraped {len(archival)} sections")
            return archival

        index_fallback = await self._scrape_nmonesource_index(code_name=code_name)
        if index_fallback:
            self.logger.info("New Mexico index fallback: Scraped %s section(s)", len(index_fallback))
            return index_fallback

        return await self._generic_scrape(code_name, code_url, "N.M. Stat. Ann.")

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

        archive_candidates = await self._discover_archived_document_urls(limit=24)
        candidate_urls = list(self._ARCHIVE_DOCUMENT_PDFS)
        for url in archive_candidates:
            if url not in candidate_urls:
                candidate_urls.append(url)

        for pdf_url in candidate_urls[:32]:
            if len(statutes) >= max_statutes:
                break

            section_number = self._extract_item_id(pdf_url)
            if not section_number or section_number in seen:
                continue

            pdf_bytes = await self._request_bytes(pdf_url=pdf_url, headers=headers, timeout=50)
            if not pdf_bytes:
                continue

            full_text = self._extract_pdf_text(pdf_bytes=pdf_bytes, max_chars=14000)
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
            req = urllib.request.Request(cdx_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=45) as resp:
                payload = resp.read().decode("utf-8", errors="ignore")
            rows = json.loads(payload)
            if not isinstance(rows, list) or len(rows) < 2:
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
            for _ in range(2):
                try:
                    payload = await self._fetch_page_content_with_archival_fallback(
                        candidate,
                        timeout_seconds=max(8, min(int(timeout), 20)),
                    )
                    if payload:
                        return payload
                except Exception:
                    await asyncio.sleep(0.25)
                    continue

        return b""

    def _extract_pdf_text(self, pdf_bytes: bytes, max_chars: int) -> str:
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
StateScraperRegistry.register("NM", NewMexicoScraper)
