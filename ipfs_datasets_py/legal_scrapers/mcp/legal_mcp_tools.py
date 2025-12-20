#!/usr/bin/env python3
"""
Legal Dataset MCP Tools - Wrapper Layer

This module provides MCP tool wrappers that call the core legal scrapers.
All scraping logic lives in ipfs_datasets_py.legal_scrapers.core.

This ensures the same scraping functionality is available via:
- Package imports (ipfs_datasets_py.legal_scrapers.core)
- CLI tools (ipfs_datasets_py.legal_scrapers.cli)
- MCP server tools (this module)
"""

import logging
import asyncio
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

# Import core scrapers
try:
    from ..core.state_laws import StateLawsScraper
    from ..core.us_code import USCodeScraper
    from ..core.federal_register import FederalRegisterScraper
    from ..core.recap import RECAPScraper
    from ..core.municode import MunicodeScraper
    from ..core.ecode360 import ECode360Scraper
    HAVE_CORE_SCRAPERS = True
except ImportError as e:
    logger.error(f"Failed to import core scrapers: {e}")
    HAVE_CORE_SCRAPERS = False


async def scrape_state_laws(
    states: Optional[List[str]] = None,
    legal_areas: Optional[List[str]] = None,
    output_format: str = "json",
    include_metadata: bool = True,
    rate_limit_delay: float = 2.0,
    max_statutes: Optional[int] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    MCP Tool: Scrape state statutes and build a structured dataset.
    
    Args:
        states: List of state codes (e.g., ["CA", "NY", "TX"]). If None, scrapes all.
        legal_areas: Specific areas (e.g., ["criminal", "civil", "family"])
        output_format: Output format - "json" or "parquet"
        include_metadata: Include metadata (effective dates, amendments, etc.)
        rate_limit_delay: Delay between requests in seconds
        max_statutes: Maximum number of statutes to scrape
        **kwargs: Additional arguments
    
    Returns:
        Dict with status, data, and metadata
    """
    if not HAVE_CORE_SCRAPERS:
        return {
            "status": "error",
            "error": "Core scrapers not available. Check installation."
        }
    
    try:
        scraper = StateLawsScraper(
            cache_dir="./legal_scraper_cache/state_laws",
            enable_ipfs=kwargs.get("enable_ipfs", False),
            enable_warc=kwargs.get("enable_warc", True),
            check_archives=kwargs.get("check_archives", True),
            output_format=output_format
        )
        
        # Scrape each state
        results = []
        states_to_scrape = states if states and states != ["all"] else list(StateLawsScraper.STATE_URLS.keys())
        
        for state in states_to_scrape:
            try:
                result = await scraper.scrape(
                    state_code=state,
                    **kwargs
                )
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to scrape {state}: {e}")
                results.append({
                    "state": state,
                    "status": "error",
                    "error": str(e)
                })
        
        return {
            "status": "success",
            "results": results,
            "states_scraped": len(results),
            "output_format": output_format
        }
        
    except Exception as e:
        logger.error(f"State laws scraping failed: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


async def scrape_us_code(
    titles: Optional[List[int]] = None,
    sections: Optional[List[str]] = None,
    output_format: str = "json",
    include_metadata: bool = True,
    **kwargs
) -> Dict[str, Any]:
    """
    MCP Tool: Scrape United States Code.
    
    Args:
        titles: List of title numbers to scrape (e.g., [18, 42]). If None, scrapes all.
        sections: Specific sections within titles
        output_format: Output format - "json" or "parquet"
        include_metadata: Include metadata
        **kwargs: Additional arguments
    
    Returns:
        Dict with status, data, and metadata
    """
    if not HAVE_CORE_SCRAPERS:
        return {
            "status": "error",
            "error": "Core scrapers not available. Check installation."
        }
    
    try:
        scraper = USCodeScraper(
            cache_dir="./legal_scraper_cache/us_code",
            enable_ipfs=kwargs.get("enable_ipfs", False),
            enable_warc=kwargs.get("enable_warc", True),
            check_archives=kwargs.get("check_archives", True),
            output_format=output_format
        )
        
        results = []
        titles_to_scrape = titles if titles else list(USCodeScraper.TITLES.keys())
        
        for title in titles_to_scrape:
            try:
                result = await scraper.scrape(
                    title=title,
                    **kwargs
                )
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to scrape title {title}: {e}")
                results.append({
                    "title": title,
                    "status": "error",
                    "error": str(e)
                })
        
        return {
            "status": "success",
            "results": results,
            "titles_scraped": len(results),
            "output_format": output_format
        }
        
    except Exception as e:
        logger.error(f"US Code scraping failed: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


async def scrape_federal_register(
    agencies: Optional[List[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    document_types: Optional[List[str]] = None,
    keywords: Optional[str] = None,
    limit: int = 100,
    **kwargs
) -> Dict[str, Any]:
    """
    MCP Tool: Scrape Federal Register documents.
    
    Args:
        agencies: List of agency abbreviations (e.g., ["EPA", "FDA"])
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        document_types: Types of documents (e.g., ["RULE", "NOTICE"])
        keywords: Search keywords
        limit: Maximum number of results
        **kwargs: Additional arguments
    
    Returns:
        Dict with status, data, and metadata
    """
    if not HAVE_CORE_SCRAPERS:
        return {
            "status": "error",
            "error": "Core scrapers not available. Check installation."
        }
    
    try:
        scraper = FederalRegisterScraper(
            cache_dir="./legal_scraper_cache/federal_register",
            enable_ipfs=kwargs.get("enable_ipfs", False),
            enable_warc=kwargs.get("enable_warc", True),
            check_archives=kwargs.get("check_archives", True)
        )
        
        result = await scraper.scrape(
            agency=agencies[0] if agencies else None,
            date=start_date,
            document_type=document_types[0] if document_types else None,
            **kwargs
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Federal Register scraping failed: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


async def scrape_recap_documents(
    query: Optional[str] = None,
    court: Optional[str] = None,
    case_name: Optional[str] = None,
    filed_after: Optional[str] = None,
    filed_before: Optional[str] = None,
    document_type: Optional[str] = None,
    limit: int = 100,
    api_token: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    MCP Tool: Search RECAP Archive for court documents.
    
    Args:
        query: Text search query
        court: Court identifier (e.g., "ca9", "nysd")
        case_name: Case name to search for
        filed_after: Date filed after (YYYY-MM-DD)
        filed_before: Date filed before (YYYY-MM-DD)
        document_type: Type (opinion, docket, complaint)
        limit: Maximum number of results
        api_token: CourtListener API token
        **kwargs: Additional arguments
    
    Returns:
        Dict with status, data, and metadata
    """
    if not HAVE_CORE_SCRAPERS:
        return {
            "status": "error",
            "error": "Core scrapers not available. Check installation."
        }
    
    try:
        scraper = RECAPScraper(
            cache_dir="./legal_scraper_cache/recap",
            enable_ipfs=kwargs.get("enable_ipfs", False),
            enable_warc=kwargs.get("enable_warc", True),
            check_archives=kwargs.get("check_archives", True)
        )
        
        result = await scraper.scrape(
            query=query,
            court=court,
            case_name=case_name,
            filed_after=filed_after,
            filed_before=filed_before,
            document_type=document_type,
            limit=limit,
            api_token=api_token,
            **kwargs
        )
        
        return result
        
    except Exception as e:
        logger.error(f"RECAP scraping failed: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


async def scrape_municipal_codes(
    provider: str,
    jurisdiction: str,
    **kwargs
) -> Dict[str, Any]:
    """
    MCP Tool: Scrape municipal codes from various providers.
    
    Args:
        provider: Provider name ("municode", "ecode360", "american_legal")
        jurisdiction: Jurisdiction identifier
        **kwargs: Additional arguments
    
    Returns:
        Dict with status, data, and metadata
    """
    if not HAVE_CORE_SCRAPERS:
        return {
            "status": "error",
            "error": "Core scrapers not available. Check installation."
        }
    
    try:
        if provider == "municode":
            scraper = MunicodeScraper(
                cache_dir="./legal_scraper_cache/municode",
                enable_ipfs=kwargs.get("enable_ipfs", False),
                enable_warc=kwargs.get("enable_warc", True),
                check_archives=kwargs.get("check_archives", True)
            )
        elif provider == "ecode360":
            scraper = ECode360Scraper(
                cache_dir="./legal_scraper_cache/ecode360",
                enable_ipfs=kwargs.get("enable_ipfs", False),
                enable_warc=kwargs.get("enable_warc", True),
                check_archives=kwargs.get("check_archives", True)
            )
        else:
            return {
                "status": "error",
                "error": f"Unknown provider: {provider}"
            }
        
        result = await scraper.scrape(
            jurisdiction=jurisdiction,
            **kwargs
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Municipal code scraping failed: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


# Export all MCP tools
__all__ = [
    "scrape_state_laws",
    "scrape_us_code",
    "scrape_federal_register",
    "scrape_recap_documents",
    "scrape_municipal_codes"
]
