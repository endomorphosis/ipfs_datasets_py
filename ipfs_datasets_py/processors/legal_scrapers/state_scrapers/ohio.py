"""Scraper for Ohio state laws.

This module contains the scraper for Ohio statutes from the official state legislative website.
"""

import re
from typing import List, Dict, Optional
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class OhioScraper(BaseStateScraper):
    """Scraper for Ohio state laws from https://codes.ohio.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Ohio's legislative website."""
        return "https://codes.ohio.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Ohio."""
        return [{
            "name": "Ohio Revised Code",
            "url": f"{self.get_base_url()}/ohio-revised-code",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Ohio's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=2)
        if not self._full_corpus_enabled() or max_statutes is not None:
            direct = await self._scrape_direct_sections(code_name, max_statutes=limit)
            if direct:
                return direct
        max_sections = limit if limit is not None else 1000000
        return await self._generic_scrape(
            code_name,
            code_url,
            "Ohio Rev. Code Ann.",
            max_sections=max_sections,
        )

    async def _scrape_direct_sections(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        section_urls = [
            f"{self.get_base_url()}/ohio-revised-code/section-1.01",
            f"{self.get_base_url()}/ohio-revised-code/section-2903.01",
        ]
        statutes: List[NormalizedStatute] = []
        limit = max_statutes if max_statutes is not None else len(section_urls)
        for source_url in section_urls[: max(1, int(limit))]:
            payload = await self._fetch_page_content_with_archival_fallback(source_url, timeout_seconds=12)
            if not payload:
                continue
            soup = BeautifulSoup(payload, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            title = soup.find(["h1", "h2"])
            section_name = title.get_text(" ", strip=True) if title else ""
            text = self._normalize_legal_text(soup.get_text(" ", strip=True))
            match = re.search(r"\bSection\s+(\d+[A-Za-z]?(?:\.\d+[A-Za-z]*)*)\b", text, re.IGNORECASE)
            section_number = match.group(1) if match else source_url.rsplit("section-", 1)[-1]
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
                    official_cite=f"Ohio Rev. Code Ann. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={"source_kind": "official_direct_section", "skip_hydrate": True},
                )
            )
        return statutes


# Register this scraper with the registry
StateScraperRegistry.register("OH", OhioScraper)
