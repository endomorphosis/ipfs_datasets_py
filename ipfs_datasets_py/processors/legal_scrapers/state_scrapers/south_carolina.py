"""Scraper for South Carolina state laws.

This module contains the scraper for South Carolina statutes from the official state legislative website.
"""

import re
from typing import List, Dict, Optional
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class SouthCarolinaScraper(BaseStateScraper):
    """Scraper for South Carolina state laws from https://www.scstatehouse.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for South Carolina's legislative website."""
        return "https://www.scstatehouse.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for South Carolina."""
        return [{
            "name": "South Carolina Code of Laws",
            # Use the statute master page directly; home page navigation is noisy
            # and often yields zero probable statute links.
            "url": f"{self.get_base_url()}/code/statmast.php",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from South Carolina's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return_threshold = self._bounded_return_threshold(30)
        if max_statutes is not None:
            return_threshold = max(1, min(return_threshold, int(max_statutes)))
        if not self._full_corpus_enabled():
            direct = await self._scrape_direct_seed_sections(code_name, max_statutes=return_threshold)
            if direct:
                return direct[:return_threshold]
        return await self._generic_scrape(code_name, code_url, "S.C. Code Ann.", max_sections=max(10, return_threshold))

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
            ("16-3-10", "https://www.scstatehouse.gov/code/t16c003.php"),
        ]
        out: List[NormalizedStatute] = []
        for section_number, url in seeds[: max(1, int(max_statutes or 1))]:
            raw = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=25)
            if not raw:
                continue
            soup = BeautifulSoup(raw, "html.parser")
            text = self._normalize_legal_text(soup.get_text(" ", strip=True))
            match = re.search(
                rf"\bSECTION\s+{re.escape(section_number)}\.\s*(.+?)(?=\bSECTION\s+\d+-\d+-\d+\.)",
                text,
                flags=re.IGNORECASE,
            )
            if not match:
                continue
            body = self._normalize_legal_text(f"SECTION {section_number}. {match.group(1)}")
            if len(body) < 120:
                continue
            name_match = re.match(rf"SECTION\s+{re.escape(section_number)}\.\s*([^\.]+)\.", body, flags=re.IGNORECASE)
            section_name = name_match.group(1).strip() if name_match else section_number
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
                    source_url=f"{url}#{section_number}",
                    official_cite=f"S.C. Code Ann. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_south_carolina_code_html",
                        "discovery_method": "official_seed_chapter_section",
                        "skip_hydrate": True,
                    },
                )
            )
        return out


# Register this scraper with the registry
StateScraperRegistry.register("SC", SouthCarolinaScraper)
