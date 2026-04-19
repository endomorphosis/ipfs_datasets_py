"""Scraper for Wisconsin state laws.

This module contains the scraper for Wisconsin statutes from the official state legislative website.
"""

from typing import List, Dict, Optional
import re
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class WisconsinScraper(BaseStateScraper):
    """Scraper for Wisconsin state laws from https://docs.legis.wisconsin.gov"""

    _WI_SECTION_URL_RE = re.compile(r"/document/statutes/[0-9]+(?:\.[0-9A-Za-z]+)+$", re.IGNORECASE)

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._WI_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for Wisconsin's legislative website."""
        return "https://docs.legis.wisconsin.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Wisconsin."""
        return [{
            "name": "Wisconsin Statutes",
            "url": f"{self.get_base_url()}/statutes/statutes",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Wisconsin's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/statutes/statutes",
            f"{self.get_base_url()}/document/statutes/940",
            f"{self.get_base_url()}/document/statutes/939.50",
        ]

        limit = self._effective_scrape_limit(max_statutes, default=40)
        direct = await self._scrape_direct_sections(code_name, max_statutes=limit)
        if direct:
            return direct

        seen = set()
        best_statutes: List[NormalizedStatute] = []
        return_threshold = limit if limit is not None else 1000000
        scan_limit = return_threshold if limit is not None else 1000
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            if self.has_playwright():
                try:
                    statutes = await self._playwright_scrape(
                        code_name,
                        candidate,
                        "Wis. Stat.",
                        max_sections=scan_limit,
                        wait_for_selector="a[href*='/document/statutes/'], a[href*='/statutes/statutes']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if len(statutes) >= return_threshold:
                        return statutes
                except Exception:
                    pass

            statutes = await self._generic_scrape(
                code_name,
                candidate,
                "Wis. Stat.",
                max_sections=scan_limit,
            )
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(statutes) >= return_threshold:
                return statutes[:return_threshold]

        return best_statutes

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
            ("939.50", f"{self.get_base_url()}/document/statutes/939.50"),
            ("940.01", f"{self.get_base_url()}/document/statutes/940.01"),
        ]
        limit = max_statutes if max_statutes is not None else len(section_urls)
        statutes: List[NormalizedStatute] = []
        for section_number, source_url in section_urls[: max(1, int(limit))]:
            payload = await self._fetch_page_content_with_archival_fallback(source_url, timeout_seconds=15)
            if not payload:
                continue
            soup = BeautifulSoup(payload, "html.parser")
            section_nodes = soup.select(f'[data-section="{section_number}"]')
            if not section_nodes:
                section_nodes = soup.select(".box-content, #contentFrame")

            text_parts: List[str] = []
            section_name = ""
            for node in section_nodes:
                if not section_name:
                    title_node = node.select_one(".qstitle_sect") or node.find("title")
                    if title_node:
                        section_name = title_node.get_text(" ", strip=True)
                text_value = self._normalize_legal_text(node.get_text(" ", strip=True))
                if text_value:
                    text_parts.append(text_value)

            text = self._normalize_legal_text(" ".join(text_parts))
            if not section_name:
                title = soup.find("title")
                section_name = title.get_text(" ", strip=True) if title else f"Section {section_number}"
            if len(text) < 240:
                continue
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:200],
                    full_text=text,
                    legal_area=self._identify_legal_area(section_name or text),
                    source_url=source_url,
                    official_cite=f"Wis. Stat. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={"source_kind": "official_wisconsin_statutes_html", "skip_hydrate": True},
                )
            )
        return statutes


# Register this scraper with the registry
StateScraperRegistry.register("WI", WisconsinScraper)
