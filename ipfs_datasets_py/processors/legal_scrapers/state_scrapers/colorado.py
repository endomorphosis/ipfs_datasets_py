"""Scraper for Colorado state laws.

This module contains the scraper for Colorado statutes from the official state legislative website.
"""

import re
import subprocess
import tempfile
from typing import List, Dict, Optional
from urllib.parse import urljoin, unquote

from ipfs_datasets_py.utils import anyio_compat as asyncio
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
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Colorado's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        statutes = await self._scrape_crs_pdfs(code_name, max_statutes=max_statutes)
        if statutes:
            return statutes
        self.logger.warning("Colorado CRS direct PDF scrape returned no usable statutes; skipping generic recovery fallback")
        return []

    async def _scrape_crs_pdfs(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape CRS section PDFs discoverable from the official publication search."""
        search_url = "https://content.leg.colorado.gov/publication-search?search_api_fulltext=crs"

        try:
            self.logger.info("Colorado CRS: fetching publication search page directly")
            page_bytes = await self._request_bytes_direct(
                search_url,
                timeout_seconds=45,
            )
            if not page_bytes:
                raise RuntimeError("empty response")
        except Exception as exc:
            self.logger.warning(f"Colorado CRS PDF discovery failed: {exc}")
            return []

        page_text = page_bytes.decode("utf-8", errors="replace")
        pdf_paths = re.findall(r"/sites/default/files/[^\" ]+\.pdf", page_text, flags=re.IGNORECASE)
        seen: set[str] = set()
        statutes: List[NormalizedStatute] = []
        limit = self._effective_scrape_limit(max_statutes, default=20)

        for path in pdf_paths:
            if limit is not None and len(statutes) >= int(limit):
                break
            if path in seen:
                continue
            seen.add(path)

            pdf_url = urljoin("https://content.leg.colorado.gov", path)
            section_number = self._extract_section_number_from_pdf_path(path)
            if not section_number:
                continue
            section_name = f"Section {section_number}" if section_number else "Colorado Revised Statutes section"
            full_text = await self._extract_pdf_text_summary(pdf_url)
            if len(full_text or "") < 300:
                continue

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
            statute.structured_data = {
                "source_kind": "official_colorado_pdf",
                "skip_hydrate": True,
            }
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

    def _fallback_section_id_from_pdf_path(self, path: str) -> str:
        decoded_path = unquote(path)
        file_name = decoded_path.rsplit("/", 1)[-1]
        file_name = re.sub(r"\.pdf$", "", file_name, flags=re.IGNORECASE)
        file_name = re.sub(r"[^A-Za-z0-9._-]+", "-", file_name).strip("-")
        return file_name[:80]

    async def _extract_pdf_text_summary(self, pdf_url: str, max_chars: int = 8000) -> str:
        """Download a PDF and extract a normalized text summary using pdftotext."""
        try:
            self.logger.info("Colorado CRS: fetching PDF %s", pdf_url)
            payload = await self._request_bytes_direct(
                pdf_url,
                timeout_seconds=60,
            )
            if not payload:
                return ""
        except Exception as exc:
            self.logger.debug(f"Colorado PDF download failed for {pdf_url}: {exc}")
            return ""

        try:
            with tempfile.TemporaryDirectory(prefix="co_crs_pdf_") as tmpdir:
                from pathlib import Path

                pdf_path = Path(tmpdir) / "section.pdf"
                txt_path = Path(tmpdir) / "section.txt"
                pdf_path.write_bytes(payload)

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

    async def _request_bytes_direct(self, url: str, timeout_seconds: int = 45) -> bytes:
        cached = await self._load_page_bytes_from_any_cache(url)
        if cached:
            return cached

        timeout = max(5, int(timeout_seconds or 45))

        def _request() -> bytes:
            try:
                import requests

                response = requests.get(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-colorado-code-scraper/2.0",
                        "Accept": "text/html,application/pdf;q=0.9,*/*;q=0.8",
                    },
                    timeout=(min(10, timeout), timeout),
                )
                if int(response.status_code or 0) != 200:
                    return b""
                return bytes(response.content or b"")
            except Exception:
                return b""

        try:
            payload = await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 2)
        except TimeoutError:
            self._record_fetch_event(provider="requests_direct", success=False, error="colorado_direct_timeout")
            return b""

        self._record_fetch_event(provider="requests_direct", success=bool(payload))
        if payload:
            await self._cache_successful_page_fetch(url=url, payload=payload, provider="requests_direct")
        return payload


# Register this scraper with the registry
StateScraperRegistry.register("CO", ColoradoScraper)
