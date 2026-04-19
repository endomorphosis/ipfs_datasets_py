"""Scraper for Massachusetts state laws.

This module contains the scraper for Massachusetts statutes from the official state legislative website.
"""

from typing import List, Dict, Optional
import urllib.request
import re
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class MassachusettsScraper(BaseStateScraper):
    """Scraper for Massachusetts state laws from https://malegislature.gov"""

    _MA_SECTION_URL_RE = re.compile(
        r"/laws/generallaws/(?:part[a-z0-9-]*|title[a-z0-9-]*|chapter[a-z0-9-]*|section[a-z0-9-]*)(?:/|$)",
        re.IGNORECASE,
    )
    
    def get_base_url(self) -> str:
        """Return the base URL for Massachusetts's legislative website."""
        return "https://malegislature.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Massachusetts."""
        return [{
            "name": "Massachusetts General Laws",
            "url": f"{self.get_base_url()}/Laws/GeneralLaws",
            "type": "Code"
        }]

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._MA_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Massachusetts's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/Laws/GeneralLaws/PartI",
            f"{self.get_base_url()}/Laws/GeneralLaws/PartII",
            f"{self.get_base_url()}/Laws/GeneralLaws/PartIII",
            f"{self.get_base_url()}/Laws/GeneralLaws/PartIV",
        ]

        seen = set()
        merged: List[NormalizedStatute] = []
        merged_keys = set()

        def _merge(items: List[NormalizedStatute]) -> None:
            for statute in items:
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if not key or key in merged_keys:
                    continue
                merged_keys.add(key)
                merged.append(statute)

        return_threshold = self._bounded_return_threshold(40)
        if max_statutes is not None:
            return_threshold = max(1, min(return_threshold, int(max_statutes)))

        direct_sections = await self._scrape_direct_seed_sections(code_name, max_statutes=return_threshold)
        if direct_sections:
            return direct_sections[:return_threshold]

        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            statutes = await self._generic_scrape(
                code_name,
                candidate,
                "Mass. Gen. Laws",
                max_sections=max(10, return_threshold),
            )
            statutes = self._filter_section_level(statutes)
            _merge(statutes)
            if len(merged) >= return_threshold:
                return merged

        return merged

    async def _scrape_direct_seed_sections(self, code_name: str, max_statutes: int = 2) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        seeds = [
            ("1", "Citizens of commonwealth defined", f"{self.get_base_url()}/Laws/GeneralLaws/PartI/TitleI/Chapter1/Section1"),
            ("2", "Jurisdiction", f"{self.get_base_url()}/Laws/GeneralLaws/PartI/TitleI/Chapter1/Section2"),
        ]
        out: List[NormalizedStatute] = []
        for section_number, fallback_name, source_url in seeds[: max(1, int(max_statutes or 1))]:
            html = await self._request_text_direct(source_url, timeout=18)
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            heading = soup.select_one("h2.genLawHeading")
            section_name = self._normalize_legal_text(heading.get_text(" ", strip=True)) if heading else fallback_name
            body = ""
            for para in soup.find_all("p"):
                text = self._normalize_legal_text(para.get_text(" ", strip=True))
                if text.lower().startswith(f"section {section_number.lower()}."):
                    body = text
                    break
            if not body:
                main = soup.select_one("main") or soup
                body = self._normalize_legal_text(main.get_text(" ", strip=True))
            if len(body) < 60:
                continue
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} ch. 1 § {section_number}",
                    code_name=code_name,
                    chapter_number="1",
                    chapter_name="JURISDICTION OF THE COMMONWEALTH AND OF THE UNITED STATES",
                    section_number=section_number,
                    section_name=section_name[:200],
                    full_text=body,
                    legal_area=self._identify_legal_area(section_name or body),
                    source_url=source_url,
                    official_cite=f"Mass. Gen. Laws ch. 1, § {section_number}",
                    structured_data={
                        "source_kind": "official_massachusetts_general_laws_html",
                        "discovery_method": "official_seed_section",
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    async def _request_text_direct(self, url: str, timeout: int = 18) -> str:
        def _request() -> str:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except Exception:
                return ""

        try:
            import asyncio

            return await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 2)
        except Exception:
            return ""


# Register this scraper with the registry
StateScraperRegistry.register("MA", MassachusettsScraper)
