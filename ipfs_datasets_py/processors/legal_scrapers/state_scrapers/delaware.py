"""Scraper for Delaware state laws.

Delaware Code Online uses heavy JavaScript rendering.
"""

from typing import List, Dict
import re
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class DelawareScraper(BaseStateScraper):
    """Scraper for Delaware state laws from https://delcode.delaware.gov
    
    NOTE: Delaware's website is heavily JavaScript-rendered.
    This scraper requires Playwright or returns limited results.
    """

    _DE_CHAPTER_URL_RE = re.compile(r"/title\d+/c\d+/index\.html$", re.IGNORECASE)

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            name = str(statute.section_name or "")
            source = str(statute.source_url or "")
            if source.lower().endswith('.pdf'):
                continue
            # Accept real section captures and skip title-level landing pages.
            if re.search(r"§\s*\d", name, re.IGNORECASE) or re.search(r"\b\d+\.[0-9A-Za-z\-]*", name):
                filtered.append(statute)
                continue
            if re.search(r"#\d+[A-Za-z\-]*$", source):
                filtered.append(statute)
                continue
            if self._DE_CHAPTER_URL_RE.search(source) and re.search(r"^Chapter\s+\d+", name, re.IGNORECASE):
                if str(statute.section_number or "").startswith("Section-"):
                    m = re.search(r"Chapter\s+(\d+[A-Za-z\-]*)", name, re.IGNORECASE)
                    if m:
                        statute.section_number = m.group(1)
                filtered.append(statute)
                continue
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for Delaware's legislative website."""
        return "https://delcode.delaware.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Delaware."""
        return [{
            "name": "Delaware Code",
            "url": f"{self.get_base_url()}/title1/c001/index.html",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape Delaware Code.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            f"{self.get_base_url()}/title1/c001/index.html",
            f"{self.get_base_url()}/title11/c005/index.html",
            f"{self.get_base_url()}/title6/c001/index.html",
            f"{self.get_base_url()}/index.html",
            code_url,
        ]

        best_statutes: List[NormalizedStatute] = []
        seen = set()
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            if PLAYWRIGHT_AVAILABLE:
                try:
                    self.logger.info("Delaware: Using Playwright for JavaScript rendering")
                    statutes = await self._scrape_with_playwright(code_name, candidate, "Del. Code")
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if len(statutes) >= 20:
                        return statutes
                except Exception as e:
                    self.logger.warning(f"Delaware Playwright scrape failed for {candidate}: {e}")

            self.logger.warning("Delaware requires Playwright for JavaScript rendering - using fallback")
            statutes = await self._custom_scrape_delaware(code_name, candidate, "Del. Code")
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(statutes) >= 20:
                return statutes

        return best_statutes
    
    async def _scrape_with_playwright(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 30
    ) -> List[NormalizedStatute]:
        """Scrape Delaware using Playwright for JavaScript rendering."""
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []
        
        statutes = []
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            try:
                self.logger.info(f"Delaware: Loading {code_url}")
                await page.goto(code_url, wait_until='networkidle', timeout=60000)
                await page.wait_for_selector('a[href*="title"], div.title-links', timeout=10000)
                
                content = await page.content()
                soup = BeautifulSoup(content, 'html.parser')
                
                links = soup.find_all('a', href=True)
                title_links = [
                    l for l in links
                    if not l.get('href', '').lower().endswith('.pdf')
                    and (
                        self._DE_CHAPTER_URL_RE.search(l.get('href', ''))
                        or '§' in l.get_text(strip=True)
                        or re.search(r"\b\d+\.[0-9A-Za-z\-]*", l.get_text(strip=True))
                    )
                ][:40]
                
                self.logger.info(f"Delaware: Found {len(title_links)} title links")
                
                section_count = 0
                for link in title_links:
                    if section_count >= max_sections:
                        break
                    
                    link_text = link.get_text(strip=True)
                    link_href = link.get('href', '')
                    
                    if len(link_text) < 3:
                        continue
                    
                    full_url = urljoin(code_url, link_href)
                    section_number = self._extract_section_number(link_text) or f"Section-{section_count + 1}"
                    legal_area = self._identify_legal_area(link_text)
                    
                    statute = NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § {section_number}",
                        code_name=code_name,
                        section_number=section_number,
                        section_name=link_text[:200],
                        full_text=f"Title {section_number}: {link_text}",
                        legal_area=legal_area,
                        source_url=full_url,
                        official_cite=f"{citation_format} § {section_number}",
                        metadata=StatuteMetadata()
                    )
                    
                    statutes.append(statute)
                    section_count += 1
                
                self.logger.info(f"Delaware Playwright: Scraped {len(statutes)} sections")
                
            finally:
                await browser.close()
        
        return statutes
    
    async def _custom_scrape_delaware(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 100
    ) -> List[NormalizedStatute]:
        """Custom scraper for Delaware (basic fallback without Playwright)."""
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
                return []

            soup = BeautifulSoup(page_bytes, 'html.parser')
            
            # Delaware uses JavaScript rendering, so this will find few/no links
            links = soup.find_all('a', href=True)
            self.logger.info(f"Delaware: Found {len(links)} links (JS-rendered page - likely incomplete)")
            
            section_count = 0
            for link in links:
                if section_count >= max_sections:
                    break
                
                link_text = link.get_text(strip=True)
                link_href = link.get('href', '')
                
                if not link_text or len(link_text) < 5 or link_href.endswith('.pdf'):
                    continue
                
                # Accept chapter/index and section-like entries, but skip PDFs.
                if link_href.lower().endswith('.pdf'):
                    continue
                is_candidate = bool(self._DE_CHAPTER_URL_RE.search(link_href)) or ('§' in link_text) or bool(re.search(r"\b\d+\.[0-9A-Za-z\-]*", link_text))
                if not is_candidate:
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
            
            self.logger.info(f"Delaware custom scraper: Scraped {len(statutes)} sections (JavaScript rendering required for full results)")
            
        except Exception as e:
            self.logger.error(f"Delaware custom scraper failed: {e}")
        
        return statutes


# Register this scraper with the registry
StateScraperRegistry.register("DE", DelawareScraper)
