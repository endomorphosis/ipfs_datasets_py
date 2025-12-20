#!/usr/bin/env python3
"""
Municode Scraper - Core Implementation

Scrapes municipal codes from library.municode.com with:
- Unified scraping (content addressing, deduplication)
- WARC import/export
- Multi-interface support (package, CLI, MCP)
- 3,500+ jurisdictions supported
"""

import logging
import re
from typing import Dict, List, Any, Optional
from bs4 import BeautifulSoup

from .base_scraper import BaseLegalScraper

logger = logging.getLogger(__name__)


class MunicodeScraper(BaseLegalScraper):
    """
    Scraper for Municode library (library.municode.com).
    
    Municode provides municipal codes for 3,500+ jurisdictions in the US.
    
    Usage:
        # As package import
        scraper = MunicodeScraper(enable_ipfs=True, check_archives=True)
        result = await scraper.scrape("https://library.municode.com/wa/seattle")
        
        # Sync wrapper
        from legal_scrapers.core.base_scraper import run_async_scraper
        result = run_async_scraper(scraper.scrape(url))
    """
    
    def get_scraper_name(self) -> str:
        """Return scraper name."""
        return "municode"
    
    async def scrape(
        self,
        jurisdiction_url: str,
        include_metadata: bool = True,
        extract_sections: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Scrape a Municode jurisdiction.
        
        Args:
            jurisdiction_url: URL of the jurisdiction (e.g., "https://library.municode.com/wa/seattle")
            include_metadata: Include jurisdiction metadata
            extract_sections: Parse and extract code sections
            **kwargs: Additional options
            
        Returns:
            Dict containing:
                - jurisdiction_url: The scraped URL
                - jurisdiction_name: Name of jurisdiction
                - state: State code
                - sections: List of code sections (if extract_sections=True)
                - content_cid: Content identifier
                - metadata_cid: Metadata identifier
                - version: Version number
                - already_scraped: Whether this was already scraped
                - changed: Whether content changed from last version
                - status: "success", "cached", or "error"
        """
        logger.info(f"Scraping Municode jurisdiction: {jurisdiction_url}")
        
        # Scrape using unified system
        result = await self.scrape_url_unified(
            url=jurisdiction_url,
            metadata={
                "source": "municode",
                "jurisdiction_url": jurisdiction_url,
                "include_metadata": include_metadata,
                "extract_sections": extract_sections
            }
        )
        
        if result['status'] not in ['success', 'cached']:
            logger.error(f"Scraping failed: {result.get('error', 'Unknown error')}")
            return result
        
        # Parse HTML content
        try:
            html_content = result.get('content', b'')
            if isinstance(html_content, bytes):
                html_content = html_content.decode('utf-8', errors='ignore')
            
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Extract jurisdiction info
            jurisdiction_info = self._extract_jurisdiction_info(soup, jurisdiction_url)
            
            # Extract sections if requested
            sections = []
            if extract_sections:
                sections = self._extract_sections(soup)
            
            # Build complete result
            scrape_result = {
                "status": result['status'],
                "jurisdiction_url": jurisdiction_url,
                "jurisdiction_name": jurisdiction_info.get('name', 'Unknown'),
                "state": jurisdiction_info.get('state', 'Unknown'),
                "sections": sections,
                "section_count": len(sections),
                "content_cid": result.get('content_cid'),
                "metadata_cid": result.get('metadata_cid'),
                "version": result.get('version'),
                "already_scraped": result.get('already_scraped', False),
                "changed": result.get('changed', True),
                "scraped_at": result.get('scraped_at'),
            }
            
            # Add metadata if requested
            if include_metadata:
                scrape_result['metadata'] = jurisdiction_info
            
            # Add archive info if available
            if 'archive_results' in result:
                scrape_result['archive_results'] = result['archive_results']
            
            logger.info(f"✓ Scraped successfully: {jurisdiction_info.get('name')}")
            logger.info(f"  Content CID: {result.get('content_cid')}")
            logger.info(f"  Sections found: {len(sections)}")
            logger.info(f"  Already scraped: {result.get('already_scraped', False)}")
            
            return scrape_result
        
        except Exception as e:
            logger.error(f"Error parsing Municode content: {e}")
            return {
                "status": "error",
                "jurisdiction_url": jurisdiction_url,
                "error": f"Parsing failed: {str(e)}",
                "content_cid": result.get('content_cid'),
                "raw_result": result
            }
    
    async def scrape_multiple(
        self,
        jurisdiction_urls: List[str],
        max_concurrent: int = 5,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Scrape multiple Municode jurisdictions.
        
        Args:
            jurisdiction_urls: List of jurisdiction URLs
            max_concurrent: Maximum concurrent requests
            **kwargs: Additional options passed to scrape()
            
        Returns:
            List of scraping results
        """
        logger.info(f"Batch scraping {len(jurisdiction_urls)} Municode jurisdictions")
        
        results = []
        for i in range(0, len(jurisdiction_urls), max_concurrent):
            batch_urls = jurisdiction_urls[i:i + max_concurrent]
            
            # Scrape batch concurrently
            import asyncio
            tasks = [self.scrape(url, **kwargs) for url in batch_urls]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for url, result in zip(batch_urls, batch_results):
                if isinstance(result, Exception):
                    results.append({
                        "status": "error",
                        "jurisdiction_url": url,
                        "error": str(result)
                    })
                else:
                    results.append(result)
        
        success_count = sum(1 for r in results if r['status'] == 'success')
        cached_count = sum(1 for r in results if r['status'] == 'cached')
        error_count = sum(1 for r in results if r['status'] == 'error')
        
        logger.info(f"Batch scraping complete:")
        logger.info(f"  Success: {success_count}")
        logger.info(f"  Cached: {cached_count}")
        logger.info(f"  Errors: {error_count}")
        
        return results
    
    def _extract_jurisdiction_info(self, soup: BeautifulSoup, url: str) -> Dict[str, Any]:
        """
        Extract jurisdiction metadata from HTML.
        
        Args:
            soup: BeautifulSoup object
            url: Jurisdiction URL
            
        Returns:
            Dict with jurisdiction info
        """
        info = {}
        
        # Try to extract jurisdiction name from title
        title_tag = soup.find('title')
        if title_tag:
            title_text = title_tag.get_text()
            info['title'] = title_text
            
            # Extract name from title (usually format: "City of Seattle, WA Code of Ordinances")
            match = re.search(r'([^,]+),\s*([A-Z]{2})', title_text)
            if match:
                info['name'] = match.group(1).strip()
                info['state'] = match.group(2)
        
        # Extract from URL as fallback
        url_parts = url.split('/')
        if len(url_parts) >= 5:
            info['state'] = url_parts[3].upper() if 'state' not in info else info['state']
            info['name'] = url_parts[4].replace('_', ' ').title() if 'name' not in info else info['name']
        
        # Try to find more metadata from page
        meta_tags = soup.find_all('meta')
        for tag in meta_tags:
            if tag.get('name') == 'description':
                info['description'] = tag.get('content', '')
        
        return info
    
    def _extract_sections(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """
        Extract code sections from HTML.
        
        Args:
            soup: BeautifulSoup object
            
        Returns:
            List of sections with title, number, and content
        """
        sections = []
        
        # Try multiple selectors for different Municode page layouts
        section_selectors = [
            {'class': 'section'},
            {'class': 'code-section'},
            {'class': 'ordinance'},
            {'data-type': 'section'}
        ]
        
        for selector in section_selectors:
            section_elements = soup.find_all(**selector)
            if section_elements:
                logger.debug(f"Found {len(section_elements)} sections with selector {selector}")
                
                for elem in section_elements:
                    section = self._parse_section(elem)
                    if section:
                        sections.append(section)
                
                break  # Use first selector that finds sections
        
        # Fallback: try to find sections by heading tags
        if not sections:
            logger.debug("Using fallback section detection")
            sections = self._extract_sections_fallback(soup)
        
        return sections
    
    def _parse_section(self, element) -> Optional[Dict[str, Any]]:
        """
        Parse a single code section element.
        
        Args:
            element: BeautifulSoup element
            
        Returns:
            Dict with section info or None
        """
        try:
            section = {}
            
            # Extract section number
            section_num = element.find(['span', 'div'], class_=re.compile('section-?num', re.I))
            if section_num:
                section['number'] = section_num.get_text().strip()
            
            # Extract section title/heading
            section_title = element.find(['h1', 'h2', 'h3', 'h4', 'span', 'div'], class_=re.compile('section-?title|heading', re.I))
            if section_title:
                section['title'] = section_title.get_text().strip()
            
            # Extract section content/text
            section_content = element.find(['div', 'p'], class_=re.compile('section-?content|text', re.I))
            if section_content:
                section['content'] = section_content.get_text().strip()
            else:
                # Fallback: use all text in element
                section['content'] = element.get_text().strip()
            
            # Only return if we got something useful
            if section.get('number') or section.get('title') or (section.get('content') and len(section['content']) > 50):
                return section
            
            return None
        
        except Exception as e:
            logger.debug(f"Error parsing section: {e}")
            return None
    
    def _extract_sections_fallback(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """
        Fallback method to extract sections using heading tags.
        
        Args:
            soup: BeautifulSoup object
            
        Returns:
            List of sections
        """
        sections = []
        
        # Find all headings
        headings = soup.find_all(['h1', 'h2', 'h3', 'h4'])
        
        for i, heading in enumerate(headings):
            section = {
                'title': heading.get_text().strip(),
                'level': heading.name
            }
            
            # Try to find section number in heading
            match = re.search(r'§?\s*(\d+[\.\-]\d+[\.\-]?\d*)', section['title'])
            if match:
                section['number'] = match.group(1)
            
            # Get content until next heading
            content_parts = []
            for sibling in heading.find_next_siblings():
                if sibling.name in ['h1', 'h2', 'h3', 'h4']:
                    break
                if sibling.name in ['p', 'div']:
                    content_parts.append(sibling.get_text().strip())
            
            if content_parts:
                section['content'] = '\n\n'.join(content_parts)
                sections.append(section)
        
        return sections


# Convenience function for sync usage
def scrape_municode(jurisdiction_url: str, **kwargs) -> Dict[str, Any]:
    """
    Convenience function to scrape Municode jurisdiction synchronously.
    
    Usage:
        result = scrape_municode("https://library.municode.com/wa/seattle")
    
    Args:
        jurisdiction_url: URL of jurisdiction to scrape
        **kwargs: Additional options
        
    Returns:
        Scraping result dict
    """
    from .base_scraper import run_async_scraper
    
    scraper = MunicodeScraper(**kwargs)
    return run_async_scraper(scraper.scrape(jurisdiction_url, **kwargs))


if __name__ == "__main__":
    # Test the scraper
    import asyncio
    logging.basicConfig(level=logging.INFO)
    
    async def test():
        print("Testing Municode scraper...")
        scraper = MunicodeScraper(check_archives=True)
        
        test_url = "https://library.municode.com/wa/seattle"
        result = await scraper.scrape(test_url)
        
        print(f"\nResult:")
        print(f"  Status: {result['status']}")
        print(f"  Jurisdiction: {result.get('jurisdiction_name', 'N/A')}")
        print(f"  Sections: {result.get('section_count', 0)}")
        print(f"  CID: {result.get('content_cid', 'N/A')}")
        print(f"  Already scraped: {result.get('already_scraped', False)}")
    
    asyncio.run(test())
