"""Scraper for Indiana state laws.

This module contains the scraper for Indiana statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class IndianaScraper(BaseStateScraper):
    """Scraper for Indiana state laws from http://iga.in.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Indiana's legislative website."""
        return "http://iga.in.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Indiana."""
        return [{
            "name": "Indiana Code",
            "url": "http://iga.in.gov/static-documents/",  # Static HTML page, more reliable
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Indiana's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        if PLAYWRIGHT_AVAILABLE:
            self.logger.info("Indiana: Using Playwright for JavaScript rendering")
            try:
                result = await self._scrape_with_playwright(code_name, code_url, "Ind. Code")
                if result:
                    return result
            except Exception as e:
                self.logger.warning(f"Indiana Playwright failed: {e}, falling back")
        
        return await self._custom_scrape_indiana(code_name, code_url, "Ind. Code")
    
    async def _scrape_with_playwright(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 50
    ) -> List[NormalizedStatute]:
        """Scrape Indiana using Playwright for JavaScript rendering."""
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError:
            return []
        
        statutes = []
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            try:
                self.logger.info(f"Indiana: Loading {code_url}")
                await page.goto(code_url, wait_until='domcontentloaded', timeout=60000)
                
                # Wait for any content to load - more permissive
                try:
                    await page.wait_for_selector('a', timeout=15000)
                except:
                    self.logger.warning("Indiana: Timeout waiting for links, proceeding anyway")
                
                # Give JavaScript time to render
                await page.wait_for_timeout(2000)
                
                content = await page.content()
                soup = BeautifulSoup(content, 'html.parser')
                links = soup.find_all('a', href=True)
                
                self.logger.info(f"Indiana: Found {len(links)} total links")
                
                section_count = 0
                for link in links:
                    if section_count >= max_sections:
                        break
                    
                    link_text = link.get_text(strip=True)
                    link_href = link.get('href', '')
                    
                    if len(link_text) < 3:
                        continue
                    
                    # Very permissive keyword matching for Indiana
                    keywords = ['title', 'article', 'chapter', 'ic', 'code', 'pdf', 'indiana', 'statute']
                    if not any(k in link_text.lower() or k in link_href.lower() for k in keywords):
                        continue
                    
                    full_url = urljoin(code_url, link_href)
                    section_number = self._extract_section_number(link_text) or f"Doc-{section_count + 1}"
                    
                    statute = NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § {section_number}",
                        code_name=code_name,
                        section_number=section_number,
                        section_name=link_text[:200],
                        full_text=f"Document {section_number}: {link_text}",
                        legal_area=self._identify_legal_area(link_text),
                        source_url=full_url,
                        official_cite=f"{citation_format} § {section_number}",
                        metadata=StatuteMetadata()
                    )
                    
                    statutes.append(statute)
                    section_count += 1
                
                self.logger.info(f"Indiana Playwright: Scraped {len(statutes)} sections")
                
            finally:
                await browser.close()
        
        return statutes
    
    async def _custom_scrape_indiana(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 100
    ) -> List[NormalizedStatute]:
        """Custom scraper for Indiana's legislative website.
        
        Indiana's website is a JavaScript SPA (Single Page Application).
        For better results, consider:
        1. Using Playwright to render JavaScript
        2. Accessing alternative API endpoints
        3. Using Internet Archive snapshots
        """
        try:
            import requests
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []
        
        statutes = []
        
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = requests.get(code_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            links = soup.find_all('a', href=True)
            
            section_count = 0
            for link in links:
                if section_count >= max_sections:
                    break
                
                link_text = link.get_text(strip=True)
                link_href = link.get('href', '')
                
                if not link_text or len(link_text) < 5:
                    continue
                
                # Indiana Code patterns - relaxed matching
                keywords_in = ['title', 'article', 'chapter', 'ic', '§', 'section', 'part', 'code', 'ind.']
                if not any(keyword in link_text.lower() for keyword in keywords_in):
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
                    full_text=f"Section {section_number}: {link_text}",
                    legal_area=legal_area,
                    source_url=full_url,
                    official_cite=f"{citation_format} § {section_number}",
                    metadata=StatuteMetadata()
                )
                
                statutes.append(statute)
                section_count += 1
            
            self.logger.info(f"Indiana custom scraper: Scraped {len(statutes)} sections")
            
            # Fallback to generic scraper if no data found
            if not statutes:
                self.logger.warning("Indiana custom scraper found no data - site uses JavaScript")
                self.logger.info("For Indiana, consider using:")
                self.logger.info("  1. Playwright for JavaScript rendering")
                self.logger.info("  2. Alternative URL: http://iga.in.gov/static-documents/")
                self.logger.info("  3. Internet Archive snapshots")
                return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
            
        except Exception as e:
            self.logger.error(f"Indiana custom scraper failed: {e}")
            self.logger.info("Note: Indiana's site requires JavaScript. Consider using Playwright.")
            return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
        
        return statutes


# Register this scraper with the registry
StateScraperRegistry.register("IN", IndianaScraper)
