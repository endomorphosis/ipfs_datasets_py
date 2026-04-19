"""Scraper for Washington state laws.

This module contains the scraper for Washington statutes from the official state legislative website.
"""

from typing import List, Dict
import re
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class WashingtonScraper(BaseStateScraper):
    """Scraper for Washington state laws from https://app.leg.wa.gov"""

    _SECTION_CITE_RE = re.compile(r"^\d+[A-Za-z]?\.\d+(?:\.\d+)?[A-Za-z]?$")

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            section_number = str(statute.section_number or "")
            if "default.aspx?cite=" not in source.lower():
                continue
            if self._SECTION_CITE_RE.match(section_number):
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for Washington's legislative website."""
        return "https://app.leg.wa.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Washington."""
        return [{
            "name": "Revised Code of Washington",
            "url": f"{self.get_base_url()}/RCW/default.aspx?cite=9A.32.030",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str, max_statutes: int | None = None) -> List[NormalizedStatute]:
        """Scrape a specific code from Washington's legislative website.
        
        Washington RCW database uses JavaScript navigation, so we use Playwright.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return_threshold = self._effective_scrape_limit(max_statutes, default=20) or 1000000
        if not self._full_corpus_enabled():
            direct = await self._scrape_direct_seed_sections(code_name, max_statutes=int(return_threshold))
            if direct:
                return direct[: int(return_threshold)]

        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/RCW/default.aspx",
            f"{self.get_base_url()}/RCW/",
            f"{self.get_base_url()}/RCW/default.aspx?cite=1",
            f"{self.get_base_url()}/RCW/default.aspx?cite=9A.32.030",
            f"{self.get_base_url()}/RCW/default.aspx?cite=9A.04",
            f"{self.get_base_url()}/RCW/default.aspx?cite=4.24",
            f"{self.get_base_url()}/RCW/default.aspx?cite=7.28",
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
                        "Wash. Rev. Code",
                        max_sections=220,
                        wait_for_selector="a[href*='default.aspx?cite='], a[href*='/RCW/']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if len(statutes) >= return_threshold:
                        return statutes[:return_threshold]
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "Wash. Rev. Code", max_sections=220)
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
            ("9A.32.030", "https://app.leg.wa.gov/RCW/default.aspx?cite=9A.32.030"),
        ]
        out: List[NormalizedStatute] = []
        for section_number, url in seeds[: max(1, int(max_statutes or 1))]:
            raw = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=25)
            if not raw:
                continue
            soup = BeautifulSoup(raw, "html.parser")
            citation_node = soup.select_one("#ContentPlaceHolder1_pnlTitleBlock h1")
            caption_node = soup.select_one("#ContentPlaceHolder1_pnlTitleBlock h2")
            content_node = soup.select_one("#contentWrapper")
            citation_text = self._normalize_legal_text(citation_node.get_text(" ", strip=True) if citation_node else "")
            caption = self._normalize_legal_text(caption_node.get_text(" ", strip=True) if caption_node else "")
            body = self._normalize_legal_text(content_node.get_text(" ", strip=True) if content_node else "")
            if len(body) < 220:
                continue
            full_text = self._normalize_legal_text(f"{citation_text} {caption} {body}")
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    title_number=section_number.split(".", 1)[0],
                    section_number=section_number,
                    section_name=caption or section_number,
                    full_text=full_text,
                    legal_area=self._identify_legal_area(full_text[:1200]),
                    source_url=url,
                    official_cite=f"Wash. Rev. Code § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_washington_rcw_html",
                        "discovery_method": "official_seed_section",
                        "skip_hydrate": True,
                    },
                )
            )
        return out


# Register this scraper with the registry
StateScraperRegistry.register("WA", WashingtonScraper)
