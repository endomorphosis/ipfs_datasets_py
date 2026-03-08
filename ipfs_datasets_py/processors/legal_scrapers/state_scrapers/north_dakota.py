"""Scraper for North Dakota state laws.

This module contains the scraper for North Dakota statutes from the official state legislative website.
"""

from typing import List, Dict
import json
import subprocess
import urllib.request
import urllib.parse
import re
from urllib.parse import urljoin
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class NorthDakotaScraper(BaseStateScraper):
    """Scraper for North Dakota state laws from https://www.legis.nd.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for North Dakota's legislative website."""
        return "https://www.legis.nd.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for North Dakota."""
        return [{
            "name": "North Dakota Century Code",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from North Dakota's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/",
        ]

        best: List[NormalizedStatute] = []
        seen = set()
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)
            statutes = await self._generic_scrape(code_name, candidate, "N.D. Cent. Code", max_sections=520)
            if len(statutes) > len(best):
                best = statutes

        if len(best) >= 60:
            return best

        pdf_statutes = await self._scrape_cencode_pdfs(code_name, max_statutes=260)
        if pdf_statutes:
            return pdf_statutes
        return best

    async def _scrape_cencode_pdfs(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        """Discover and emit Century Code chapter PDF links from legislative homepage."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        homepage = f"{self.get_base_url()}/"
        payload = await self._fetch_page_content_with_archival_fallback(homepage, timeout_seconds=35)
        if not payload:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        statutes: List[NormalizedStatute] = []
        seen = set()
        candidate_links = []
        for link in soup.find_all("a", href=True):
            candidate_links.append(str(link.get("href", "")).strip())

        discovered = await self._discover_archived_cencode_pdfs(limit=420)
        candidate_links.extend(discovered)

        for href in candidate_links:
            if len(statutes) >= max_statutes:
                break
            if not href:
                continue
            abs_url = urljoin(homepage, href)
            if not re.search(r"/cencode/t\d{1,3}c\d{1,3}\.pdf$", abs_url, re.IGNORECASE):
                continue
            if abs_url in seen:
                continue
            seen.add(abs_url)

            file_name = abs_url.rsplit("/", 1)[-1]
            m = re.search(r"t(\d{1,3})c(\d{1,3})\.pdf$", file_name, re.IGNORECASE)
            title_no = m.group(1) if m else ""
            chapter_no = m.group(2) if m else ""
            label = f"Title {title_no} Chapter {chapter_no}".strip()
            section_number = f"{title_no}-{chapter_no}".strip("-") or file_name
            pdf_bytes = await self._request_bytes(abs_url, timeout=45)
            full_text = self._extract_pdf_text(pdf_bytes=pdf_bytes, max_chars=14000)
            if len(full_text) < 280:
                full_text = f"North Dakota Century Code {label}: {abs_url}"

            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=label,
                    full_text=full_text,
                    source_url=abs_url,
                    legal_area=self._identify_legal_area(label),
                    official_cite=f"N.D. Cent. Code {section_number}",
                    metadata=StatuteMetadata(),
                )
            )

        return statutes

    async def _discover_archived_cencode_pdfs(self, limit: int = 320) -> List[str]:
        """Discover archived ND Century Code chapter PDFs from Wayback CDX."""
        cdx_url = (
            "http://web.archive.org/cdx/search/cdx?url=legis.nd.gov/cencode/t*c*.pdf"
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

            out: List[str] = []
            for row in rows[1:]:
                if not isinstance(row, list) or len(row) < 3:
                    continue
                ts = str(row[1]).strip()
                original = str(row[2]).strip()
                if not ts or not original:
                    continue
                encoded = urllib.parse.quote(original, safe=':/?=&%.-_')
                out.append(f"http://web.archive.org/web/{ts}/{encoded}")
            return out
        except Exception:
            return []

    async def _request_bytes(self, pdf_url: str, timeout: int) -> bytes:
        candidates = [str(pdf_url or "")]
        wayback_iframe = self._to_wayback_iframe_url(candidates[0])
        if wayback_iframe and wayback_iframe not in candidates:
            candidates.insert(0, wayback_iframe)

        if candidates[0].startswith("https://"):
            candidates.append("http://" + candidates[0][8:])
        elif candidates[0].startswith("http://"):
            candidates.append("https://" + candidates[0][7:])

        seen = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            try:
                payload = await self._fetch_page_content_with_archival_fallback(candidate, timeout_seconds=timeout)
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
        if not pdf_bytes:
            return ""
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
StateScraperRegistry.register("ND", NorthDakotaScraper)
