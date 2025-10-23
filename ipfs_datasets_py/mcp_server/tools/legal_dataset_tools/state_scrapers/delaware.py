"""Scraper for Delaware state laws.

Delaware Code Online uses heavy JavaScript rendering.
"""

from typing import List, Dict
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
    
    def get_base_url(self) -> str:
        """Return the base URL for Delaware's legislative website."""
        return "https://delcode.delaware.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Delaware."""
        return [{
            "name": "Delaware Code",
            "url": f"{self.get_base_url()}/index.html",
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
        if PLAYWRIGHT_AVAILABLE:
            self.logger.info("Delaware: Using Playwright for JavaScript rendering")
            return await self._scrape_with_playwright(code_name, code_url, "Del. Code")
        else:
            self.logger.warning("Delaware requires Playwright for JavaScript rendering - using fallback")
            return await self._custom_scrape_delaware(code_name, code_url, "Del. Code")
    
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
                title_links = [l for l in links if 'title' in l.get('href', '').lower() and not l.get('href', '').endswith('.pdf')][:10]
                
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
                    section_number = self._extract_section_number(link_text) or f"Title-{section_count + 1}"
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
            import requests
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []
        
        statutes = []
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(code_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
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
                
                # Accept links with 'title' or numbers
                if 'title' not in link_href.lower() and not any(char.isdigit() for char in link_text):
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
