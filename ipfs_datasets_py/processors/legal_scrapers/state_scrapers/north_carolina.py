"""Scraper for North Carolina state laws.

This module contains the scraper for North Carolina statutes from the official state legislative website.
"""

from typing import List, Dict, Optional
import re
import urllib.request
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class NorthCarolinaScraper(BaseStateScraper):
    """Scraper for North Carolina state laws from https://www.ncleg.gov"""

    _NC_SECTION_URL_RE = re.compile(r"/enactedlegislation/statutes/html/bysection/chapter_[0-9A-Za-z]+/gs_[0-9A-Za-z\-\.]+\.html$", re.IGNORECASE)
    _NC_CHAPTER_URL_RE = re.compile(r"/laws/generalstatutesections/chapter[0-9A-Za-z]+$", re.IGNORECASE)

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._NC_SECTION_URL_RE.search(source) or self._NC_CHAPTER_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for North Carolina's legislative website."""
        return "https://www.ncleg.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for North Carolina."""
        return [{
            "name": "North Carolina General Statutes",
            "url": f"{self.get_base_url()}/Laws/GeneralStatutes",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from North Carolina's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            f"{self.get_base_url()}/Laws/GeneralStatuteSections/Chapter1",
            f"{self.get_base_url()}/Laws/GeneralStatutesTOC",
            code_url,
            f"{self.get_base_url()}/Laws/GeneralStatutes",
            f"{self.get_base_url()}/Laws",
            # Archive fallback candidate when live endpoints fluctuate.
            "https://web.archive.org/web/20251017000000/https://www.ncleg.gov/Laws/GeneralStatuteSections/Chapter1",
        ]

        seen = set()
        best_statutes: List[NormalizedStatute] = []
        return_threshold = self._bounded_return_threshold(30)
        if max_statutes is not None:
            return_threshold = max(1, min(return_threshold, int(max_statutes)))
        direct = await self._scrape_direct_seed_sections(code_name, max_statutes=return_threshold)
        if direct:
            return direct[:return_threshold]
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            if self.has_playwright():
                try:
                    statutes = await self._playwright_scrape(
                        code_name,
                        candidate,
                        "N.C. Gen. Stat.",
                        max_sections=max(10, return_threshold),
                        wait_for_selector="a[href*='/BySection/'][href*='GS_'], a[href*='/GeneralStatuteSections/']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if len(statutes) >= return_threshold:
                        return statutes
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "N.C. Gen. Stat.", max_sections=max(10, return_threshold))
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(statutes) >= return_threshold:
                return statutes

        return best_statutes

    async def _scrape_direct_seed_sections(self, code_name: str, max_statutes: int = 1) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        seeds = [
            ("1-1", f"{self.get_base_url()}/EnactedLegislation/Statutes/HTML/BySection/Chapter_1/GS_1-1.html"),
            ("14-17", f"{self.get_base_url()}/EnactedLegislation/Statutes/HTML/BySection/Chapter_14/GS_14-17.html"),
        ]
        out: List[NormalizedStatute] = []
        for section_number, source_url in seeds[: max(1, int(max_statutes or 1))]:
            html = await self._request_text_direct(source_url, timeout=18)
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            text = self._normalize_legal_text(soup.get_text(" ", strip=True))
            if len(text) < 80:
                continue
            name_match = re.search(rf"§\s*{re.escape(section_number)}[.;]?\s*([^§]{{4,180}}?)(?:\.|$)", text)
            section_name = name_match.group(1).strip() if name_match else f"G.S. {section_number}"
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:200],
                    full_text=text[:14000],
                    legal_area=self._identify_legal_area(section_name),
                    source_url=source_url,
                    official_cite=f"N.C. Gen. Stat. § {section_number}",
                    structured_data={
                        "source_kind": "official_north_carolina_general_statutes_html",
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
StateScraperRegistry.register("NC", NorthCarolinaScraper)
