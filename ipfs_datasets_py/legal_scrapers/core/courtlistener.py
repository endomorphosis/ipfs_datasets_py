"""
CourtListener API scraper for federal and state court documents.

CourtListener is a comprehensive free legal database covering:
- Federal courts (District, Appellate, Supreme Court)
- State courts (Supreme, Appellate, Trial)
- RECAP Archive (PACER documents)
- Oral arguments audio
- Judicial data and citations

API Documentation: https://www.courtlistener.com/api/rest-info/
"""

import logging
import time
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

# Court types
COURT_TYPES = {
    "district": "U.S. District Courts",
    "appellate": "U.S. Courts of Appeals",
    "bankruptcy": "U.S. Bankruptcy Courts",
    "supreme": "U.S. Supreme Court",
    "state_supreme": "State Supreme Courts",
    "state_appellate": "State Appellate Courts",
    "specialty": "U.S. Specialty Courts"
}

# Federal circuits
FEDERAL_CIRCUITS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "dc", "fed"]


class CourtListenerScraper:
    """
    Scraper for CourtListener API with comprehensive court document access.
    
    Features:
    - Opinion search across all courts
    - RECAP archive (PACER documents)
    - Docket search
    - Oral argument audio
    - Judge information
    - Citation resolution
    """
    
    def __init__(self,
                 api_token: Optional[str] = None,
                 rate_limit_delay: float = 1.0,
                 max_results: int = 1000):
        """
        Initialize CourtListener scraper.
        
        Args:
            api_token: Optional API token for authenticated requests
            rate_limit_delay: Delay between requests (seconds)
            max_results: Maximum results per query
        """
        self.base_url = "https://www.courtlistener.com/api/rest/v3"
        self.api_token = api_token
        self.rate_limit_delay = rate_limit_delay
        self.max_results = max_results
        
        self.headers = {}
        if api_token:
            self.headers["Authorization"] = f"Token {api_token}"
        
        logger.info(f"CourtListenerScraper initialized (authenticated={bool(api_token)})")
    
    async def search_opinions(self,
                             query: Optional[str] = None,
                             court_type: Optional[str] = None,
                             start_date: Optional[str] = None,
                             end_date: Optional[str] = None,
                             citation: Optional[str] = None,
                             case_name: Optional[str] = None,
                             judge: Optional[str] = None,
                             limit: int = 100) -> Dict[str, Any]:
        """
        Search court opinions.
        
        Args:
            query: Free text search query
            court_type: Court type filter (supreme, appellate, district, etc.)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            citation: Citation to search for
            case_name: Case name
            judge: Judge name
            limit: Max results to return
        
        Returns:
            Dict with results and metadata
        """
        logger.info(f"Searching opinions: query={query}, court={court_type}")
        
        params = {"format": "json"}
        
        if query:
            params["q"] = query
        if court_type:
            params["court"] = court_type
        if start_date:
            params["filed_after"] = start_date
        if end_date:
            params["filed_before"] = end_date
        if citation:
            params["citation"] = citation
        if case_name:
            params["case_name"] = case_name
        if judge:
            params["judge"] = judge
        
        # Pagination
        params["limit"] = min(limit, self.max_results)
        
        try:
            # Simulate API call - replace with actual HTTP request
            await asyncio.sleep(self.rate_limit_delay)
            
            # TODO: Implement actual HTTP request
            # For now, return mock structure
            return {
                "success": True,
                "count": 0,
                "results": [],
                "query": params,
                "endpoint": "opinions"
            }
        except Exception as e:
            logger.error(f"Error searching opinions: {e}")
            return {
                "success": False,
                "error": str(e),
                "query": params
            }
    
    async def search_dockets(self,
                            case_name: Optional[str] = None,
                            docket_number: Optional[str] = None,
                            court: Optional[str] = None,
                            start_date: Optional[str] = None,
                            end_date: Optional[str] = None,
                            limit: int = 100) -> Dict[str, Any]:
        """
        Search RECAP/PACER dockets.
        
        Args:
            case_name: Case name to search
            docket_number: Docket number
            court: Court identifier
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            limit: Max results
        
        Returns:
            Dict with docket results
        """
        logger.info(f"Searching dockets: case={case_name}, docket={docket_number}")
        
        params = {"format": "json"}
        
        if case_name:
            params["case_name"] = case_name
        if docket_number:
            params["docket_number"] = docket_number
        if court:
            params["court"] = court
        if start_date:
            params["date_filed_after"] = start_date
        if end_date:
            params["date_filed_before"] = end_date
        
        params["limit"] = min(limit, self.max_results)
        
        try:
            await asyncio.sleep(self.rate_limit_delay)
            
            # TODO: Implement actual HTTP request
            return {
                "success": True,
                "count": 0,
                "results": [],
                "query": params,
                "endpoint": "dockets"
            }
        except Exception as e:
            logger.error(f"Error searching dockets: {e}")
            return {
                "success": False,
                "error": str(e),
                "query": params
            }
    
    async def resolve_citation(self, citation: str) -> Dict[str, Any]:
        """
        Resolve a legal citation to CourtListener documents.
        
        Args:
            citation: Citation string (e.g., "123 S.Ct. 456", "123 F.3d 456")
        
        Returns:
            Dict with resolved documents
        """
        logger.info(f"Resolving citation: {citation}")
        
        # Use opinions search with citation
        return await self.search_opinions(citation=citation, limit=10)
    
    async def get_oral_arguments(self,
                                court: Optional[str] = None,
                                case_name: Optional[str] = None,
                                start_date: Optional[str] = None,
                                end_date: Optional[str] = None,
                                limit: int = 100) -> Dict[str, Any]:
        """
        Search oral argument audio recordings.
        
        Args:
            court: Court identifier
            case_name: Case name
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            limit: Max results
        
        Returns:
            Dict with oral argument results
        """
        logger.info(f"Searching oral arguments: court={court}, case={case_name}")
        
        params = {"format": "json"}
        
        if court:
            params["panel__docket__court"] = court
        if case_name:
            params["case_name"] = case_name
        if start_date:
            params["date_argued_after"] = start_date
        if end_date:
            params["date_argued_before"] = end_date
        
        params["limit"] = min(limit, self.max_results)
        
        try:
            await asyncio.sleep(self.rate_limit_delay)
            
            # TODO: Implement actual HTTP request
            return {
                "success": True,
                "count": 0,
                "results": [],
                "query": params,
                "endpoint": "audio"
            }
        except Exception as e:
            logger.error(f"Error searching oral arguments: {e}")
            return {
                "success": False,
                "error": str(e),
                "query": params
            }
    
    async def get_supreme_court_opinions(self,
                                        term: Optional[str] = None,
                                        start_date: Optional[str] = None,
                                        end_date: Optional[str] = None,
                                        limit: int = 100) -> Dict[str, Any]:
        """
        Get U.S. Supreme Court opinions.
        
        Args:
            term: Court term (e.g., "2023")
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            limit: Max results
        
        Returns:
            Dict with Supreme Court opinions
        """
        logger.info(f"Getting Supreme Court opinions: term={term}")
        
        return await self.search_opinions(
            court_type="supreme",
            start_date=start_date,
            end_date=end_date,
            limit=limit
        )
    
    async def get_circuit_court_opinions(self,
                                        circuit: str,
                                        start_date: Optional[str] = None,
                                        end_date: Optional[str] = None,
                                        limit: int = 100) -> Dict[str, Any]:
        """
        Get U.S. Circuit Court of Appeals opinions.
        
        Args:
            circuit: Circuit number (1-11, dc, fed)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            limit: Max results
        
        Returns:
            Dict with circuit court opinions
        """
        if circuit.lower() not in FEDERAL_CIRCUITS:
            return {
                "success": False,
                "error": f"Invalid circuit: {circuit}. Must be one of {FEDERAL_CIRCUITS}"
            }
        
        logger.info(f"Getting Circuit Court opinions: circuit={circuit}")
        
        return await self.search_opinions(
            court_type="appellate",
            query=f"court_id:ca{circuit}",
            start_date=start_date,
            end_date=end_date,
            limit=limit
        )


# Convenience functions for package-level imports
async def search_opinions(**kwargs) -> Dict[str, Any]:
    """Search CourtListener opinions."""
    scraper = CourtListenerScraper()
    return await scraper.search_opinions(**kwargs)


async def resolve_citation(citation: str) -> Dict[str, Any]:
    """Resolve a legal citation using CourtListener."""
    scraper = CourtListenerScraper()
    return await scraper.resolve_citation(citation)


async def get_supreme_court_opinions(**kwargs) -> Dict[str, Any]:
    """Get U.S. Supreme Court opinions."""
    scraper = CourtListenerScraper()
    return await scraper.get_supreme_court_opinions(**kwargs)


async def get_circuit_court_opinions(circuit: str, **kwargs) -> Dict[str, Any]:
    """Get federal circuit court opinions."""
    scraper = CourtListenerScraper()
    return await scraper.get_circuit_court_opinions(circuit, **kwargs)
