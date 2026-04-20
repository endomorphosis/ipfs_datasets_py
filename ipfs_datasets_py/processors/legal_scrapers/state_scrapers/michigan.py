"""Scraper for Michigan state laws.

This module contains the scraper for Michigan statutes from the official state legislative website.
"""

import re
from typing import List, Dict, Optional
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class MichiganScraper(BaseStateScraper):
    """Scraper for Michigan state laws from http://www.legislature.mi.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Michigan's legislative website."""
        return "http://www.legislature.mi.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Michigan."""
        return [{
            "name": "Michigan Compiled Laws",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Michigan's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = max(1, int(max_statutes)) if max_statutes is not None else self._bounded_return_threshold(2)
        if not self._full_corpus_enabled() or max_statutes is not None:
            direct = await self._scrape_direct_sections(code_name, max_statutes=limit)
            if direct:
                return direct
        return await self._generic_scrape(code_name, code_url, "Mich. Comp. Laws", max_sections=max(10, limit))

    async def _scrape_direct_sections(self, code_name: str, max_statutes: int | None = None) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        section_urls = [
            f"{self.get_base_url()}/Laws/MCL?objectName=mcl-750-316",
            f"{self.get_base_url()}/Laws/MCL?objectName=mcl-600-101",
        ]
        statutes: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else self._bounded_return_threshold(2)
        for source_url in section_urls[:limit]:
            payload = await self._fetch_page_content_with_archival_fallback(source_url, timeout_seconds=12)
            if not payload:
                continue
            soup = BeautifulSoup(payload, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            title = soup.find(["h1", "h2"])
            section_name = title.get_text(" ", strip=True) if title else ""
            text = self._normalize_legal_text(soup.get_text(" ", strip=True))
            match = re.search(r"\b(\d+[A-Za-z]?(?:\.\d+[A-Za-z]*)+)\b", text)
            section_number = match.group(1) if match else source_url.rsplit("mcl-", 1)[-1]
            if len(text) < 160:
                continue
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:200] or f"Section {section_number}",
                    full_text=text,
                    legal_area=self._identify_legal_area(section_name or text),
                    source_url=source_url,
                    official_cite=f"Mich. Comp. Laws § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={"source_kind": "official_direct_section", "skip_hydrate": True},
                )
            )
        return statutes


# Register this scraper with the registry
StateScraperRegistry.register("MI", MichiganScraper)
