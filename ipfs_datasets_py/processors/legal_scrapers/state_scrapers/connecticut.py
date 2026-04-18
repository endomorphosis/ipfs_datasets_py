"""Scraper for Connecticut state laws.

This module contains the scraper for Connecticut statutes from the official state legislative website.
"""

import json
import re
import urllib.parse
import urllib.request
from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class ConnecticutScraper(BaseStateScraper):
    """Scraper for Connecticut state laws from https://www.cga.ct.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Connecticut's legislative website."""
        return "https://www.cga.ct.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Connecticut."""
        return [{
            "name": "Connecticut General Statutes",
            # Live endpoint currently fails SSL verification in several runtime
            # environments; seed from a stable archive snapshot instead.
            "url": "http://web.archive.org/web/20250101000000/http://www.cga.ct.gov/current/pub/titles.htm",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Connecticut's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return_threshold = self._bounded_return_threshold(30)
        live_stubs = await self._scrape_live_title_stubs(code_name, max_statutes=max(10, return_threshold))

        archival_stubs = await self._scrape_archived_chapter_stubs(code_name, max_statutes=max(10, return_threshold))

        candidate_urls = [
            code_url,
            "https://www.cga.ct.gov/current/pub/titles.htm",
            "https://law.justia.com/codes/connecticut/",
            "http://web.archive.org/web/20250101000000/https://law.justia.com/codes/connecticut/",
        ]

        best: List[NormalizedStatute] = []
        seen = set()
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            statutes = await self._custom_scrape_connecticut(code_name, candidate, "Conn. Gen. Stat.", max_sections=260)
            if len(statutes) > len(best):
                best = statutes
            if len(statutes) >= return_threshold:
                return statutes

            generic = await self._generic_scrape(code_name, candidate, "Conn. Gen. Stat.", max_sections=260)
            if len(generic) > len(best):
                best = generic
            if len(generic) >= return_threshold:
                return generic

        if len(live_stubs) > len(best):
            best = live_stubs

        if len(archival_stubs) > len(best):
            best = archival_stubs

        return best

    async def _scrape_live_title_stubs(self, code_name: str, max_statutes: int = 120) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError:
            return []

        url = "https://www.cga.ct.gov/current/pub/titles.htm"
        try:
            payload = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=35)
            if not payload:
                return []
        except Exception:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        out: List[NormalizedStatute] = []
        seen = set()
        for a in soup.find_all("a", href=True):
            if len(out) >= max_statutes:
                break
            href = str(a.get("href") or "").strip()
            text = str(a.get_text(" ", strip=True) or "").strip()
            if not href or not text:
                continue
            if "chap" not in href.lower() and "title" not in text.lower() and "chapter" not in text.lower():
                continue
            full_url = urljoin(url, href)
            section_number = self._extract_section_number(text) or str(len(out) + 1)
            key = section_number.lower()
            if key in seen:
                continue
            seen.add(key)

            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=text[:200],
                    full_text=f"Connecticut General Statutes {text}: {full_url}",
                    source_url=full_url,
                    legal_area=self._identify_legal_area(text),
                    official_cite=f"Conn. Gen. Stat. {section_number}",
                    metadata=StatuteMetadata(),
                )
            )
        return out

    async def _scrape_archived_chapter_stubs(self, code_name: str, max_statutes: int = 120) -> List[NormalizedStatute]:
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx?url=www.cga.ct.gov/current/pub/*"
            "&output=json&filter=statuscode:200&collapse=digest"
            f"&limit={max(1, int(max_statutes) * 6)}"
        )
        try:
            req = urllib.request.Request(cdx_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=45) as resp:
                rows = json.loads(resp.read().decode("utf-8", errors="ignore"))
        except Exception:
            return []

        if not isinstance(rows, list) or len(rows) < 2:
            return []

        out: List[NormalizedStatute] = []
        seen = set()
        for row in rows[1:]:
            if len(out) >= max_statutes:
                break
            if not isinstance(row, list) or len(row) < 3:
                continue
            ts = str(row[1] or "").strip()
            original = str(row[2] or "").strip()
            if not ts or not original:
                continue

            m = re.search(r"/(?:chap|chapter)([0-9A-Za-z]+)\.(?:htm|html)$", original, flags=re.IGNORECASE)
            chapter = m.group(1) if m else ""
            if not chapter:
                continue
            key = chapter.lower()
            if key in seen:
                continue
            seen.add(key)

            encoded = urllib.parse.quote(original, safe=':/?=&%.-_')
            source_url = f"https://web.archive.org/web/{ts}/{encoded}"
            title = f"Chapter {chapter}"
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {chapter}",
                    code_name=code_name,
                    section_number=chapter,
                    section_name=title,
                    full_text=f"Connecticut General Statutes {title}: {source_url}",
                    source_url=source_url,
                    legal_area=self._identify_legal_area(title),
                    official_cite=f"Conn. Gen. Stat. ch. {chapter}",
                    metadata=StatuteMetadata(),
                )
            )

        return out
    
    async def _custom_scrape_connecticut(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 100
    ) -> List[NormalizedStatute]:
        """Custom scraper for Connecticut's legislative website.
        
        Connecticut organizes statutes by titles with chapters underneath.
        """
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
                timeout_seconds=30,
            )
            if not page_bytes:
                raise RuntimeError(f"empty response for {code_url}")

            soup = BeautifulSoup(page_bytes, 'html.parser')
            
            # Find all links to titles/chapters
            links = soup.find_all('a', href=True)
            
            section_count = 0
            for link in links:
                if section_count >= max_sections:
                    break
                
                link_text = link.get_text(strip=True)
                link_href = link.get('href', '')
                
                # Look for title or chapter patterns in Connecticut's format
                if not link_text or len(link_text) < 5:
                    continue
                
                # Connecticut - very permissive matching to catch statute links
                # Accept links with numbers or common statute terms
                if not any(char.isdigit() for char in link_text):
                    keywords_ct = ['title', 'chapter', 'sec', '§', 'part', 'article', 'statute', 'cgs', 'law']
                    if not any(keyword in link_text.lower() for keyword in keywords_ct):
                        continue
                
                full_url = urljoin(code_url, link_href)
                
                section_number = self._extract_section_number(link_text)
                if not section_number:
                    section_number = f"Section-{section_count + 1}"
                
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
            
            self.logger.info(f"Connecticut custom scraper: Scraped {len(statutes)} sections")
            
            # Fallback to generic scraper if no data found
            if not statutes:
                self.logger.info("Connecticut custom scraper found no data, falling back to generic scraper")
                return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
            
        except Exception as e:
            self.logger.error(f"Connecticut custom scraper failed: {e}")
            return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
        
        return statutes


# Register this scraper with the registry
StateScraperRegistry.register("CT", ConnecticutScraper)
