"""Scraper for Nevada state laws.

This module contains the scraper for Nevada statutes from the official state legislative website.
"""

import re
import urllib.request
from typing import List, Dict, Optional, Tuple
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class NevadaScraper(BaseStateScraper):
    """Scraper for Nevada state laws from https://www.leg.state.nv.us"""

    _NRS_CHAPTER_HREF_RE = re.compile(r"^NRS-\d{3}[A-Z]?\.html$", re.IGNORECASE)
    _NRS_SECTION_NUMBER_RE = re.compile(r"^\d+[A-Z]?\.\d+(?:\.\d+)?[A-Z]?$")
    
    def get_base_url(self) -> str:
        """Return the base URL for Nevada's legislative website."""
        return "https://www.leg.state.nv.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Nevada."""
        return [{
            "name": "Nevada Revised Statutes",
            "url": f"{self.get_base_url()}/NRS/",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Nevada's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=40) or 1000000
        official = await self._scrape_official_index(
            code_name,
            max_statutes=None if limit == 1000000 else int(limit),
        )
        if official:
            return official[: int(limit)]

        if not self._full_corpus_enabled():
            direct = await self._scrape_direct_seed_sections(code_name, max_statutes=int(limit))
            if direct:
                return direct[: int(limit)]

        fallback_limit = max(10, int(limit if limit != 1000000 else 40))
        return await self._generic_scrape(code_name, code_url, "Nev. Rev. Stat.", max_sections=fallback_limit)

    async def _scrape_direct_seed_sections(self, code_name: str, max_statutes: int = 2) -> List[NormalizedStatute]:
        seeds = [
            ("1.010", f"{self.get_base_url()}/NRS/NRS-001.html"),
            ("200.010", f"{self.get_base_url()}/NRS/NRS-200.html"),
        ]
        chapter_rows = await self._scrape_chapter_pages(
            code_name,
            [url for _, url in seeds[: max(1, int(max_statutes or 1))]],
            max_statutes=max_statutes,
            discovery_method="official_seed_chapter_inline_sections",
        )
        return chapter_rows[: max(1, int(max_statutes or 1))]

    async def _scrape_official_index(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        chapter_pages = await self._discover_chapter_pages()
        self.logger.info("Nevada official index: discovered %s chapter pages", len(chapter_pages))
        return await self._scrape_chapter_pages(
            code_name,
            chapter_pages,
            max_statutes=max_statutes,
            discovery_method="official_title_chapter_inline_sections",
        )

    async def _discover_chapter_pages(self) -> List[str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = f"{self.get_base_url()}/NRS/"
        html = await self._request_text_direct(index_url, timeout=30)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        out: List[str] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            if not self._NRS_CHAPTER_HREF_RE.match(href):
                continue
            chapter_url = f"{self.get_base_url()}/NRS/{href.lstrip('/')}"
            if chapter_url in seen:
                continue
            seen.add(chapter_url)
            out.append(chapter_url)
        return out

    async def _scrape_chapter_pages(
        self,
        code_name: str,
        chapter_pages: List[str],
        *,
        max_statutes: Optional[int],
        discovery_method: str,
    ) -> List[NormalizedStatute]:
        statutes: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for chapter_index, chapter_url in enumerate(chapter_pages, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            remaining = None if limit is None else max(0, limit - len(statutes))
            if remaining is not None and remaining <= 0:
                break
            chapter_rows = await self._extract_sections_from_chapter_page(
                code_name,
                chapter_url,
                discovery_method=discovery_method,
                max_statutes=remaining,
            )
            statutes.extend(chapter_rows)
            if chapter_index == 1 or chapter_index % 25 == 0 or chapter_index == len(chapter_pages):
                self.logger.info(
                    "Nevada official index: chapter=%s/%s yielded=%s statutes_so_far=%s",
                    chapter_index,
                    len(chapter_pages),
                    len(chapter_rows),
                    len(statutes),
                )
        return statutes[:limit] if limit is not None else statutes

    async def _extract_sections_from_chapter_page(
        self,
        code_name: str,
        chapter_url: str,
        *,
        discovery_method: str,
        max_statutes: Optional[int],
    ) -> List[NormalizedStatute]:
        if max_statutes is not None and int(max_statutes) <= 0:
            return []
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        html = await self._request_text_direct(chapter_url, timeout=35)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        paragraphs = soup.find_all("p")
        out: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        current: Dict[str, object] | None = None

        def _flush_current() -> None:
            nonlocal current
            if not current:
                return
            section_number = str(current.get("section_number") or "").strip()
            section_name = str(current.get("section_name") or "").strip()
            body_parts = [str(item).strip() for item in current.get("body_parts") or [] if str(item).strip()]
            if not section_number or not body_parts:
                current = None
                return
            full_text = self._normalize_legal_text(" ".join(body_parts))
            if len(full_text) < 120:
                current = None
                return
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=(section_name or f"NRS {section_number}")[:200],
                    full_text=full_text[:14000],
                    legal_area=self._identify_legal_area(section_name or full_text[:800]),
                    source_url=f"{chapter_url}#{current.get('anchor')}" if current.get("anchor") else chapter_url,
                    official_cite=f"Nev. Rev. Stat. § {section_number}",
                    structured_data={
                        "source_kind": "official_nevada_revised_statutes_html",
                        "discovery_method": discovery_method,
                        "chapter_url": chapter_url,
                        "skip_hydrate": True,
                    },
                )
            )
            current = None

        for paragraph in paragraphs:
            if limit is not None and len(out) >= limit:
                break
            anchor = paragraph.find("a", attrs={"name": True})
            section_span = paragraph.find("span", class_="Section")
            if anchor is not None and section_span is not None:
                _flush_current()
                section_number = self._normalize_legal_text(section_span.get_text(" ", strip=True))
                if not self._NRS_SECTION_NUMBER_RE.match(section_number):
                    continue
                leadline = paragraph.find("span", class_="Leadline")
                section_name = self._normalize_legal_text(leadline.get_text(" ", strip=True)) if leadline else ""
                text = self._normalize_legal_text(paragraph.get_text(" ", strip=True))
                current = {
                    "anchor": str(anchor.get("name") or "").strip(),
                    "section_number": section_number,
                    "section_name": section_name,
                    "body_parts": [text] if text else [],
                }
                continue
            if current is None:
                continue
            css_classes = {str(value) for value in (paragraph.get("class") or [])}
            if "SectBody" not in css_classes:
                continue
            text = self._normalize_legal_text(paragraph.get_text(" ", strip=True))
            if text:
                cast_parts = current.setdefault("body_parts", [])
                if isinstance(cast_parts, list):
                    cast_parts.append(text)

        _flush_current()
        return out[:limit] if limit is not None else out

    async def _request_text_direct(self, url: str, timeout: int = 18) -> str:
        def _request() -> str:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read().decode("windows-1252", errors="replace")
            except Exception:
                return ""

        try:
            import asyncio

            return await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 2)
        except Exception:
            return ""


# Register this scraper with the registry
StateScraperRegistry.register("NV", NevadaScraper)
