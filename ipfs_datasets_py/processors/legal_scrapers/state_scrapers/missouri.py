"""Scraper for Missouri state laws.

This module contains the scraper for Missouri statutes from the official state legislative website.
"""

import re
from typing import List, Dict, Optional
from urllib.parse import parse_qs, urljoin, urlparse
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class MissouriScraper(BaseStateScraper):
    """Scraper for Missouri state laws from http://www.moga.mo.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Missouri's legislative website."""
        return "https://revisor.mo.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Missouri."""
        return [{
            "name": "Missouri Revised Statutes",
            "url": f"{self.get_base_url()}/main/Home.aspx",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Missouri's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=2)
        # Use custom scraper with Missouri-specific patterns
        fallback = await self._custom_scrape_missouri(
            code_name,
            code_url,
            "Mo. Rev. Stat.",
            max_sections=limit or 1000000,
        )
        if fallback:
            if limit is not None:
                return fallback[:limit]
            return list(fallback)

        if not self._full_corpus_enabled():
            direct = await self._scrape_direct_sections(code_name, max_statutes=limit or 2)
            if direct:
                return direct
        return []

    async def _scrape_direct_sections(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        section_urls = [
            f"{self.get_base_url()}/main/OneSection.aspx?section=1.010",
            f"{self.get_base_url()}/main/OneSection.aspx?section=565.020",
        ]
        statutes: List[NormalizedStatute] = []
        for source_url in section_urls[: max(1, int(max_statutes or 1))]:
            payload = await self._fetch_page_content_with_archival_fallback(source_url, timeout_seconds=12)
            if not payload:
                continue
            text, section_name = self._extract_section_text_and_name(payload)
            if len(text) < 280:
                continue
            match = re.search(r"\b(\d+\.\d+[A-Za-z]*)\b", text)
            section_number = match.group(1) if match else source_url.rsplit("section=", 1)[-1]
            statutes.append(
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
                    official_cite=f"Mo. Rev. Stat. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_missouri_section_html",
                        "discovery_method": "official_direct_section",
                        "skip_hydrate": True,
                    },
                )
            )
        return statutes
    
    async def _custom_scrape_missouri(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 220
    ) -> List[NormalizedStatute]:
        """Custom scraper for Missouri's legislative website.
        
        Use the Missouri Revisor site and gather section links from chapter pages.
        This avoids very slow fallback URL chains that can cause global timeout.
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []
        
        statutes = []
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
        }

        try:
            home_url = f"{self.get_base_url()}/main/Home.aspx"
            home_bytes = await self._fetch_page_content_with_archival_fallback(
                home_url,
                timeout_seconds=20,
            )
            if not home_bytes:
                return []
            soup = BeautifulSoup(home_bytes, 'html.parser')
        except Exception as e:
            self.logger.warning(f"Missouri: failed to load home page: {e}")
            return []

        chapter_urls = []
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            if 'OneChapter.aspx?chapter=' not in href:
                continue
            full = urljoin(home_url, href)
            if full not in chapter_urls:
                chapter_urls.append(full)

        # Keep non-full-corpus probes bounded, but allow daemon full-corpus
        # runs to walk every chapter exposed by the official index.
        if not self._full_corpus_enabled():
            chapter_urls = chapter_urls[:28]
        seen_sections = set()

        for chapter_url in chapter_urls:
            if len(statutes) >= max_sections:
                break
            chapter_vals = parse_qs(urlparse(chapter_url).query).get('chapter') or []
            chapter_number = (chapter_vals[0].strip() if chapter_vals else '')
            try:
                chapter_bytes = await self._fetch_page_content_with_archival_fallback(
                    chapter_url,
                    timeout_seconds=20,
                )
                if not chapter_bytes:
                    continue
                chap_soup = BeautifulSoup(chapter_bytes, 'html.parser')
            except Exception:
                continue

            for link in chap_soup.find_all('a', href=True):
                if len(statutes) >= max_sections:
                    break
                href = link.get('href', '')
                if 'OneSection.aspx?section=' not in href:
                    continue

                full_url = urljoin(chapter_url, href)
                parsed = urlparse(full_url)
                section_vals = parse_qs(parsed.query).get('section') or []
                section_number = (section_vals[0].strip() if section_vals else '')
                if not section_number:
                    continue
                if section_number in seen_sections:
                    continue
                seen_sections.add(section_number)

                link_text = link.get_text(' ', strip=True) or f"Section {section_number}"
                section_payload = await self._fetch_page_content_with_archival_fallback(
                    full_url,
                    timeout_seconds=20,
                )
                full_text, extracted_name = self._extract_section_text_and_name(section_payload or b"")
                section_name = (extracted_name or link_text or f"Section {section_number}")[:200]
                if not full_text:
                    full_text = f"Section {section_number}: {link_text}"

                legal_area = self._identify_legal_area(link_text or code_name)
                statute = NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name,
                    full_text=full_text[:14000],
                    legal_area=legal_area,
                    source_url=full_url,
                    official_cite=f"{citation_format} § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_missouri_section_html",
                        "discovery_method": "official_chapter_index_sections",
                    },
                )
                statutes.append(statute)

        # Missouri sometimes serves heavily collapsed chapter pages where only one
        # repeated section link is visible. Use chapter links as a bounded fallback.
        if len(statutes) < 10:
            for chapter_url in chapter_urls:
                if len(statutes) >= max_sections:
                    break
                chapter_vals = parse_qs(urlparse(chapter_url).query).get('chapter') or []
                chapter_number = (chapter_vals[0].strip() if chapter_vals else '')
                if not chapter_number or chapter_number in seen_sections:
                    continue
                seen_sections.add(chapter_number)

                chapter_label = f"Chapter {chapter_number}"
                statute = NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {chapter_number}",
                    code_name=code_name,
                    section_number=chapter_number,
                    section_name=chapter_label,
                    full_text=f"{chapter_label}: Missouri Revised Statutes chapter",
                    legal_area=self._identify_legal_area(chapter_label),
                    source_url=chapter_url,
                    official_cite=f"{citation_format} ch. {chapter_number}",
                    metadata=StatuteMetadata(),
                )
                statutes.append(statute)

        self.logger.info(f"Missouri custom scraper: Scraped {len(statutes)} sections")
        if not statutes:
            self.logger.warning("Missouri custom scraper found no section-level links")
            return []
        
        return statutes

    def _extract_section_text_and_name(self, payload: bytes) -> tuple[str, str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return "", ""

        soup = BeautifulSoup(payload, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()

        section_node = soup.select_one("div.norm")
        history_nodes = soup.select("div.foot p")
        body_parts: List[str] = []

        if section_node is not None:
            body_parts.append(self._normalize_legal_text(section_node.get_text(" ", strip=True)))
        for node in history_nodes:
            text = self._normalize_legal_text(node.get_text(" ", strip=True))
            if text:
                body_parts.append(text)

        if not body_parts:
            body_parts.append(self._normalize_legal_text(soup.get_text(" ", strip=True)))

        full_text = " ".join(part for part in body_parts if part).strip()
        section_name = ""
        heading_match = re.search(r"\b\d+\.\d+[A-Za-z]*\.\s*(.+?)\s+[—-]\s+", full_text)
        if heading_match:
            section_name = heading_match.group(1).strip()
        if not section_name:
            title_match = re.search(
                r"<meta\s+property=\"og:description\"\s+content=\"([^\"]+)\"",
                payload.decode("utf-8", errors="replace"),
                re.IGNORECASE,
            )
            if title_match:
                section_name = self._normalize_legal_text(title_match.group(1))
        if not section_name:
            section_name = "Section"
        return full_text, section_name


# Register this scraper with the registry
StateScraperRegistry.register("MO", MissouriScraper)
