"""Scraper for Nebraska state laws.

This module contains the scraper for Nebraska statutes from the official state legislative website.
"""

import re
import urllib.request
from typing import List, Dict, Optional
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class NebraskaScraper(BaseStateScraper):
    """Scraper for Nebraska state laws from https://nebraskalegislature.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Nebraska's legislative website."""
        return "https://nebraskalegislature.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Nebraska."""
        return [{
            "name": "Nebraska Revised Statutes",
            "url": f"{self.get_base_url()}/laws/browse-statutes.php",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Nebraska's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = max(1, int(max_statutes)) if max_statutes is not None else self._bounded_return_threshold(40)
        if not self._full_corpus_enabled() or max_statutes is not None:
            direct = await self._scrape_direct_seed_sections(code_name, max_statutes=limit)
            if direct:
                return direct[:limit]
        return await self._generic_scrape(code_name, code_url, "Neb. Rev. Stat.", max_sections=max(10, limit))

    async def _scrape_direct_seed_sections(self, code_name: str, max_statutes: int = 2) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        seeds = [
            ("1-101", f"{self.get_base_url()}/laws/statutes.php?statute=1-101"),
            ("28-303", f"{self.get_base_url()}/laws/statutes.php?statute=28-303"),
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
            match = re.search(rf"\b{re.escape(section_number)}\b[.:\s-]+([^.;]{{4,160}})", text)
            section_name = match.group(1).strip() if match else f"Section {section_number}"
            if len(text) < 160:
                continue
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
                    official_cite=f"Neb. Rev. Stat. § {section_number}",
                    structured_data={
                        "source_kind": "official_nebraska_statutes_html",
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
StateScraperRegistry.register("NE", NebraskaScraper)
