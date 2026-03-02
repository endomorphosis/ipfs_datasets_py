"""Scraper for Georgia state laws.

This module contains the scraper for Georgia statutes from the official state legislative website.
"""

import re
import subprocess
import tempfile
from typing import List, Dict

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class GeorgiaScraper(BaseStateScraper):
    """Scraper for Georgia state laws from http://www.legis.ga.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Georgia's legislative website."""
        return "http://www.legis.ga.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Georgia."""
        return [{
            "name": "Official Code of Georgia",
            "url": f"{self.get_base_url()}/legislation/laws.html",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Georgia's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        summary_pdf_statutes = await self._scrape_general_statute_summary_pdfs(code_name)
        if summary_pdf_statutes:
            return summary_pdf_statutes

        if PLAYWRIGHT_AVAILABLE:
            self.logger.info("Georgia: Using Playwright for JavaScript rendering")
            try:
                result = await self._scrape_with_playwright(code_name, code_url, "Ga. Code Ann.")
                if result:
                    return result
            except Exception as e:
                self.logger.warning(f"Georgia Playwright failed: {e}, falling back")
        
        return await self._custom_scrape_georgia(code_name, code_url, "Ga. Code Ann.")

    async def _scrape_general_statute_summary_pdfs(self, code_name: str) -> List[NormalizedStatute]:
        """Use official GA-hosted General Statutes summary PDFs as strict-safe fallback."""
        candidate_docs = [
            (
                "2025",
                "https://www.legis.ga.gov/api/document/docs/default-source/legislative-counsel-document-library/25sumdoc.pdf?sfvrsn=95973fc9_4",
            ),
            (
                "2024",
                "https://www.legis.ga.gov/api/document/docs/default-source/legislative-counsel-document-library/2024-general-statutes-summary-pdf.pdf?sfvrsn=38862f9_8",
            ),
        ]

        statutes: List[NormalizedStatute] = []
        for year, pdf_url in candidate_docs:
            text = await self._extract_pdf_text_summary(pdf_url)
            if len(text) < 280:
                continue

            statute = NormalizedStatute(
                state_code=self.state_code,
                state_name=self.state_name,
                statute_id=f"{code_name} § Summary-{year}",
                code_name=code_name,
                section_number=year,
                section_name=f"Summary of {year} General Statutes",
                full_text=text,
                legal_area="general",
                source_url=pdf_url,
                official_cite=f"Ga. Gen. Stat. Summary ({year})",
                metadata=StatuteMetadata(),
            )
            statutes.append(statute)

        if statutes:
            self.logger.info(f"Georgia summary PDF fallback: Scraped {len(statutes)} records")
        return statutes

    async def _extract_pdf_text_summary(self, pdf_url: str, max_chars: int = 12000) -> str:
        """Download PDF and extract normalized text via pdftotext."""
        try:
            payload = await self._fetch_page_content_with_archival_fallback(
                pdf_url,
                timeout_seconds=60,
            )
            if not payload:
                return ""
        except Exception as exc:
            self.logger.debug(f"Georgia PDF download failed for {pdf_url}: {exc}")
            return ""

        try:
            with tempfile.TemporaryDirectory(prefix="ga_sum_pdf_") as tmpdir:
                from pathlib import Path

                pdf_path = Path(tmpdir) / "summary.pdf"
                txt_path = Path(tmpdir) / "summary.txt"
                pdf_path.write_bytes(payload)

                result = subprocess.run(
                    ["pdftotext", "-f", "1", "-l", "12", str(pdf_path), str(txt_path)],
                    capture_output=True,
                    text=True,
                    timeout=40,
                    check=False,
                )
                if int(result.returncode) != 0 or not txt_path.exists():
                    return ""

                text = txt_path.read_text(encoding="utf-8", errors="ignore")
                text = re.sub(r"\s+", " ", text).strip()
                return text[:max_chars]
        except Exception as exc:
            self.logger.debug(f"Georgia PDF extraction failed for {pdf_url}: {exc}")
            return ""
    
    async def _scrape_with_playwright(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 30
    ) -> List[NormalizedStatute]:
        """Scrape Georgia using Playwright for JavaScript rendering."""
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
                for link in links:
                    if section_count >= max_sections:
                        break
                    
                    link_text = link.get_text(strip=True)
                    link_href = link.get('href', '')
                    
                    if len(link_text) < 5:
                        continue
                    
                    keywords = ['title', 'chapter', 'code', 'statute']
                    if not any(k in link_text.lower() for k in keywords):
                        continue
                    
                    full_url = urljoin(code_url, link_href)
                    section_number = self._extract_section_number(link_text) or f"Section-{section_count + 1}"
                    
                    statute = NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § {section_number}",
                        code_name=code_name,
                        section_number=section_number,
                        section_name=link_text[:200],
                        full_text=f"Section {section_number}: {link_text}",
                        legal_area=self._identify_legal_area(link_text),
                        source_url=full_url,
                        official_cite=f"{citation_format} § {section_number}",
                        metadata=StatuteMetadata()
                    )
                    
                    statutes.append(statute)
                    section_count += 1
                
                self.logger.info(f"Georgia Playwright: Scraped {len(statutes)} sections")
                
            finally:
                await browser.close()
        
        return statutes
    
    async def _custom_scrape_georgia(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 100
    ) -> List[NormalizedStatute]:
        """Custom scraper for Georgia's legislative website.
        
        Georgia's website is a JavaScript SPA (Single Page Application).
        For better results, consider:
        1. Using Playwright to render JavaScript
        2. Accessing alternative sources like LexisNexis or Internet Archive
        3. Using the Georgia Code API if available
        """
        # Try alternative URLs first
        alternative_urls = [
            "https://advance.lexis.com/container?config=014CJAAyZGVmYXVsdHM6OTU5ZDJjOGYtMGZjMC00MGI0LWIzYzEtNmVhYTZmYzJmY2RhKgxYmRQzkSm9zOIGXjY8",  # LexisNexis
            "http://web.archive.org/web/*/www.legis.ga.gov/legislation/laws.html"  # Internet Archive
        ]
        
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
            links = soup.find_all('a', href=True)
            
            section_count = 0
            for link in links:
                if section_count >= max_sections:
                    break
                
                link_text = link.get_text(strip=True)
                link_href = link.get('href', '')
                
                if not link_text or len(link_text) < 5:
                    continue
                
                # Georgia Code patterns - relaxed matching
                keywords_ga = ['title', 'chapter', '§', 'section', 'part', 'code', 'statute', 'article', 'ga.']
                if not any(keyword in link_text.lower() for keyword in keywords_ga):
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
            
            self.logger.info(f"Georgia custom scraper: Scraped {len(statutes)} sections")
            
            # Fallback to generic scraper if no data found
            if not statutes:
                self.logger.warning("Georgia custom scraper found no data - site uses JavaScript")
                self.logger.info("For Georgia, consider using:")
                self.logger.info("  1. Playwright for JavaScript rendering: pip install playwright && playwright install")
                self.logger.info("  2. Alternative source: Internet Archive")
                self.logger.info("  3. API access if available from GA General Assembly")
                return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
            
        except Exception as e:
            self.logger.error(f"Georgia custom scraper failed: {e}")
            self.logger.info("Note: Georgia's site requires JavaScript. Consider using Playwright.")
            return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
        
        return statutes


# Register this scraper with the registry
StateScraperRegistry.register("GA", GeorgiaScraper)
