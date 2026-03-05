"""Scraper for Iowa state laws.

This module contains the scraper for Iowa statutes from the official state legislative website.
"""

import json
import re
import urllib.parse
import urllib.request
from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class IowaScraper(BaseStateScraper):
    """Scraper for Iowa state laws from https://www.legis.iowa.gov"""
    
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
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Iowa's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        live_stubs = await self._scrape_live_code_stubs(code_name, max_statutes=220)

        archival_stubs = await self._scrape_archived_code_stubs(code_name, max_statutes=140)

        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/docs/code//",
            f"{self.get_base_url()}/docs/code/",
            "https://law.justia.com/codes/iowa/",
            "http://web.archive.org/web/20250101000000/https://law.justia.com/codes/iowa/",
        ]

        seen = set()
        best_statutes: List[NormalizedStatute] = []
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            statutes = await self._generic_scrape(code_name, candidate, "Iowa Code", max_sections=280)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(statutes) >= 30:
                return statutes

        if len(live_stubs) > len(best_statutes):
            best_statutes = live_stubs
        if len(archival_stubs) > len(best_statutes):
            best_statutes = archival_stubs

        return best_statutes

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
        try:
            req = urllib.request.Request(cdx_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=45) as resp:
                rows = json.loads(resp.read().decode("utf-8", errors="ignore"))
        except Exception:
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
                )
            )

        return out


# Register this scraper with the registry
StateScraperRegistry.register("IA", IowaScraper)
