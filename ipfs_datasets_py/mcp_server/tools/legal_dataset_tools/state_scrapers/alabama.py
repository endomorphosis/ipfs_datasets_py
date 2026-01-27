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
        
        Alabama's website uses framesets and may not be accessible directly.
        This scraper uses multiple fallback strategies:
        1. Try Internet Archive
        2. Parse frameset to extract actual content URLs
        3. Use generic fallback scraper
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
        
        # Alabama's site is often down or blocked, use Internet Archive
        # Try to get an archived version first
        archive_urls_to_try = [
            "http://web.archive.org/web/20240123221654/http://alisondb.legislature.state.al.us/alison/CodeOfAlabama/1975/title.htm",
            "http://web.archive.org/web/20231201000000*/http://alisondb.legislature.state.al.us/alison/CodeOfAlabama/1975/title.htm",
            code_url  # Try original as last resort
        ]
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # Try each URL until one works
        for attempt_url in archive_urls_to_try:
            try:
                self.logger.info(f"Alabama: Attempting to fetch from: {attempt_url}")
                response = requests.get(attempt_url, headers=headers, timeout=30)
                response.raise_for_status()
                self.logger.info(f"Alabama: Success! Status code: {response.status_code}")
                self.logger.info(f"Alabama: Content length: {len(response.content)} bytes")
                
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Check if this is a frameset page
                frames = soup.find_all('frame', src=True)
                if frames:
                    self.logger.info(f"Alabama: Found {len(frames)} frames, extracting frame URLs")
                    for frame in frames:
                        frame_src = frame.get('src')
                        if frame_src and 'title.htm' in frame_src.lower():
                            # This is likely the TOC frame
                            frame_url = urljoin(attempt_url, frame_src)
                            self.logger.info(f"Alabama: Fetching TOC frame: {frame_url}")
                            try:
                                frame_response = requests.get(frame_url, headers=headers, timeout=30)
                                if frame_response.status_code == 200:
                                    soup = BeautifulSoup(frame_response.content, 'html.parser')
                                    self.logger.info(f"Alabama: Successfully loaded TOC frame")
                                    break
                            except Exception as frame_error:
                                self.logger.warning(f"Alabama: Failed to load frame: {frame_error}")
                                continue
                
                # Find all links that look like title or chapter links
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
                self.logger.info(f"Alabama: Custom scraper completed with {len(statutes)} statutes from {attempt_url}")
                
                # If we got results, return them
                if statutes:
                    return statutes
                else:
                    self.logger.warning(f"Alabama: No statutes found with {attempt_url}, trying next URL")
                    
            except requests.exceptions.Timeout as e:
                self.logger.warning(f"Alabama: Timeout for {attempt_url}: {e}")
                continue
            except requests.exceptions.HTTPError as e:
                self.logger.warning(f"Alabama: HTTP error for {attempt_url}: {e}")
                continue
            except requests.exceptions.RequestException as e:
                self.logger.warning(f"Alabama: Request failed for {attempt_url}: {e}")
                continue
            except Exception as e:
                self.logger.warning(f"Alabama: Error with {attempt_url}: {type(e).__name__}: {e}")
                continue
        
        # If all URLs failed, try generic scraper as last resort
        self.logger.warning("Alabama: All URL attempts failed")
        self.logger.info("Alabama: Site likely down. Recommendations:")
        self.logger.info("  1. Check https://web.archive.org for archived versions")
        self.logger.info("  2. Try again later when site is accessible")
        self.logger.info("  3. Contact Alabama Legislative Services")
        return await self._generic_scrape(code_name, code_url, citation_format, max_sections=max_sections)


# Register this scraper with the registry
StateScraperRegistry.register("AL", AlabamaScraper)
