"""Scraper for New Mexico state laws.

This module contains the scraper for New Mexico statutes from archived
NMOneSource statute PDFs.
"""

import re
import subprocess
import time
from typing import Dict, List

import requests

from .base_scraper import BaseStateScraper, NormalizedStatute
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
        archival = self._scrape_archived_document_pdfs(code_name=code_name, max_statutes=12)
        if archival:
            self.logger.info(f"New Mexico archival fallback: Scraped {len(archival)} sections")
            return archival

        return await self._generic_scrape(code_name, code_url, "N.M. Stat. Ann.")

    def _scrape_archived_document_pdfs(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        headers = {"User-Agent": "Mozilla/5.0"}
        statutes: List[NormalizedStatute] = []
        seen = set()

        for pdf_url in self._ARCHIVE_DOCUMENT_PDFS:
            if len(statutes) >= max_statutes:
                break

            section_number = self._extract_item_id(pdf_url)
            if not section_number or section_number in seen:
                continue

            pdf_bytes = self._request_bytes(pdf_url=pdf_url, headers=headers, timeout=50)
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

    def _extract_item_id(self, pdf_url: str) -> str:
        match = re.search(r"/en/(\d+)/1/document\.do", str(pdf_url or ""), flags=re.IGNORECASE)
        return match.group(1) if match else ""

    def _request_bytes(self, pdf_url: str, headers: Dict[str, str], timeout: int) -> bytes:
        candidates = [str(pdf_url or "")]
        if candidates[0].startswith("https://"):
            candidates.append("http://" + candidates[0][8:])
        elif candidates[0].startswith("http://"):
            candidates.append("https://" + candidates[0][7:])

        for candidate in candidates:
            for _ in range(3):
                try:
                    response = requests.get(candidate, headers=headers, timeout=timeout)
                    response.raise_for_status()
                    if response.content:
                        return response.content
                except Exception:
                    time.sleep(0.6)
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
