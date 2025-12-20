"""
MCP Server Tools for Unified Legal Scraping

Exposes the unified legal scraper through MCP protocol for use in
Claude Desktop and other MCP clients.

These are thin wrappers that delegate to the core legal_scrapers package.
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# Import from core package
try:
    # Add parent paths to find the main package
    package_root = Path(__file__).parent.parent.parent.parent
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    
    from ipfs_datasets_py.legal_scrapers.unified_scraper import UnifiedLegalScraper
    from ipfs_datasets_py.content_addressed_scraper import ContentAddressedScraper
    HAVE_LEGAL_SCRAPERS = True
    logger.info("Legal scrapers package loaded successfully")
except ImportError as e:
    HAVE_LEGAL_SCRAPERS = False
    logger.warning(f"Legal scrapers not available: {e}")
    logger.warning("Falling back to local unified_legal_scraper")


async def mcp_scrape_legal_url(
    url: str,
    force_rescrape: bool = False,
    prefer_archived: bool = True,
    enable_warc: bool = True,
    enable_ipfs: bool = False
) -> Dict[str, Any]:
    """
    Scrape a legal URL using unified scraper with content addressing.
    
    MCP Tool: scrape_legal_url
    
    This tool:
    - Checks if URL already scraped (content addressed)
    - Searches Common Crawl indexes (all indexes, each is a delta)
    - Falls back to Wayback Machine, IPWB, Archive.is
    - Uses Playwright for JS-heavy pages
    - Uses live scraping if needed
    - Generates IPFS CID
    - Exports to WARC format
    
    Args:
        url: URL to scrape
        force_rescrape: Force rescrape even if cached
        prefer_archived: Prefer archived versions over live
        enable_warc: Enable WARC export
        enable_ipfs: Enable IPFS storage
    
    Returns:
        Dict with:
            - success: bool
            - url: str
            - content: str (HTML)
            - cid: str (IPFS CID)
            - source: str (where content came from)
            - already_scraped: bool
            - warc_path: str (if exported)
            - common_crawl_indexes: List[str]
            - errors: List[str]
    
    Example:
        result = await mcp_scrape_legal_url("https://library.municode.com/wa/seattle")
        if result["success"]:
            print(f"CID: {result['cid']}")
            print(f"Source: {result['source']}")
    """
    try:
        if HAVE_LEGAL_SCRAPERS:
            # Use unified legal scraper - it handles all types automatically
            scraper = UnifiedLegalScraper(
                enable_ipfs=enable_ipfs,
                enable_warc=enable_warc,
                check_archives=prefer_archived
            )
            result = await scraper.scrape_url(
                url,
                force_rescrape=force_rescrape,
                prefer_archived=prefer_archived
            )
            return result
        else:
            # Fallback to local unified_legal_scraper
            from .unified_legal_scraper import UnifiedLegalScraper
            
            scraper = UnifiedLegalScraper(enable_warc=enable_warc)
            result = await scraper.scrape_url(
                url,
                force_rescrape=force_rescrape,
                prefer_archived=prefer_archived
            )
            
            return result.to_dict()
    except Exception as e:
        logger.error(f"MCP scrape_legal_url failed: {e}", exc_info=True)
        return {
            "success": False,
            "url": url,
            "errors": [str(e)]
        }


async def mcp_scrape_legal_urls_bulk(
    urls: List[str],
    max_concurrent: int = 10,
    force_rescrape: bool = False,
    prefer_archived: bool = True,
    enable_warc: bool = True
) -> Dict[str, Any]:
    """
    Scrape multiple legal URLs in parallel.
    
    MCP Tool: scrape_legal_urls_bulk
    
    Scrapes multiple URLs concurrently using the unified scraper
    with content addressing and fallback mechanisms.
    
    Args:
        urls: List of URLs to scrape
        max_concurrent: Maximum concurrent requests (default 10)
        force_rescrape: Force rescrape even if cached
        prefer_archived: Prefer archived versions
        enable_warc: Enable WARC export
    
    Returns:
        Dict with:
            - success: bool
            - total: int
            - successful: int
            - failed: int
            - results: List[Dict] (individual results)
            - summary: Dict (statistics)
    
    Example:
        urls = [
            "https://library.municode.com/wa/seattle",
            "https://library.municode.com/ca/los_angeles"
        ]
        result = await mcp_scrape_legal_urls_bulk(urls, max_concurrent=5)
        print(f"Scraped {result['successful']}/{result['total']}")
    """
    try:
        if HAVE_LEGAL_SCRAPERS:
            scraper = UnifiedLegalScraper(enable_warc=enable_warc)
            results = await scraper.scrape_urls_parallel(
                urls,
                max_concurrent=max_concurrent,
                force_rescrape=force_rescrape,
                prefer_archived=prefer_archived
            )
        else:
            from .unified_legal_scraper import UnifiedLegalScraper as LocalScraper
            
            scraper = LocalScraper(enable_warc=enable_warc)
            results = await scraper.scrape_urls_parallel(
                urls,
                max_concurrent=max_concurrent,
                force_rescrape=force_rescrape,
                prefer_archived=prefer_archived
            )
        
        successful = sum(1 for r in results if r.get('success'))
        
        # Gather statistics
        sources = {}
        for r in results:
            if r.get('success'):
                source = r.get('source', 'unknown')
                sources[source] = sources.get(source, 0) + 1
        
        return {
            "success": True,
            "total": len(urls),
            "successful": successful,
            "failed": len(urls) - successful,
            "results": results,
            "summary": {
                "sources_used": sources,
                "cached_count": sum(1 for r in results if r.get('already_scraped')),
                "archived_count": sum(1 for r in results if r.get('source', '').startswith(('common_crawl', 'wayback', 'ipwb'))),
                "live_count": sum(1 for r in results if r.get('source', '').startswith('live'))
            }
        }
    except Exception as e:
        logger.error(f"MCP scrape_legal_urls_bulk failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "total": len(urls),
            "successful": 0,
            "failed": len(urls)
        }


async def mcp_search_common_crawl(
    url: str,
    indexes: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Search Common Crawl indexes for a URL.
    
    MCP Tool: search_common_crawl
    
    Searches multiple Common Crawl indexes for the given URL pattern.
    Each index is a delta from prior scrapes, so searching multiple
    indexes finds all historical versions.
    
    Args:
        url: URL or URL pattern to search (supports wildcards like *)
        indexes: List of CC indexes to search (default: latest 5)
    
    Returns:
        Dict with:
            - success: bool
            - url: str
            - total_results: int
            - results: List[Dict] (CC index entries)
            - indexes_searched: List[str]
    
    Example:
        # Search for all Municode Seattle pages
        result = await mcp_search_common_crawl(
            "https://library.municode.com/wa/seattle/*"
        )
        print(f"Found {result['total_results']} entries")
    """
    try:
        from .unified_legal_scraper import UnifiedLegalScraper
        
        scraper = UnifiedLegalScraper()
        if indexes:
            scraper.common_crawl_indexes = indexes
        
        results = await scraper.search_common_crawl(url)
        
        return {
            "success": True,
            "url": url,
            "total_results": len(results),
            "results": results,
            "indexes_searched": scraper.common_crawl_indexes
        }
    except Exception as e:
        logger.error(f"MCP search_common_crawl failed: {e}")
        return {
            "success": False,
            "url": url,
            "error": str(e),
            "total_results": 0
        }


async def mcp_check_url_cached(url: str) -> Dict[str, Any]:
    """
    Check if URL has already been scraped.
    
    MCP Tool: check_url_cached
    
    Checks the content-addressed cache to see if this URL
    has been scraped before and returns version history.
    
    Args:
        url: URL to check
    
    Returns:
        Dict with:
            - cached: bool
            - url: str
            - versions: List[Dict] (version history)
            - latest_cid: str (most recent CID)
    
    Example:
        result = await mcp_check_url_cached("https://library.municode.com/wa/seattle")
        if result["cached"]:
            print(f"Already scraped, CID: {result['latest_cid']}")
    """
    try:
        from .unified_legal_scraper import UnifiedLegalScraper
        
        scraper = UnifiedLegalScraper()
        cached = await scraper.check_already_scraped(url)
        
        if cached:
            return {
                "cached": True,
                "url": url,
                "versions": cached['versions'],
                "latest_cid": cached['latest']['cid'] if cached['latest'] else None,
                "version_count": len(cached['versions'])
            }
        else:
            return {
                "cached": False,
                "url": url,
                "versions": [],
                "latest_cid": None,
                "version_count": 0
            }
    except Exception as e:
        logger.error(f"MCP check_url_cached failed: {e}")
        return {
            "cached": False,
            "url": url,
            "error": str(e)
        }


async def mcp_export_to_warc(
    url: str,
    html: str,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Export scraped content to WARC format.
    
    MCP Tool: export_to_warc
    
    Exports HTML content to WARC (Web ARChive) format for long-term
    archival and interoperability with other tools.
    
    Args:
        url: Source URL
        html: HTML content
        metadata: Additional metadata to include
    
    Returns:
        Dict with:
            - success: bool
            - warc_path: str (path to WARC file)
            - size: int (file size in bytes)
    
    Example:
        result = await mcp_export_to_warc(
            "https://example.com",
            "<html>...</html>",
            {"cid": "QmXxx", "source": "live"}
        )
        print(f"Exported to: {result['warc_path']}")
    """
    try:
        from .unified_legal_scraper import UnifiedLegalScraper
        
        scraper = UnifiedLegalScraper(enable_warc=True)
        warc_path = await scraper.export_to_warc(
            url,
            html,
            metadata or {}
        )
        
        if warc_path:
            from pathlib import Path
            size = Path(warc_path).stat().st_size
            
            return {
                "success": True,
                "warc_path": warc_path,
                "size": size
            }
        else:
            return {
                "success": False,
                "error": "WARC export failed"
            }
    except Exception as e:
        logger.error(f"MCP export_to_warc failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }


async def mcp_migrate_scraper_file(file_path: str) -> Dict[str, Any]:
    """
    Analyze a scraper file and generate migration report.
    
    MCP Tool: migrate_scraper_file
    
    Analyzes an existing scraper file to identify old scraping patterns
    and provides recommendations for migration to unified scraper.
    
    Args:
        file_path: Path to scraper file to analyze
    
    Returns:
        Dict with:
            - needs_migration: bool
            - file: str
            - patterns_found: List[Dict]
            - recommendations: List[str]
    
    Example:
        result = await mcp_migrate_scraper_file("state_scrapers/california.py")
        if result["needs_migration"]:
            print("Patterns to migrate:")
            for pattern in result["patterns_found"]:
                print(f"  - {pattern['pattern']}: {pattern['count']} occurrences")
    """
    try:
        from pathlib import Path
        from .scraper_adapter import MigrationHelper
        
        file_path_obj = Path(file_path)
        report = MigrationHelper.generate_migration_report(file_path_obj)
        
        return report
    except Exception as e:
        logger.error(f"MCP migrate_scraper_file failed: {e}")
        return {
            "error": str(e),
            "file": file_path,
            "needs_migration": False
        }


async def mcp_scrape_municode_jurisdiction(
    jurisdiction_url: str,
    extract_sections: bool = True,
    enable_ipfs: bool = False
) -> Dict[str, Any]:
    """
    Scrape a Municode jurisdiction with specialized parsing.
    
    MCP Tool: scrape_municode_jurisdiction
    
    Municode hosts municipal codes for 3,500+ US jurisdictions.
    This tool provides optimized scraping with proper structure extraction.
    
    Args:
        jurisdiction_url: URL of jurisdiction (e.g., "https://library.municode.com/wa/seattle")
        extract_sections: Parse and extract code sections
        enable_ipfs: Store in IPFS for permanent archiving
    
    Returns:
        Dict with:
            - success: bool
            - jurisdiction_name: str
            - state: str
            - sections: List[Dict] (if extract_sections=True)
            - content_cid: str (IPFS CID)
            - already_scraped: bool
    
    Example:
        result = await mcp_scrape_municode_jurisdiction(
            "https://library.municode.com/wa/seattle",
            extract_sections=True
        )
    """
    try:
        if not HAVE_LEGAL_SCRAPERS:
            return {
                "success": False,
                "error": "Legal scrapers package not available"
            }
        
        scraper = MunicodeScraper(
            enable_ipfs=enable_ipfs,
            enable_warc=True,
            check_archives=True
        )
        
        result = await scraper.scrape(
            jurisdiction_url,
            extract_sections=extract_sections
        )
        
        return result
    except Exception as e:
        logger.error(f"MCP scrape_municode_jurisdiction failed: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "jurisdiction_url": jurisdiction_url
        }


async def mcp_scrape_us_code_title(
    title: int,
    section: Optional[str] = None,
    enable_ipfs: bool = False
) -> Dict[str, Any]:
    """
    Scrape a US Code title or section.
    
    MCP Tool: scrape_us_code_title
    
    Scrapes federal statutory law from uscode.house.gov.
    Supports all 54 titles of the United States Code.
    
    Args:
        title: Title number (1-54)
        section: Optional specific section within title
        enable_ipfs: Store in IPFS
    
    Returns:
        Dict with:
            - success: bool
            - title: int
            - title_name: str
            - sections: List[Dict]
            - content_cid: str
    
    Example:
        # Scrape Title 18 (Crimes)
        result = await mcp_scrape_us_code_title(18)
        
        # Scrape specific section
        result = await mcp_scrape_us_code_title(18, section="1001")
    """
    try:
        if not HAVE_LEGAL_SCRAPERS:
            return {
                "success": False,
                "error": "Legal scrapers package not available"
            }
        
        scraper = USCodeScraper(
            enable_ipfs=enable_ipfs,
            enable_warc=True,
            check_archives=True
        )
        
        result = await scraper.scrape(
            title=title,
            section=section
        )
        
        return result
    except Exception as e:
        logger.error(f"MCP scrape_us_code_title failed: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "title": title
        }


async def mcp_scrape_state_laws(
    state_code: str,
    include_statutes: bool = True,
    include_regulations: bool = False,
    enable_ipfs: bool = False
) -> Dict[str, Any]:
    """
    Scrape state laws and statutes.
    
    MCP Tool: scrape_state_laws
    
    Scrapes state statutory law with support for all 50 states + DC.
    
    Args:
        state_code: Two-letter state code (e.g., "WA", "CA", "NY")
        include_statutes: Include state statutes
        include_regulations: Include state regulations
        enable_ipfs: Store in IPFS
    
    Returns:
        Dict with:
            - success: bool
            - state: str
            - state_name: str
            - statutes: List[Dict]
            - content_cid: str
    
    Example:
        # Scrape Washington state laws
        result = await mcp_scrape_state_laws("WA", include_statutes=True)
    """
    try:
        if not HAVE_LEGAL_SCRAPERS:
            return {
                "success": False,
                "error": "Legal scrapers package not available"
            }
        
        scraper = StateLawsScraper(
            enable_ipfs=enable_ipfs,
            enable_warc=True,
            check_archives=True
        )
        
        result = await scraper.scrape(
            state_code=state_code,
            include_statutes=include_statutes,
            include_regulations=include_regulations
        )
        
        return result
    except Exception as e:
        logger.error(f"MCP scrape_state_laws failed: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "state_code": state_code
        }


async def mcp_scrape_federal_register(
    query: Optional[str] = None,
    document_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    enable_ipfs: bool = False
) -> Dict[str, Any]:
    """
    Scrape Federal Register documents.
    
    MCP Tool: scrape_federal_register
    
    Scrapes daily publications of federal agency rules, proposed rules,
    and notices from federalregister.gov.
    
    Args:
        query: Search query (optional)
        document_type: Type (rule, proposed_rule, notice)
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        enable_ipfs: Store in IPFS
    
    Returns:
        Dict with:
            - success: bool
            - documents: List[Dict]
            - count: int
            - query: str
    
    Example:
        # Search for EPA rules
        result = await mcp_scrape_federal_register(
            query="EPA environmental",
            document_type="rule"
        )
    """
    try:
        if not HAVE_LEGAL_SCRAPERS:
            return {
                "success": False,
                "error": "Legal scrapers package not available"
            }
        
        scraper = FederalRegisterScraper(
            enable_ipfs=enable_ipfs,
            enable_warc=True,
            check_archives=True
        )
        
        result = await scraper.scrape(
            query=query,
            document_type=document_type,
            start_date=start_date,
            end_date=end_date
        )
        
        return result
    except Exception as e:
        logger.error(f"MCP scrape_federal_register failed: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }


async def mcp_search_court_opinions(
    query: Optional[str] = None,
    citation: Optional[str] = None,
    court: Optional[str] = None,
    judge: Optional[str] = None,
    filed_after: Optional[str] = None,
    filed_before: Optional[str] = None,
    limit: int = 20,
    api_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Search court opinions with CourtListener fallback to direct court websites.
    
    MCP Tool: search_court_opinions
    
    Searches CourtListener API first, then falls back to scraping direct court
    websites if citation not found. Supports Supreme Court, Circuit Courts,
    District Courts, and State Courts.
    
    Args:
        query: Free text search
        citation: Specific citation (e.g., "410 U.S. 113")
        court: Court identifier (e.g., "scotus", "ca9")
        judge: Judge name
        filed_after: Date in YYYY-MM-DD format
        filed_before: Date in YYYY-MM-DD format
        limit: Maximum results (default 20)
        api_token: Optional CourtListener API token
    
    Returns:
        Dict with:
            - success: bool
            - count: int
            - results: List[Dict] (opinions)
            - source: str (courtlistener_api or direct_scraping)
    
    Example:
        # Search Supreme Court
        result = await mcp_search_court_opinions(
            court="scotus",
            citation="410 U.S. 113"
        )
        
        # Search Ninth Circuit
        result = await mcp_search_court_opinions(
            court="ca9",
            query="environmental protection"
        )
    """
    try:
        if not HAVE_LEGAL_SCRAPERS:
            return {
                "success": False,
                "error": "Legal scrapers package not available"
            }
        
        from ipfs_datasets_py.legal_scrapers.scrapers.courtlistener_scraper import CourtListenerScraper
        from ipfs_datasets_py.legal_scrapers.unified_scraper import UnifiedScraper
        
        unified_scraper = UnifiedScraper()
        scraper = CourtListenerScraper(api_token=api_token, unified_scraper=unified_scraper)
        
        result = await scraper.search_opinions(
            query=query,
            citation=citation,
            court=court,
            judge=judge,
            filed_after=filed_after,
            filed_before=filed_before,
            limit=limit
        )
        
        return {
            "success": True,
            **result
        }
    except Exception as e:
        logger.error(f"MCP search_court_opinions failed: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "count": 0,
            "results": []
        }


async def mcp_search_court_dockets(
    court: Optional[str] = None,
    case_name: Optional[str] = None,
    docket_number: Optional[str] = None,
    limit: int = 20,
    api_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Search court dockets on CourtListener.
    
    MCP Tool: search_court_dockets
    
    Searches federal and state court dockets including PACER data
    from the RECAP Archive.
    
    Args:
        court: Court identifier
        case_name: Case name to search
        docket_number: Specific docket number
        limit: Maximum results
        api_token: Optional CourtListener API token
    
    Returns:
        Dict with docket entries
    
    Example:
        result = await mcp_search_court_dockets(
            court="ca9",
            case_name="Smith v. Jones"
        )
    """
    try:
        if not HAVE_LEGAL_SCRAPERS:
            return {
                "success": False,
                "error": "Legal scrapers package not available"
            }
        
        from ipfs_datasets_py.legal_scrapers.scrapers.courtlistener_scraper import CourtListenerScraper
        from ipfs_datasets_py.legal_scrapers.unified_scraper import UnifiedScraper
        
        unified_scraper = UnifiedScraper()
        scraper = CourtListenerScraper(api_token=api_token, unified_scraper=unified_scraper)
        
        result = await scraper.get_dockets(
            court=court,
            case_name=case_name,
            docket_number=docket_number,
            limit=limit
        )
        
        return {
            "success": True,
            **result
        }
    except Exception as e:
        logger.error(f"MCP search_court_dockets failed: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "count": 0,
            "results": []
        }


# MCP Tool registry for auto-registration
MCP_TOOLS = [
    {
        "name": "scrape_legal_url",
        "description": "Scrape a legal URL with content addressing and multi-source fallback",
        "function": mcp_scrape_legal_url,
        "parameters": {
            "url": {"type": "string", "required": True},
            "force_rescrape": {"type": "boolean", "required": False, "default": False},
            "prefer_archived": {"type": "boolean", "required": False, "default": True},
            "enable_warc": {"type": "boolean", "required": False, "default": True}
        }
    },
    {
        "name": "scrape_legal_urls_bulk",
        "description": "Scrape multiple legal URLs in parallel",
        "function": mcp_scrape_legal_urls_bulk,
        "parameters": {
            "urls": {"type": "array", "items": {"type": "string"}, "required": True},
            "max_concurrent": {"type": "integer", "required": False, "default": 10},
            "force_rescrape": {"type": "boolean", "required": False, "default": False},
            "prefer_archived": {"type": "boolean", "required": False, "default": True},
            "enable_warc": {"type": "boolean", "required": False, "default": True}
        }
    },
    {
        "name": "scrape_municode_jurisdiction",
        "description": "Scrape a Municode jurisdiction with specialized parsing (3,500+ US jurisdictions)",
        "function": mcp_scrape_municode_jurisdiction,
        "parameters": {
            "jurisdiction_url": {"type": "string", "required": True},
            "extract_sections": {"type": "boolean", "required": False, "default": True},
            "enable_ipfs": {"type": "boolean", "required": False, "default": False}
        }
    },
    {
        "name": "scrape_us_code_title",
        "description": "Scrape US Code title or section (federal statutory law)",
        "function": mcp_scrape_us_code_title,
        "parameters": {
            "title": {"type": "integer", "required": True},
            "section": {"type": "string", "required": False},
            "enable_ipfs": {"type": "boolean", "required": False, "default": False}
        }
    },
    {
        "name": "scrape_state_laws",
        "description": "Scrape state laws and statutes (all 50 states + DC)",
        "function": mcp_scrape_state_laws,
        "parameters": {
            "state_code": {"type": "string", "required": True},
            "include_statutes": {"type": "boolean", "required": False, "default": True},
            "include_regulations": {"type": "boolean", "required": False, "default": False},
            "enable_ipfs": {"type": "boolean", "required": False, "default": False}
        }
    },
    {
        "name": "scrape_federal_register",
        "description": "Scrape Federal Register documents (rules, proposed rules, notices)",
        "function": mcp_scrape_federal_register,
        "parameters": {
            "query": {"type": "string", "required": False},
            "document_type": {"type": "string", "required": False},
            "start_date": {"type": "string", "required": False},
            "end_date": {"type": "string", "required": False},
            "enable_ipfs": {"type": "boolean", "required": False, "default": False}
        }
    },
    {
        "name": "search_common_crawl",
        "description": "Search Common Crawl indexes for URL patterns",
        "function": mcp_search_common_crawl,
        "parameters": {
            "url": {"type": "string", "required": True},
            "indexes": {"type": "array", "items": {"type": "string"}, "required": False}
        }
    },
    {
        "name": "check_url_cached",
        "description": "Check if URL already scraped with content addressing",
        "function": mcp_check_url_cached,
        "parameters": {
            "url": {"type": "string", "required": True}
        }
    },
    {
        "name": "export_to_warc",
        "description": "Export scraped content to WARC format",
        "function": mcp_export_to_warc,
        "parameters": {
            "url": {"type": "string", "required": True},
            "html": {"type": "string", "required": True},
            "metadata": {"type": "object", "required": False}
        }
    },
    {
        "name": "migrate_scraper_file",
        "description": "Analyze scraper file and generate migration report",
        "function": mcp_migrate_scraper_file,
        "parameters": {
            "file_path": {"type": "string", "required": True}
        }
    },
    {
        "name": "search_court_opinions",
        "description": "Search court opinions with CourtListener + fallback to direct court websites",
        "function": mcp_search_court_opinions,
        "parameters": {
            "query": {"type": "string", "required": False},
            "citation": {"type": "string", "required": False},
            "court": {"type": "string", "required": False},
            "judge": {"type": "string", "required": False},
            "filed_after": {"type": "string", "required": False},
            "filed_before": {"type": "string", "required": False},
            "limit": {"type": "integer", "required": False, "default": 20},
            "api_token": {"type": "string", "required": False}
        }
    },
    {
        "name": "search_court_dockets",
        "description": "Search court dockets including RECAP Archive (PACER data)",
        "function": mcp_search_court_dockets,
        "parameters": {
            "court": {"type": "string", "required": False},
            "case_name": {"type": "string", "required": False},
            "docket_number": {"type": "string", "required": False},
            "limit": {"type": "integer", "required": False, "default": 20},
            "api_token": {"type": "string", "required": False}
        }
    }
]
