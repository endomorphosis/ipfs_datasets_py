"""Scraper for West Virginia state laws.

This module contains the scraper for West Virginia statutes from the official state legislative website.
"""

from typing import List, Dict
import re
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class WestVirginiaScraper(BaseStateScraper):
    """Scraper for West Virginia state laws from http://www.wvlegislature.gov"""

    _WV_SECTION_URL_RE = re.compile(r"/\d+[A-Za-z]?(?:-\d+[A-Za-z]?){1,2}/?$")

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._WV_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for West Virginia's legislative website."""
        return "https://code.wvlegislature.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for West Virginia."""
        return [{
            "name": "West Virginia Code",
            "url": f"{self.get_base_url()}/11-8-12/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str, max_statutes: int | None = None) -> List[NormalizedStatute]:
        """Scrape a specific code from West Virginia's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return_threshold = self._effective_scrape_limit(max_statutes, default=15) or 1000000
        if not self._full_corpus_enabled():
            direct = await self._scrape_direct_seed_sections(code_name, max_statutes=int(return_threshold))
            if direct:
                return direct[: int(return_threshold)]

        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/1/",
            f"{self.get_base_url()}/11/",
            f"{self.get_base_url()}/11-8-12/",
            f"{self.get_base_url()}/1-1/",
            f"{self.get_base_url()}/",
        ]

        seen = set()
        best_statutes: List[NormalizedStatute] = []
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            if self.has_playwright():
                try:
                    statutes = await self._playwright_scrape(
                        code_name,
                        candidate,
                        "W. Va. Code",
                        max_sections=220,
                        wait_for_selector="a[href*='wvlegislature.gov/'][href*='-'], a[href*='/code/'], a[href*='/article/']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if len(statutes) >= return_threshold:
                        return statutes[:return_threshold]
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "W. Va. Code", max_sections=220)
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(statutes) >= return_threshold:
                return statutes[:return_threshold]

        return best_statutes[:return_threshold]

    async def _scrape_direct_seed_sections(
        self,
        code_name: str,
        max_statutes: int = 1,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        seeds = [
            ("61-2-1", "https://code.wvlegislature.gov/61-2-1/"),
        ]
        out: List[NormalizedStatute] = []
        for section_number, url in seeds[: max(1, int(max_statutes or 1))]:
            raw = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=25)
            if not raw:
                continue
            soup = BeautifulSoup(raw, "html.parser")
            node = soup.select_one("div.sectiontext")
            if node is None:
                continue
            heading = self._normalize_legal_text((node.find("h4") or node).get_text(" ", strip=True))
            body_parts = [
                self._normalize_legal_text(p.get_text(" ", strip=True))
                for p in node.find_all("p")
            ]
            body = self._normalize_legal_text(" ".join([heading, *body_parts]))
            if len(body) < 180:
                continue
            section_name = re.sub(r"^§\s*[\w\-]+\.?\s*", "", heading).strip() or heading
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    title_number=section_number.split("-", 1)[0],
                    section_number=section_number,
                    section_name=section_name[:220],
                    full_text=body,
                    legal_area=self._identify_legal_area(body[:1200]),
                    source_url=url,
                    official_cite=f"W. Va. Code § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_west_virginia_code_html",
                        "discovery_method": "official_seed_section",
                        "skip_hydrate": True,
                    },
                )
            )
        return out


# Register this scraper with the registry
StateScraperRegistry.register("WV", WestVirginiaScraper)
