"""Scraper for Pennsylvania state laws.

This module contains the scraper for Pennsylvania statutes from the official state legislative website.
"""

import re
from typing import List, Dict, Optional
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class PennsylvaniaScraper(BaseStateScraper):
    """Scraper for Pennsylvania state laws from https://www.legis.state.pa.us"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Pennsylvania's legislative website."""
        return "https://www.legis.state.pa.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Pennsylvania."""
        return [{
            "name": "Pennsylvania Consolidated Statutes",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Pennsylvania's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/cfdocs/legis/LI/Public/li_index.cfm",
            f"{self.get_base_url()}/WU01/LI/LI/CT/HTM/",
            "https://law.justia.com/codes/pennsylvania/",
            "https://web.archive.org/web/20250201000000/https://law.justia.com/codes/pennsylvania/",
            "https://web.archive.org/web/20250201000000/https://www.legis.state.pa.us/cfdocs/legis/LI/Public/li_index.cfm",
        ]

        seen = set()
        merged: List[NormalizedStatute] = []
        merged_keys = set()
        limit = self._effective_scrape_limit(max_statutes, default=80)
        return_threshold = limit if limit is not None else 1000000
        direct_statutes = await self._scrape_direct_titles(
            code_name,
            max_statutes=min(return_threshold, 80),
        )
        if direct_statutes:
            if limit is not None:
                return direct_statutes[:limit]
            return direct_statutes

        def _merge(items: List[NormalizedStatute]) -> None:
            for statute in items:
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if not key or key in merged_keys:
                    continue
                merged_keys.add(key)
                merged.append(statute)

        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            statutes = await self._generic_scrape(
                code_name,
                candidate,
                "Pa. Cons. Stat.",
                max_sections=return_threshold if limit is not None else 900,
            )
            _merge(statutes)
            if len(merged) >= return_threshold:
                return merged[:return_threshold]

        return merged

    async def _scrape_direct_titles(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        urls = [
            "https://www.legis.state.pa.us/WU01/LI/LI/CT/HTM/01/00.001..HTM",
            "https://www.legis.state.pa.us/WU01/LI/LI/CT/HTM/18/18.001..HTM",
        ]
        out: List[NormalizedStatute] = []
        for source_url in urls[: max(1, int(max_statutes or 1))]:
            payload = await self._fetch_page_content_with_archival_fallback(source_url, timeout_seconds=12)
            if not payload:
                continue
            soup = BeautifulSoup(payload, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            text = self._normalize_legal_text(soup.get_text(" ", strip=True))
            if len(text) < 280:
                continue
            title_node = soup.find("title")
            section_name = (
                title_node.get_text(" ", strip=True) if title_node else text.split(" Sec.", 1)[0]
            )
            title_match = re.search(r"Title\s+(\d+)", text, re.IGNORECASE)
            title_number = title_match.group(1) if title_match else str(len(out) + 1)
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § Title {title_number}",
                    code_name=code_name,
                    section_number=f"Title {title_number}",
                    section_name=section_name[:200],
                    full_text=text[:14000],
                    source_url=source_url,
                    legal_area=self._identify_legal_area(section_name),
                    official_cite=f"Pa. Cons. Stat. tit. {title_number}",
                    metadata=StatuteMetadata(),
                    structured_data={"source_kind": "official_direct_title", "skip_hydrate": True},
                )
            )
        return out


# Register this scraper with the registry
StateScraperRegistry.register("PA", PennsylvaniaScraper)
