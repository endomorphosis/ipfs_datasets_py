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

    _CO_SECTION_NUMBER_RE = re.compile(r"\b(\d{1,2}-\d{1,3}-\d{1,4})\b")
    
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
        """Scrape CRS-related publications discoverable from the official publication search."""
        limit = self._effective_scrape_limit(max_statutes, default=20)
        discovered = await self._discover_crs_publications(limit=max(8, int(limit or 20) * 3))
        if not discovered:
            return []

        statutes: List[NormalizedStatute] = []
        seen_sections: set[str] = set()

        for publication in discovered:
            if limit is not None and len(statutes) >= int(limit):
                break
            title = str(publication.get("title") or "").strip()
            detail_url = str(publication.get("detail_url") or "").strip()
            pdf_url = str(publication.get("pdf_url") or "").strip()
            section_number = self._extract_section_number(title) or self._extract_section_number_from_pdf_path(pdf_url)
            if not section_number:
                continue
            if section_number in seen_sections:
                continue
            seen_sections.add(section_number)

            section_name = title or f"Section {section_number}"
            full_text = ""
            source_kind = "official_colorado_pdf"

            if detail_url:
                detail_text = await self._extract_publication_detail_text(detail_url)
                if len(detail_text or "") >= 220:
                    full_text = detail_text
                    source_kind = "official_colorado_publication_html"

            if len(full_text or "") < 220 and pdf_url:
                pdf_text = await self._extract_pdf_text_summary(pdf_url)
                if len(pdf_text or "") >= len(full_text or ""):
                    full_text = pdf_text
                    source_kind = "official_colorado_pdf"

            if len(full_text or "") < 220:
                continue

            statute = NormalizedStatute(
                state_code=self.state_code,
                state_name=self.state_name,
                statute_id=f"{code_name} § {section_number}",
                code_name=code_name,
                section_number=section_number,
                section_name=section_name,
                full_text=full_text,
                source_url=detail_url or pdf_url,
                legal_area=self._identify_legal_area(code_name),
                official_cite=f"Colo. Rev. Stat. § {section_number}",
            )
            statute.structured_data = {
                "source_kind": source_kind,
                "detail_url": detail_url or None,
                "pdf_url": pdf_url or None,
                "skip_hydrate": True,
            }
            statutes.append(statute)

        self.logger.info(f"Scraped {len(statutes)} Colorado CRS PDF statutes")
        return statutes

    async def _discover_crs_publications(self, limit: int = 60) -> List[Dict[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        out: List[Dict[str, str]] = []
        seen: set[str] = set()

        for page in range(0, 8):
            search_url = f"https://content.leg.colorado.gov/publication-search?search_api_fulltext=crs&page={page}"
            try:
                page_bytes = await self._request_bytes_direct(search_url, timeout_seconds=45)
            except Exception:
                continue
            if not page_bytes:
                continue

            soup = BeautifulSoup(page_bytes, "html.parser")
            rows = soup.select(".views-row")
            if not rows:
                break

            for row in rows:
                row_text = " ".join(row.get_text(" ", strip=True).split())
                if "C.R.S." not in row_text and "Colorado Revised Statutes" not in row_text:
                    continue
                detail_url = ""
                pdf_url = ""
                title = ""
                for link in row.select("a[href]"):
                    href = str(link.get("href") or "").strip()
                    text = " ".join(link.get_text(" ", strip=True).split())
                    if not href:
                        continue
                    absolute = urljoin(search_url, href)
                    if "/publications/" in href and not title:
                        detail_url = absolute
                        title = text or row_text[:240]
                    if href.lower().endswith(".pdf"):
                        pdf_url = absolute
                if not detail_url and not pdf_url:
                    continue
                section_number = self._extract_section_number(title or row_text) or self._extract_section_number_from_pdf_path(pdf_url)
                if not section_number:
                    continue
                key = detail_url or pdf_url
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    {
                        "title": title or row_text[:240],
                        "detail_url": detail_url,
                        "pdf_url": pdf_url,
                        "section_number": section_number,
                    }
                )
                if len(out) >= limit:
                    return out
        return out

    async def _extract_publication_detail_text(self, detail_url: str, max_chars: int = 16000) -> str:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return ""

        payload = await self._request_bytes_direct(detail_url, timeout_seconds=45)
        if not payload:
            return ""
        html_text = payload.decode("utf-8", errors="replace")
        soup = BeautifulSoup(html_text, "html.parser")
        article = soup.select_one("article")
        if article is None:
            return ""
        text = " ".join(article.get_text(" ", strip=True).split())
        text = re.sub(r"\bShare:\b.*$", "", text, flags=re.IGNORECASE).strip()
        return text[:max_chars]

    def _extract_section_number(self, text: str) -> str:
        match = self._CO_SECTION_NUMBER_RE.search(str(text or ""))
        return match.group(1) if match else ""

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
