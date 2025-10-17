"""Scraper for Alabama state laws.

This module contains the scraper for Alabama statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class AlabamaScraper(BaseStateScraper):
    """Scraper for Alabama state laws from http://alisondb.legislature.state.al.us"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Alabama's legislative website."""
        return "http://alisondb.legislature.state.al.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Alabama."""
        return [{
            "name": "Alabama Code",
            "url": f"{self.get_base_url()}/alison/CodeOfAlabama/1975/coatoc.htm",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Alabama's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        # Use custom scraper with Alabama-specific patterns
        return await self._custom_scrape_alabama(code_name, code_url, "Ala. Code")
    
    async def _custom_scrape_alabama(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 100
    ) -> List[NormalizedStatute]:
        """Custom scraper for Alabama's legislative website.
        
        Alabama uses a nested table of contents structure with titles and chapters.
        This method handles the specific HTML structure of alisondb.legislature.state.al.us
        
        Expected HTML structure:
        - Links with patterns like "Title X", "Chapter Y", "Section Z"
        - Nested TOC with titles containing multiple chapters
        
        Example valid links:
        - "Title 13A - Criminal Code"
        - "Chapter 6 - Homicide"
        - "Section 13A-6-2 - Murder"
        """
        self.logger.info(f"Alabama: Starting custom scrape for {code_name}")
        self.logger.info(f"Alabama: Accessing URL: {code_url}")
        
        try:
            import requests
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError as e:
            self.logger.error(f"Alabama: Required library not available: {e}")
            self.logger.error("Alabama: Install required packages: pip install requests beautifulsoup4")
            return []
        
        statutes = []
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            self.logger.info(f"Alabama: Fetching page with timeout=30s")
            response = requests.get(code_url, headers=headers, timeout=30)
            response.raise_for_status()
            self.logger.info(f"Alabama: Response status code: {response.status_code}")
            self.logger.info(f"Alabama: Response content length: {len(response.content)} bytes")
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find all links that look like title or chapter links
            # Alabama's TOC typically has links in specific patterns
            links = soup.find_all('a', href=True)
            self.logger.info(f"Alabama: Found {len(links)} total links on page")
            
            # Alabama-specific keywords (more permissive)
            keywords = ['title', 'section', 'chapter', '§', 'article', 'code', 'statute', 'part', 'division']
            
            section_count = 0
            skipped_short = 0
            skipped_no_keywords = 0
            
            for link in links:
                if section_count >= max_sections:
                    self.logger.info(f"Alabama: Reached max_sections limit ({max_sections})")
                    break
                
                link_text = link.get_text(strip=True)
                link_href = link.get('href', '')
                
                # Skip empty or very short links
                if not link_text or len(link_text) < 5:
                    skipped_short += 1
                    continue
                
                # Look for title or section patterns - relaxed to catch more links
                if not any(keyword in link_text.lower() for keyword in keywords):
                    skipped_no_keywords += 1
                    self.logger.debug(f"Alabama: Skipped (no keywords): '{link_text[:50]}'")
                    continue
                
                # Make URL absolute
                full_url = urljoin(code_url, link_href)
                
                # Extract section number
                section_number = self._extract_section_number(link_text)
                if not section_number:
                    section_number = f"Section-{section_count + 1}"
                
                # Identify legal area from link text
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
                self.logger.debug(f"Alabama: Accepted ({section_count}): '{link_text[:50]}'")
            
            self.logger.info(f"Alabama: Filtering stats - Short: {skipped_short}, No keywords: {skipped_no_keywords}, Accepted: {len(statutes)}")
            self.logger.info(f"Alabama: Custom scraper completed with {len(statutes)} statutes")
            
            if not statutes:
                # If custom scraper found nothing, try generic scraper as fallback
                self.logger.warning("Alabama: Custom scraper found no data!")
                self.logger.info("Alabama: Falling back to generic scraper")
                return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
            
            return statutes
            
        except requests.exceptions.Timeout:
            self.logger.error(f"Alabama: Request timeout after 30s for URL: {code_url}")
            self.logger.info("Alabama: Attempting generic scraper fallback")
            return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"Alabama: HTTP error {e.response.status_code}: {e}")
            self.logger.info("Alabama: Attempting generic scraper fallback")
            return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Alabama: Request failed: {e}")
            self.logger.info("Alabama: Attempting generic scraper fallback")
            return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
        except Exception as e:
            self.logger.error(f"Alabama: Unexpected error in custom scraper: {type(e).__name__}: {e}")
            self.logger.exception("Alabama: Full traceback:")
            # Fallback to generic scraper
            self.logger.info("Alabama: Attempting generic scraper fallback")
            return await self._generic_scraper(code_name, code_url, citation_format, max_sections)


# Register this scraper with the registry
StateScraperRegistry.register("AL", AlabamaScraper)
