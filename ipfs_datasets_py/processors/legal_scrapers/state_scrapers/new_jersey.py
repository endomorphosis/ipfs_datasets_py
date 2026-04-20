"""Scraper for New Jersey state laws.

This module contains the scraper for New Jersey statutes from the official state
legislative website.
"""

import re
import subprocess
import urllib.request
from typing import List, Dict, Optional
from urllib.parse import urljoin
from .base_scraper import BaseStateScraper, NormalizedStatute
from .base_scraper import StatuteMetadata
from .registry import StateScraperRegistry


class NewJerseyScraper(BaseStateScraper):
    """Scraper for New Jersey state laws from https://www.njleg.state.nj.us"""

    _LIS_GATEWAY = "https://lis.njleg.state.nj.us/nxt/gateway.dll"
    _XHITLIST_SELECT = (
        "title;path;relevance-weight;content-type;home-title;"
        "item-bookmark;title-path"
    )
    
    def get_base_url(self) -> str:
        """Return the base URL for New Jersey's legislative website."""
        return "https://www.njleg.state.nj.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for New Jersey."""
        return [{
            "name": "New Jersey Statutes",
            "url": "https://lis.njleg.state.nj.us/nxt/gateway.dll/statutes/1?f=templates&fn=default.htm&vid=Publish:10.1048/Enu",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from New Jersey's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return_threshold = self._bounded_return_threshold(20)
        if max_statutes is not None:
            return_threshold = max(1, min(return_threshold, int(max_statutes)))
        if not self._full_corpus_enabled() or max_statutes is not None:
            direct = await self._scrape_direct_public_law_pdfs(code_name, max_statutes=return_threshold)
            if direct:
                return direct[:return_threshold]
        statutes = await self._scrape_via_xhitlist(code_name, max_sections=max(10, return_threshold))
        if len(statutes) >= return_threshold:
            return statutes

        self.logger.warning(
            "NJ xhitlist extraction returned %d records; falling back to generic scrape",
            len(statutes),
        )
        fallback = await self._generic_scrape(code_name, code_url, "N.J. Stat. Ann.", max_sections=max(10, return_threshold))
        if not fallback:
            return statutes

        seen = {s.source_url for s in statutes if s.source_url}
        for statute in fallback:
            if statute.source_url in seen:
                continue
            seen.add(statute.source_url)
            statutes.append(statute)
        return statutes

    async def _scrape_direct_public_law_pdfs(self, code_name: str, max_statutes: int = 1) -> List[NormalizedStatute]:
        seeds = [
            ("P.L. 2025, c.1", "https://pub.njleg.state.nj.us/Bills/2024/PL25/1_.PDF"),
            ("P.L. 2025, c.2", "https://pub.njleg.state.nj.us/Bills/2024/PL25/2_.PDF"),
        ]
        out: List[NormalizedStatute] = []
        for cite, pdf_url in seeds[: max(1, int(max_statutes or 1))]:
            pdf_bytes = await self._request_bytes_direct(pdf_url, timeout=20)
            text = self._extract_pdf_text(pdf_bytes, max_chars=14000)
            if len(text) < 280:
                continue
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} {cite}",
                    code_name=code_name,
                    section_number=cite,
                    section_name=cite,
                    full_text=text,
                    legal_area=self._identify_legal_area(text[:1200]),
                    source_url=pdf_url,
                    official_cite=cite,
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_new_jersey_public_law_pdf",
                        "discovery_method": "official_seed_pdf",
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    async def _request_bytes_direct(self, url: str, timeout: int = 20) -> bytes:
        def _request() -> bytes:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return bytes(resp.read() or b"")
            except Exception:
                return b""

        try:
            import asyncio

            return await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 2)
        except Exception:
            return b""

    def _extract_pdf_text(self, pdf_bytes: bytes, max_chars: int) -> str:
        if not pdf_bytes:
            return ""
        try:
            proc = subprocess.run(
                ["pdftotext", "-layout", "-q", "-", "-"],
                input=pdf_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except Exception:
            return ""
        if proc.returncode != 0 or not proc.stdout:
            return ""
        text = proc.stdout.decode("utf-8", errors="ignore")
        return re.sub(r"\s+", " ", text).strip()[:max_chars]

    async def _scrape_via_xhitlist(self, code_name: str, max_sections: int = 120) -> List[NormalizedStatute]:
        """Collect NJ statutes from LIS query result pages.

        The LIS default page is JS-driven and often sparse when fetched as static
        HTML. Querying xhitlist returns concrete hitdoc links that can be parsed
        directly.
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        terms = ["tax", "crime", "property", "employment", "health"]
        seen_urls = set()
        statutes: List[NormalizedStatute] = []
        legal_area = self._identify_legal_area(code_name)

        for term in terms:
            if len(statutes) >= max_sections:
                break

            page = await self._fetch_xhitlist_page(term)
            if not page:
                continue

            soup = BeautifulSoup(page, "html.parser")
            for link in soup.find_all("a", href=True):
                if len(statutes) >= max_sections:
                    break

                href = str(link.get("href", "")).strip()
                if "f=hitdoc" not in href.lower():
                    continue

                link_text = link.get_text(strip=True)
                if not link_text or link_text.lower().startswith(("next", "last", "manage")):
                    continue

                source_url = urljoin(self._LIS_GATEWAY, href)
                if source_url in seen_urls:
                    continue
                seen_urls.add(source_url)

                section_number = self._extract_section_number(link_text)
                if not section_number:
                    section_number = self._derive_section_number_from_url(source_url)
                if not section_number:
                    section_number = f"Section-{len(statutes) + 1}"

                statutes.append(
                    NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § {section_number}",
                        code_name=code_name,
                        section_number=section_number,
                        section_name=link_text[:220],
                        full_text=f"Section {section_number}: {link_text}",
                        legal_area=legal_area,
                        source_url=source_url,
                        official_cite=f"N.J. Stat. Ann. § {section_number}",
                        metadata=StatuteMetadata(),
                    )
                )

        self.logger.info("NJ xhitlist extracted %d statute links", len(statutes))
        return statutes

    async def _fetch_xhitlist_page(self, query_term: str) -> str:
        """Fetch one NJ xhitlist result page as text for a simple query term."""
        params = {
            "f": "xhitlist",
            "xhitlist_vq": query_term,
            "xhitlist_q": query_term,
            "xhitlist_x": "Simple",
            "xhitlist_s": "relevance-weight",
            "xhitlist_mh": "120",
            "xhitlist_d": "",
            "xhitlist_hc": "",
            "xhitlist_xsl": "xhitlist.xsl",
            "xhitlist_vpc": "first",
            "xhitlist_vps": "50",
            "xhitlist_sel": self._XHITLIST_SELECT,
        }
        request_url = self._build_query_url(self._LIS_GATEWAY, params)
        raw = await self._fetch_page_content_with_archival_fallback(
            request_url,
            timeout_seconds=45,
        )
        if not raw:
            return ""
        try:
            return raw.decode("utf-8", errors="ignore")
        except Exception:
            return ""

    def _build_query_url(self, base_url: str, params: Dict[str, str]) -> str:
        """Build a URL query string without introducing extra dependencies."""
        from urllib.parse import urlencode

        return f"{base_url}?{urlencode(params)}"


# Register this scraper with the registry
StateScraperRegistry.register("NJ", NewJerseyScraper)
