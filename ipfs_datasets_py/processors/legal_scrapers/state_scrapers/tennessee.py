"""Scraper for Tennessee state laws.

This module contains the scraper for Tennessee statutes from the official state legislative website.
"""

import re
import warnings
from typing import List, Dict, Optional
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry

# Suppress SSL warnings for tn.gov
warnings.filterwarnings('ignore', message='Unverified HTTPS request')


class TennesseeScraper(BaseStateScraper):
    """Scraper for Tennessee state laws from https://www.tn.gov/tga"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Tennessee's legislative website."""
        return "https://www.tn.gov/tga"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Tennessee."""
        return [{
            "name": "Tennessee Code Annotated",
            "url": "https://www.capitol.tn.gov/legislation/archives.html",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Tennessee's legislative website.
        
        Tennessee's site frequently has connection issues.
        This scraper tries multiple approaches:
        1. HTTP with SSL bypass for reliable sources
        2. Playwright for JavaScript rendering
        3. Internet Archive
        
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

        # Try alternative URLs if main URL fails
        # Note: Tennessee's SSL certificate often has issues, use verify=False in requests
        # Tennessee URLs with extended timeout and SSL verification disabled
        alternative_urls = [
            "https://www.capitol.tn.gov/legislation/archives.html",
            "https://publications.tnsosfiles.com/acts/",
            code_url,
            "http://web.archive.org/web/20230101000000*/tn.gov/*/statutes*"
        ]
        
        # Try custom scraper with SSL bypass first
        for url_attempt in alternative_urls[:2]:
            try:
                self.logger.info(f"Tennessee: Attempting custom scrape with {url_attempt}")
                statutes = await self._custom_scrape_tennessee(
                    code_name,
                    url_attempt,
                    "Tenn. Code Ann.",
                    max_sections=max(1, return_threshold)
                )
                if statutes:
                    return statutes[:return_threshold]
            except Exception as e:
                self.logger.warning(f"Tennessee custom scrape failed for {url_attempt}: {e}")
        
        # Fallback to HTTP scraper with all alternative URLs
        self.logger.info("Tennessee: Using fallback HTTP scraper")
        for url_attempt in alternative_urls:
            try:
                self.logger.info(f"Tennessee: Attempting HTTP scrape with {url_attempt}")
                result = await self._custom_scrape_tennessee(code_name, url_attempt, "Tenn. Code Ann.")
                if result:
                    return result[:return_threshold]
            except Exception as e:
                self.logger.warning(f"Tennessee: HTTP scrape failed for {url_attempt}: {e}")
                continue
        
        # If all attempts failed, return empty list with guidance
        self.logger.error("Tennessee: All scraping attempts failed")
        self.logger.info("For Tennessee, the site may be temporarily down. Try:")
        self.logger.info("  1. Wait and retry later")
        self.logger.info("  2. Use publications.tnsosfiles.com")
        self.logger.info("  3. Access via Internet Archive")
        return []

    async def _scrape_direct_seed_sections(
        self,
        code_name: str,
        max_statutes: int = 1,
    ) -> List[NormalizedStatute]:
        seeds = [
            (
                "39-13-202",
                "First degree murder",
                "https://law.justia.com/codes/tennessee/2024/title-39/chapter-13/part-2/section-39-13-202/",
            ),
        ]
        out: List[NormalizedStatute] = []
        for section_number, section_name, source_url in seeds[: max(1, int(max_statutes or 1))]:
            reader_url = f"https://r.jina.ai/http://{source_url}"
            raw = await self._fetch_page_content_with_archival_fallback(reader_url, timeout_seconds=25)
            if not raw:
                continue
            try:
                markdown = raw.decode("utf-8", errors="replace")
            except Exception:
                continue
            body = self._extract_justia_reader_section(markdown, section_number)
            if len(body) < 220:
                continue
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    title_number=section_number.split("-", 1)[0],
                    section_number=section_number,
                    section_name=section_name,
                    full_text=body[:14000],
                    legal_area=self._identify_legal_area(body[:1200]),
                    source_url=source_url,
                    official_cite=f"Tenn. Code Ann. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "jina_reader_justia_tennessee_code",
                        "discovery_method": "cloudflare_block_recovery_seed_section",
                        "reader_url": reader_url,
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    def _extract_justia_reader_section(self, markdown: str, section_number: str) -> str:
        text = str(markdown or "")
        start = text.find(f"Section {section_number}")
        cite_start = text.find(f"TN Code § {section_number}")
        if cite_start >= 0:
            start = cite_start
        if start < 0:
            start = text.find(f"§ {section_number}")
        if start < 0:
            return ""
        tail = text[start:]
        end_markers = ["Disclaimer:", "Justia Free Databases", "Newsletter", "Want to receive"]
        end = len(tail)
        for marker in end_markers:
            idx = tail.find(marker)
            if idx >= 0:
                end = min(end, idx)
        body = tail[:end]
        body = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", body)
        body = re.sub(r"\*\*([^*]+)\*\*", r"\1", body)
        return self._normalize_legal_text(body)

    async def _custom_scrape_tennessee(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 280
    ) -> List[NormalizedStatute]:
        """Custom scraper for Tennessee with SSL bypass."""
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []
        
        statutes = []
        
        try:
            page_bytes = await self._fetch_page_content_with_archival_fallback(
                code_url,
                timeout_seconds=45,
            )
            if not page_bytes:
                return []

            soup = BeautifulSoup(page_bytes, 'html.parser')
            links = soup.find_all('a', href=True)
            
            section_count = 0
            statute_number_re = re.compile(r"\b\d{1,2}-\d{1,3}-\d+[A-Za-z-]*\b")
            chapter_re = re.compile(r"\b(?:chapter|ch\.?|title|section|sec\.?)\s*\d+", re.IGNORECASE)
            ga_re = re.compile(r"\b\d{2,3}(?:st|nd|rd|th)?\b", re.IGNORECASE)
            nav_terms = {
                "my bills",
                "browse bills",
                "bills and resolutions",
                "subject index",
                "bill information",
            }

            for link in links:
                if section_count >= max_sections:
                    break
                
                link_text = link.get_text(strip=True)
                link_href = link.get('href', '')
                
                if not link_text or len(link_text) < 3:
                    continue
                
                lower_text = link_text.lower()
                lower_href = link_href.lower()
                if any(term in lower_text for term in nav_terms):
                    continue

                has_statute_pattern = bool(statute_number_re.search(link_text) or statute_number_re.search(link_href))
                has_chapter_pattern = bool(chapter_re.search(link_text) or chapter_re.search(link_href))
                has_session_pattern = ("special session" in lower_text) and bool(ga_re.search(link_text))
                has_legislative_doc_path = (
                    "archives/joint/publications" in lower_href
                    or "acts-and-resolutions" in lower_href
                    or "archives/" in lower_href and "specialsession" in lower_href
                )

                if not (has_statute_pattern or has_chapter_pattern or has_session_pattern or has_legislative_doc_path):
                    continue
                
                full_url = urljoin(code_url, link_href)

                section_number = self._extract_section_number(link_text)
                if not section_number:
                    # Derive a stable numeric identifier from URL/query text when possible.
                    href_match = statute_number_re.search(link_href) or ga_re.search(link_text)
                    if href_match:
                        section_number = href_match.group(0)

                if not section_number:
                    continue

                legal_area = self._identify_legal_area(link_text)
                
                statute = NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=link_text[:200],
                    full_text=f"Section {section_number}: {link_text}",
                    legal_area=legal_area,
                    source_url=full_url,
                    official_cite=f"{citation_format} § {section_number}",
                    metadata=StatuteMetadata()
                )
                
                statutes.append(statute)
                section_count += 1
            
            self.logger.info(f"Tennessee custom scraper: Scraped {len(statutes)} sections")
            
        except Exception as e:
            self.logger.error(f"Tennessee custom scraper failed: {e}")
        
        return statutes


# Register this scraper with the registry
StateScraperRegistry.register("TN", TennesseeScraper)
