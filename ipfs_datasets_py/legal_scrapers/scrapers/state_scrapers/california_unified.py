"""California state law scraper - MIGRATED to unified scraper.

This is an example migration showing how to convert an existing scraper
to use the unified scraping system with content addressing.

Changes from original:
1. Inherit from StateScraperMixin for unified scraping methods
2. Convert sync requests to async unified scraper calls
3. Add content addressing for deduplication
4. Enable multi-source fallback (Common Crawl, Wayback, etc.)
"""

from typing import List, Dict, Optional
import re
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry

# NEW: Import unified scraping components
from .scraper_adapter import StateScraperMixin


class CaliforniaScraperUnified(BaseStateScraper, StateScraperMixin):
    """Scraper for California state laws - Using Unified Scraper.
    
    This version uses the unified scraping system which provides:
    - Content addressing (IPFS CIDs)
    - Deduplication
    - Multi-source fallback (Common Crawl, Wayback, live)
    - WARC export
    - Parallel scraping
    """
    
    def get_base_url(self) -> str:
        """Get base URL for California Legislative Information."""
        return "https://leginfo.legislature.ca.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Get list of California codes.
        
        California has 29 codes organized by subject matter.
        """
        base_url = self.get_base_url()
        
        codes = [
            {"name": "Business and Professions Code", "url": f"{base_url}/faces/codes.xhtml", "type": "BPC"},
            {"name": "Civil Code", "url": f"{base_url}/faces/codes.xhtml", "type": "CIV"},
            {"name": "Code of Civil Procedure", "url": f"{base_url}/faces/codes.xhtml", "type": "CCP"},
            {"name": "Commercial Code", "url": f"{base_url}/faces/codes.xhtml", "type": "COM"},
            {"name": "Corporations Code", "url": f"{base_url}/faces/codes.xhtml", "type": "CORP"},
            {"name": "Education Code", "url": f"{base_url}/faces/codes.xhtml", "type": "EDC"},
            {"name": "Elections Code", "url": f"{base_url}/faces/codes.xhtml", "type": "ELEC"},
            {"name": "Evidence Code", "url": f"{base_url}/faces/codes.xhtml", "type": "EVID"},
            {"name": "Family Code", "url": f"{base_url}/faces/codes.xhtml", "type": "FAM"},
            {"name": "Financial Code", "url": f"{base_url}/faces/codes.xhtml", "type": "FIN"},
            {"name": "Fish and Game Code", "url": f"{base_url}/faces/codes.xhtml", "type": "FGC"},
            {"name": "Food and Agricultural Code", "url": f"{base_url}/faces/codes.xhtml", "type": "FAC"},
            {"name": "Government Code", "url": f"{base_url}/faces/codes.xhtml", "type": "GOV"},
            {"name": "Harbors and Navigation Code", "url": f"{base_url}/faces/codes.xhtml", "type": "HNC"},
            {"name": "Health and Safety Code", "url": f"{base_url}/faces/codes.xhtml", "type": "HSC"},
            {"name": "Insurance Code", "url": f"{base_url}/faces/codes.xhtml", "type": "INS"},
            {"name": "Labor Code", "url": f"{base_url}/faces/codes.xhtml", "type": "LAB"},
            {"name": "Military and Veterans Code", "url": f"{base_url}/faces/codes.xhtml", "type": "MVC"},
            {"name": "Penal Code", "url": f"{base_url}/faces/codes.xhtml", "type": "PEN"},
            {"name": "Probate Code", "url": f"{base_url}/faces/codes.xhtml", "type": "PROB"},
            {"name": "Public Contract Code", "url": f"{base_url}/faces/codes.xhtml", "type": "PCC"},
            {"name": "Public Resources Code", "url": f"{base_url}/faces/codes.xhtml", "type": "PRC"},
            {"name": "Public Utilities Code", "url": f"{base_url}/faces/codes.xhtml", "type": "PUC"},
            {"name": "Revenue and Taxation Code", "url": f"{base_url}/faces/codes.xhtml", "type": "RTC"},
            {"name": "Streets and Highways Code", "url": f"{base_url}/faces/codes.xhtml", "type": "SHC"},
            {"name": "Unemployment Insurance Code", "url": f"{base_url}/faces/codes.xhtml", "type": "UIC"},
            {"name": "Vehicle Code", "url": f"{base_url}/faces/codes.xhtml", "type": "VEH"},
            {"name": "Water Code", "url": f"{base_url}/faces/codes.xhtml", "type": "WAT"},
            {"name": "Welfare and Institutions Code", "url": f"{base_url}/faces/codes.xhtml", "type": "WIC"},
        ]
        
        return codes
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific California code using unified scraper.
        
        CHANGES FROM ORIGINAL:
        - Now async (await)
        - Uses self.get_soup() instead of requests.get() + BeautifulSoup
        - Automatic content addressing and caching
        - Multi-source fallback
        
        Args:
            code_name: Name of the code (e.g., "Penal Code")
            code_url: URL to the code
            
        Returns:
            List of normalized statutes
        """
        statutes = []
        
        try:
            # OLD: response = requests.get(code_url, headers=headers, timeout=30)
            # OLD: soup = BeautifulSoup(response.content, 'html.parser')
            
            # NEW: Use unified scraper via StateScraperMixin
            soup = await self.get_soup(code_url)
            
            if not soup:
                self.logger.error(f"Failed to fetch {code_url}")
                return []
            
            # Rest of parsing logic is UNCHANGED
            # Parse the page to find sections
            legal_area = self._identify_legal_area(code_name)
            
            # Find all section links
            section_links = soup.find_all('a', href=re.compile(r'.*section.*', re.IGNORECASE))
            if not section_links:
                section_links = soup.find_all('a', href=True, limit=100)
            
            # NEW: If we have many sections, scrape them in parallel
            if len(section_links) > 10:
                statutes = await self._scrape_sections_parallel(
                    section_links[:100],
                    code_name,
                    code_url,
                    legal_area
                )
            else:
                # Sequential for small numbers
                for i, link in enumerate(section_links[:100]):
                    statute = await self._scrape_section(
                        link, i, code_name, code_url, legal_area
                    )
                    if statute:
                        statutes.append(statute)
            
            self.logger.info(f"Scraped {len(statutes)} sections from {code_name}")
            
        except Exception as e:
            self.logger.error(f"Failed to scrape {code_name}: {e}")
        
        return statutes
    
    async def _scrape_section(
        self,
        link,
        index: int,
        code_name: str,
        code_url: str,
        legal_area: Optional[str]
    ) -> Optional[NormalizedStatute]:
        """Scrape a single section."""
        section_text = link.get_text(strip=True)
        section_url = link.get('href', '')
        
        if not section_text or len(section_text) < 3:
            return None
        
        if not section_url.startswith('http'):
            from urllib.parse import urljoin
            section_url = urljoin(code_url, section_url)
        
        # Extract section number
        section_number = self._extract_section_number(section_text)
        if not section_number:
            section_number = f"{index+1}"
        
        # NEW: Could optionally fetch full text of section
        # section_html = await self.get_html(section_url)
        # But for demo, we keep it simple
        
        statute = NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=section_text[:200],
            full_text=f"Section {section_number}: {section_text}",
            source_url=section_url,
            legal_area=legal_area,
            official_cite=f"Cal. {code_name} § {section_number}",
            metadata=StatuteMetadata()
        )
        
        return statute
    
    async def _scrape_sections_parallel(
        self,
        section_links: List,
        code_name: str,
        code_url: str,
        legal_area: Optional[str]
    ) -> List[NormalizedStatute]:
        """Scrape multiple sections in parallel using unified scraper.
        
        This is NEW functionality enabled by the unified scraper.
        """
        import asyncio
        
        tasks = [
            self._scrape_section(link, i, code_name, code_url, legal_area)
            for i, link in enumerate(section_links)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out errors and None values
        statutes = [
            r for r in results
            if r is not None and not isinstance(r, Exception)
        ]
        
        return statutes


# Register the migrated scraper
# In production, this would replace the old one
StateScraperRegistry.register("CA_UNIFIED", CaliforniaScraperUnified)


# Example usage comparison:
"""
OLD WAY (synchronous, no caching):
    scraper = CaliforniaScraper()
    statutes = scraper.scrape_code("Penal Code", url)
    # Takes 5-10 seconds, no deduplication

NEW WAY (async, cached, multi-source):
    scraper = CaliforniaScraperUnified()
    statutes = await scraper.scrape_code("Penal Code", url)
    # First time: 3-5 seconds (tries Common Crawl first)
    # Second time: Instant (cached with CID)
    # Parallel: All 29 codes in ~30 seconds total
"""
