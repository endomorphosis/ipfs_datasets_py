"""Scraper for Colorado state laws.

This module contains the scraper for Colorado statutes from the official state legislative website.
"""

import re
import subprocess
import tempfile
from typing import List, Dict
from urllib.parse import urljoin, unquote

import requests

from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class ColoradoScraper(BaseStateScraper):
    """Scraper for Colorado state laws from https://leg.colorado.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Colorado's legislative website."""
        return "https://leg.colorado.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Colorado."""
        return [{
            "name": "Colorado Revised Statutes",
            "url": "https://content.leg.colorado.gov/publication-search?search_api_fulltext=crs",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Colorado's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        statutes = self._scrape_crs_pdfs(code_name)
        if statutes:
            return statutes
        return await self._generic_scrape(code_name, f"{self.get_base_url()}/laws/colorado-revised-statutes", "Colo. Rev. Stat.")

    def _scrape_crs_pdfs(self, code_name: str) -> List[NormalizedStatute]:
        """Scrape CRS section PDFs discoverable from the official publication search."""
        search_url = "https://content.leg.colorado.gov/publication-search?search_api_fulltext=crs"
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        try:
            response = requests.get(search_url, headers=headers, timeout=45)
            response.raise_for_status()
        except Exception as exc:
            self.logger.warning(f"Colorado CRS PDF discovery failed: {exc}")
            return []

        pdf_paths = re.findall(r"/sites/default/files/[^\" ]+\.pdf", response.text, flags=re.IGNORECASE)
        seen: set[str] = set()
        statutes: List[NormalizedStatute] = []

        for path in pdf_paths:
            if path in seen:
                continue
            seen.add(path)

            # Keep section-like CRS files (e.g., 14-10-114pre20140101.pdf).
            if not re.search(r"/\d{1,2}-\d{1,3}-\d{1,4}[A-Za-z0-9\-]*\.pdf$", path):
                continue

            pdf_url = urljoin("https://content.leg.colorado.gov", path)
            section_number = self._extract_section_number_from_pdf_path(path)
            section_name = f"Section {section_number}" if section_number else "Colorado Revised Statutes section"
            full_text = self._extract_pdf_text_summary(pdf_url)

            statute = NormalizedStatute(
                state_code=self.state_code,
                state_name=self.state_name,
                statute_id=f"{code_name} § {section_number}" if section_number else f"{code_name} § PDF-{len(statutes)+1}",
                code_name=code_name,
                section_number=section_number,
                section_name=section_name,
                full_text=full_text or section_name,
                source_url=pdf_url,
                legal_area=self._identify_legal_area(code_name),
                official_cite=f"Colo. Rev. Stat. § {section_number}" if section_number else None,
            )
            statutes.append(statute)

        self.logger.info(f"Scraped {len(statutes)} Colorado CRS PDF statutes")
        return statutes

    def _extract_section_number_from_pdf_path(self, path: str) -> str:
        """Extract section number from CRS-style PDF filenames."""
        decoded_path = unquote(path)
        file_name = decoded_path.rsplit("/", 1)[-1]
        match = re.match(r"(\d{1,2}-\d{1,3}-\d{1,4})", file_name)
        if not match:
            return ""
        return match.group(1)

    def _extract_pdf_text_summary(self, pdf_url: str, max_chars: int = 8000) -> str:
        """Download a PDF and extract a normalized text summary using pdftotext."""
        try:
            response = requests.get(
                pdf_url,
                timeout=60,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            response.raise_for_status()
        except Exception as exc:
            self.logger.debug(f"Colorado PDF download failed for {pdf_url}: {exc}")
            return ""

        try:
            with tempfile.TemporaryDirectory(prefix="co_crs_pdf_") as tmpdir:
                from pathlib import Path

                pdf_path = Path(tmpdir) / "section.pdf"
                txt_path = Path(tmpdir) / "section.txt"
                pdf_path.write_bytes(response.content)

                result = subprocess.run(
                    ["pdftotext", "-f", "1", "-l", "3", str(pdf_path), str(txt_path)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                if int(result.returncode) != 0 or not txt_path.exists():
                    return ""

                text = txt_path.read_text(encoding="utf-8", errors="ignore")
                text = re.sub(r"\s+", " ", text).strip()
                return text[:max_chars]
        except Exception as exc:
            self.logger.debug(f"Colorado PDF text extraction failed for {pdf_url}: {exc}")
            return ""


# Register this scraper with the registry
StateScraperRegistry.register("CO", ColoradoScraper)
