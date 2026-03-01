"""New York state law scraper.

Scrapes laws from the New York State Senate website
(https://www.nysenate.gov/).
"""

from typing import List, Dict
import re
from urllib.parse import urljoin
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class NewYorkScraper(BaseStateScraper):
    """Scraper for New York state laws."""
    
    def get_base_url(self) -> str:
        """Get base URL for NY Senate."""
        return "https://www.nysenate.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Get list of New York consolidated law sources.

        In this environment, direct per-code NY Senate endpoints are often blocked.
        Use a single consolidated entry and let scrape_code choose the best source.
        """
        base_url = self.get_base_url()

        return [
            {
                "name": "New York Consolidated Laws",
                "url": f"{base_url}/legislation/laws",
                "type": "NY-LAWS",
            }
        ]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific New York law.
        
        Args:
            code_name: Name of the law
            code_url: URL to the law
            
        Returns:
            List of normalized statutes
        """
        try:
            import requests
            from bs4 import BeautifulSoup
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []
        
        statutes = []
        
        try:
            headers = {
                'User-Agent': (
                    'Mozilla/5.0 (X11; Linux x86_64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/124.0.0.0 Safari/537.36'
                ),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': self.get_base_url(),
                'Connection': 'keep-alive',
            }

            session = requests.Session()
            session.headers.update(headers)
            response = session.get(code_url, timeout=30, allow_redirects=True)

            if int(response.status_code) in {401, 403}:
                self.logger.warning(
                    f"NY direct request blocked ({response.status_code}) for {code_name}; using public.law fallback"
                )
                return await self._scrape_public_law_updates(code_name)

            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract legal area
            legal_area = self._identify_legal_area(code_name)

            # Find section/article links from the index page if available.
            section_href_re = re.compile(r".*/legislation/laws/[A-Za-z0-9\-.]+/[A-Za-z0-9\-.]+$", re.IGNORECASE)
            section_links = soup.find_all('a', href=section_href_re)
            
            seen_sections = set()
            for link in section_links[:120]:
                section_text = link.get_text(strip=True)
                section_url = link.get('href', '')
                
                if not section_text or len(section_text) < 3:
                    continue
                
                if not section_url.startswith('http'):
                    section_url = urljoin(code_url, section_url)
                
                # Extract section number
                section_number = self._extract_section_number(section_text)
                if not section_number:
                    tail = section_url.rstrip('/').split('/')[-1]
                    section_number = tail if re.search(r"\d", tail) else ""
                if not section_number:
                    continue
                if section_number in seen_sections:
                    continue
                seen_sections.add(section_number)
                
                statute = NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_text[:200],
                    full_text=f"Section {section_number}: {section_text}",  # Added full_text
                    source_url=section_url,
                    legal_area=legal_area,
                    official_cite=f"NY {code_name} § {section_number}",
                    metadata=StatuteMetadata()
                )
                
                statutes.append(statute)
            
            self.logger.info(f"Scraped {len(statutes)} sections from {code_name}")

            if statutes:
                return statutes

            self.logger.warning("NY primary source returned no sections; using public.law fallback")
            return await self._scrape_public_law_updates(code_name)
            
        except Exception as e:
            self.logger.error(f"Failed to scrape {code_name}: {e}")
            return await self._scrape_public_law_updates(code_name)

    async def _scrape_public_law_updates(
        self,
        code_name: str,
        max_sections: int = 120,
    ) -> List[NormalizedStatute]:
        """Fallback scraper using the newyork.public.law latest-updates index.

        This source is accessible in environments where NY Senate pages are blocked.
        """
        try:
            import requests
            from bs4 import BeautifulSoup
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []

        headers = {
            'User-Agent': (
                'Mozilla/5.0 (X11; Linux x86_64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            ),
        }

        base = "https://newyork.public.law"
        seed_pages = [
            f"{base}/laws/latest-updates",
            f"{base}/laws/latest-updates?page=2",
            f"{base}/laws/latest-updates?page=3",
            f"{base}/laws/latest-updates?page=4",
        ]

        statutes: List[NormalizedStatute] = []
        seen_urls = set()
        legal_area = self._identify_legal_area(code_name)
        section_url_re = re.compile(r"/laws/n\.y\._[a-z0-9_'.\-,]+_(section|article|title)_[a-z0-9\-.]+$", re.IGNORECASE)

        for page_url in seed_pages:
            if len(statutes) >= max_sections:
                break
            try:
                response = requests.get(page_url, headers=headers, timeout=30, allow_redirects=True)
                response.raise_for_status()
            except Exception as exc:
                self.logger.warning(f"NY fallback page failed {page_url}: {exc}")
                continue

            soup = BeautifulSoup(response.content, 'html.parser')
            for link in soup.find_all('a', href=True):
                if len(statutes) >= max_sections:
                    break

                href = link.get('href', '').strip()
                if not href:
                    continue

                full_url = urljoin(base, href)
                if full_url in seen_urls:
                    continue
                if not section_url_re.search(full_url):
                    continue
                seen_urls.add(full_url)

                link_text = link.get_text(' ', strip=True)
                section_number = self._extract_section_number(link_text)
                if not section_number:
                    tail = full_url.rstrip('/').split('/')[-1]
                    # Keep the terminal identifier as a stable fallback.
                    section_number = re.sub(r"^.*_(section|article|title)_", "", tail, flags=re.IGNORECASE)

                section_name = link_text[:200] if link_text else f"Section {section_number}"
                statutes.append(
                    NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § {section_number}",
                        code_name=code_name,
                        section_number=section_number,
                        section_name=section_name,
                        full_text=f"Section {section_number}: {section_name}",
                        source_url=full_url,
                        legal_area=legal_area,
                        official_cite=f"NY {code_name} § {section_number}",
                        metadata=StatuteMetadata(),
                    )
                )

        self.logger.info(f"NY fallback scraper collected {len(statutes)} sections")
        return statutes


# Register the scraper
StateScraperRegistry.register("NY", NewYorkScraper)
