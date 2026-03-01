"""Scraper for Wyoming state laws.

This module contains the scraper for Wyoming statutes from the official state legislative website.
"""

import re
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class WyomingScraper(BaseStateScraper):
    """Scraper for Wyoming state laws from https://www.wyoleg.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Wyoming's legislative website."""
        return "https://www.wyoleg.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Wyoming."""
        return [{
            "name": "Wyoming Statutes",
            "url": f"{self.get_base_url()}/stateStatutes/StatutesDownload",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Wyoming's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        if PLAYWRIGHT_AVAILABLE:
            self.logger.info("Wyoming: Using Playwright for JavaScript rendering")
            try:
                result = await self._scrape_with_playwright(code_name, code_url, "Wyo. Stat.")
                if result:
                    return result
            except Exception as e:
                self.logger.warning(f"Wyoming Playwright failed: {e}, falling back")
        
        return await self._custom_scrape_wyoming(code_name, code_url, "Wyo. Stat.")
    
    async def _scrape_with_playwright(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 60
    ) -> List[NormalizedStatute]:
        """Scrape Wyoming using Playwright for JavaScript rendering."""
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
                await page.goto(code_url, wait_until='networkidle', timeout=60000)
                await page.wait_for_selector('a', timeout=10000)
                
                content = await page.content()
                soup = BeautifulSoup(content, 'html.parser')
                links = soup.find_all('a', href=True)
                
                section_count = 0
                seen_urls = set()
                for link in links:
                    if section_count >= max_sections:
                        break
                    
                    link_text = link.get_text(strip=True)
                    link_href = link.get('href', '')
                    
                    if len(link_text) < 5:
                        continue
                    full_url = urljoin(code_url, link_href)
                    full_url_l = full_url.lower()
                    # Focus on authoritative downloadable title PDFs instead of nav links.
                    if not (full_url_l.endswith('.pdf') and '/statutes/compress/title' in full_url_l):
                        continue
                    if full_url in seen_urls:
                        continue
                    seen_urls.add(full_url)

                    section_number = self._extract_section_number(link_text) or f"Section-{section_count + 1}"
                    m = re.search(r"\btitle\s+(\d+(?:\.\d+)?)", link_text, re.IGNORECASE)
                    if m:
                        section_number = m.group(1)

                    full_text = self._extract_pdf_text_summary(full_url)
                    if len(full_text.strip()) < 80:
                        full_text = (
                            f"Wyoming Statutes Title {section_number}: {link_text}. "
                            f"Official source PDF: {full_url}."
                        )
                    
                    statute = NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § {section_number}",
                        code_name=code_name,
                        section_number=section_number,
                        section_name=link_text[:200],
                        full_text=full_text,
                        legal_area=self._identify_legal_area(link_text),
                        source_url=full_url,
                        official_cite=f"{citation_format} § {section_number}",
                        metadata=StatuteMetadata()
                    )
                    
                    statutes.append(statute)
                    section_count += 1
                
                self.logger.info(f"Wyoming Playwright: Scraped {len(statutes)} sections")
                
            finally:
                await browser.close()
        
        return statutes

    def _extract_pdf_text_summary(self, pdf_url: str, max_chars: int = 6000) -> str:
        """Extract statute text from a PDF using system `pdftotext`.

        This keeps Wyoming strict-mode scraping resilient without adding heavy PDF
        parser dependencies to the Python environment.
        """
        try:
            import requests

            response = requests.get(
                pdf_url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=45,
            )
            response.raise_for_status()

            with tempfile.TemporaryDirectory(prefix="wy_statute_pdf_") as td:
                pdf_path = Path(td) / "input.pdf"
                txt_path = Path(td) / "output.txt"
                pdf_path.write_bytes(response.content)

                proc = subprocess.run(
                    ["pdftotext", "-f", "1", "-l", "3", str(pdf_path), str(txt_path)],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
                if proc.returncode != 0 or not txt_path.exists():
                    return ""

                raw = txt_path.read_text(encoding="utf-8", errors="ignore")
                text = re.sub(r"\s+", " ", raw).strip()
                return text[:max_chars]
        except Exception as e:
            self.logger.debug(f"Wyoming PDF text extraction failed for {pdf_url}: {e}")
            return ""
    
    async def _custom_scrape_wyoming(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 100
    ) -> List[NormalizedStatute]:
        """Custom scraper for Wyoming's legislative website.
        
        Wyoming's website is a JavaScript SPA (Single Page Application).
        For better results, consider:
        1. Using Playwright to render JavaScript
        2. Accessing alternative static pages
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
                
                # Wyoming patterns - relaxed matching
                keywords_wy = ['title', 'chapter', '§', 'section', 'part', 'code', 'statute', 'article', 'wyo.']
                if not any(keyword in link_text.lower() for keyword in keywords_wy):
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
            
            self.logger.info(f"Wyoming custom scraper: Scraped {len(statutes)} sections")
            
            # Fallback to generic scraper if no data found
            if not statutes:
                self.logger.warning("Wyoming custom scraper found no data - site uses JavaScript")
                if PLAYWRIGHT_AVAILABLE:
                    self.logger.info("Wyoming custom scraper retrying with Playwright StatutesDownload page")
                    pw_statutes = await self._scrape_with_playwright(
                        code_name,
                        f"{self.get_base_url()}/stateStatutes/StatutesDownload",
                        citation_format,
                        max_sections=max_sections,
                    )
                    if pw_statutes:
                        return pw_statutes
                self.logger.info("For Wyoming, consider using:")
                self.logger.info("  1. Playwright for JavaScript rendering")
                self.logger.info("  2. Alternative URL: https://wyoleg.gov/statutes/compress/")
                self.logger.info("  3. Internet Archive snapshots")
                return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
            
        except Exception as e:
            self.logger.error(f"Wyoming custom scraper failed: {e}")
            self.logger.info("Note: Wyoming's site requires JavaScript. Consider using Playwright.")
            return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
        
        return statutes


# Register this scraper with the registry
StateScraperRegistry.register("WY", WyomingScraper)
