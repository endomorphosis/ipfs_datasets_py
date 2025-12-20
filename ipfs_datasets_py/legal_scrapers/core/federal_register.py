#!/usr/bin/env python3
"""
Federal Register Scraper - Core Implementation

Scrapes documents from the Federal Register (federalregister.gov).
Includes rules, proposed rules, notices, and presidential documents.
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta

from .base_scraper import BaseLegalScraper

logger = logging.getLogger(__name__)


class FederalRegisterScraper(BaseLegalScraper):
    """
    Scraper for Federal Register documents.
    
    Supports:
    - Final rules
    - Proposed rules
    - Notices
    - Presidential documents
    - Search by date, agency, topic
    """
    
    BASE_URL = "https://www.federalregister.gov"
    API_URL = "https://www.federalregister.gov/api/v1"
    
    DOCUMENT_TYPES = [
        "RULE",
        "PRORULE",  # Proposed rule
        "NOTICE",
        "PRESDOCU"  # Presidential document
    ]
    
    def get_scraper_name(self) -> str:
        """Return scraper identifier."""
        return "federal_register"
    
    async def scrape(
        self,
        document_number: str = None,
        url: str = None,
        date: str = None,
        agency: str = None,
        document_type: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Scrape Federal Register document(s).
        
        Args:
            document_number: Specific document number (e.g., "2024-12345")
            url: Direct URL to document
            date: Date to scrape (YYYY-MM-DD)
            agency: Filter by agency
            document_type: Filter by type (RULE, PRORULE, NOTICE, PRESDOCU)
            **kwargs: Additional arguments
            
        Returns:
            Dict with scraped content and metadata
        """
        try:
            # Determine target URL
            if url:
                target_url = url
            elif document_number:
                target_url = f"{self.BASE_URL}/documents/{document_number}"
            elif date:
                target_url = f"{self.API_URL}/documents.json?conditions[publication_date]={date}"
                if agency:
                    target_url += f"&conditions[agencies][]={agency}"
                if document_type:
                    target_url += f"&conditions[type][]={document_type}"
            else:
                # Default to today's documents
                today = datetime.now().strftime("%Y-%m-%d")
                target_url = f"{self.API_URL}/documents.json?conditions[publication_date]={today}"
            
            logger.info(f"Scraping Federal Register: {target_url}")
            
            # Scrape using unified system
            metadata = {
                "scraper": self.get_scraper_name(),
                "document_number": document_number,
                "date": date,
                "agency": agency,
                "document_type": document_type,
                "type": "federal_register"
            }
            
            result = await self.scrape_url_unified(target_url, metadata)
            
            # Parse content
            if result['status'] == 'success':
                parsed = await self._parse_federal_register(result['content'])
                result.update(parsed)
            
            return result
        
        except Exception as e:
            logger.error(f"Error scraping Federal Register: {e}")
            return {
                "status": "error",
                "error": str(e),
                "document_number": document_number,
                "url": url
            }
    
    async def scrape_date_range(
        self,
        start_date: str,
        end_date: str,
        agency: str = None,
        document_type: str = None,
        max_concurrent: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Scrape documents from a date range.
        
        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            agency: Filter by agency
            document_type: Filter by document type
            max_concurrent: Max concurrent requests
            
        Returns:
            List of scrape results
        """
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        
        dates = []
        current = start
        while current <= end:
            dates.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)
        
        logger.info(f"Scraping {len(dates)} days of Federal Register documents")
        
        results = []
        for date in dates:
            result = await self.scrape(
                date=date,
                agency=agency,
                document_type=document_type
            )
            results.append(result)
        
        return results
    
    async def scrape_by_agency(
        self,
        agency: str,
        days_back: int = 30,
        max_concurrent: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Scrape recent documents from a specific agency.
        
        Args:
            agency: Agency name or code
            days_back: Number of days to look back
            max_concurrent: Max concurrent requests
            
        Returns:
            List of scrape results
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        
        return await self.scrape_date_range(
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
            agency=agency,
            max_concurrent=max_concurrent
        )
    
    async def _parse_federal_register(
        self,
        content: Any
    ) -> Dict[str, Any]:
        """
        Parse Federal Register content.
        
        Args:
            content: Raw content (HTML or JSON)
            
        Returns:
            Parsed data dict
        """
        if isinstance(content, bytes):
            content_str = content.decode('utf-8', errors='ignore')
        else:
            content_str = str(content)
        
        # Try to parse as JSON (from API)
        try:
            import json
            data = json.loads(content_str)
            
            if 'results' in data:
                # Multiple documents
                return {
                    "document_count": len(data['results']),
                    "documents": data['results'],
                    "parsed": True,
                    "format": "json"
                }
            elif 'document_number' in data:
                # Single document
                return {
                    "document_number": data.get('document_number'),
                    "title": data.get('title'),
                    "agency_names": data.get('agency_names', []),
                    "type": data.get('type'),
                    "publication_date": data.get('publication_date'),
                    "abstract": data.get('abstract'),
                    "full_text_xml_url": data.get('full_text_xml_url'),
                    "html_url": data.get('html_url'),
                    "pdf_url": data.get('pdf_url'),
                    "parsed": True,
                    "format": "json"
                }
        except:
            pass
        
        # HTML parsing fallback
        return {
            "content_length": len(content_str),
            "parsed": False,
            "format": "html",
            # Would add HTML parsing here
        }


# Convenience function
def scrape_federal_register(
    document_number: str = None,
    url: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Sync wrapper for Federal Register scraping.
    
    Args:
        document_number: Document number
        url: Direct URL
        **kwargs: Additional arguments
        
    Returns:
        Scrape result
    """
    import asyncio
    scraper = FederalRegisterScraper()
    return asyncio.run(scraper.scrape(document_number=document_number, url=url, **kwargs))


if __name__ == "__main__":
    # Test
    result = scrape_federal_register(date=datetime.now().strftime("%Y-%m-%d"))
    print(f"Status: {result.get('status')}")
    print(f"Document count: {result.get('document_count', 'N/A')}")
