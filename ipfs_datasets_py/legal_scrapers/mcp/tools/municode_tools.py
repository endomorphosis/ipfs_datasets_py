#!/usr/bin/env python3
"""
MCP Tools for Municode Scraper

Model Context Protocol tool definitions for Municode scraping.
Enables AI assistants to scrape municipal codes via MCP.
"""

from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

# Import core scraper
try:
    from ...core import MunicodeScraper, run_async_scraper
    HAVE_SCRAPER = True
except ImportError:
    HAVE_SCRAPER = False
    logger.error("Failed to import MunicodeScraper")


def register_municode_tools(server):
    """
    Register Municode scraping tools with MCP server.
    
    Args:
        server: MCP server instance
        
    Returns:
        MCP server with Municode tools registered
    """
    if not HAVE_SCRAPER:
        logger.error("Cannot register Municode tools - scraper not available")
        return server
    
    @server.tool(
        name="scrape_municode_jurisdiction",
        description="Scrape municipal codes from a Municode library jurisdiction. Returns jurisdiction metadata, code sections, and content identifiers.",
        schema={
            "type": "object",
            "properties": {
                "jurisdiction_url": {
                    "type": "string",
                    "description": "Full URL of the jurisdiction to scrape (e.g., 'https://library.municode.com/wa/seattle')",
                    "pattern": "^https://library\\.municode\\.com/.+"
                },
                "enable_ipfs": {
                    "type": "boolean",
                    "description": "Store scraped content in IPFS for permanent archiving",
                    "default": False
                },
                "enable_warc": {
                    "type": "boolean",
                    "description": "Enable WARC format import/export",
                    "default": False
                },
                "check_archives": {
                    "type": "boolean",
                    "description": "Check Common Crawl and Wayback Machine archives before scraping",
                    "default": True
                },
                "include_metadata": {
                    "type": "boolean",
                    "description": "Include detailed jurisdiction metadata in results",
                    "default": True
                },
                "extract_sections": {
                    "type": "boolean",
                    "description": "Parse and extract individual code sections",
                    "default": True
                }
            },
            "required": ["jurisdiction_url"]
        }
    )
    async def scrape_municode_jurisdiction(
        jurisdiction_url: str,
        enable_ipfs: bool = False,
        enable_warc: bool = False,
        check_archives: bool = True,
        include_metadata: bool = True,
        extract_sections: bool = True
    ) -> Dict[str, Any]:
        """Scrape a Municode jurisdiction and return structured data."""
        try:
            scraper = MunicodeScraper(
                enable_ipfs=enable_ipfs,
                enable_warc=enable_warc,
                check_archives=check_archives
            )
            
            result = await scraper.scrape(
                jurisdiction_url=jurisdiction_url,
                include_metadata=include_metadata,
                extract_sections=extract_sections
            )
            
            return result
        
        except Exception as e:
            logger.error(f"Error scraping Municode: {e}")
            return {
                "status": "error",
                "jurisdiction_url": jurisdiction_url,
                "error": str(e)
            }
    
    @server.tool(
        name="batch_scrape_municode",
        description="Scrape multiple Municode jurisdictions in batch. Efficiently handles concurrent requests with deduplication.",
        schema={
            "type": "object",
            "properties": {
                "jurisdiction_urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Array of jurisdiction URLs to scrape",
                    "minItems": 1
                },
                "max_concurrent": {
                    "type": "integer",
                    "description": "Maximum number of concurrent requests",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20
                },
                "enable_ipfs": {
                    "type": "boolean",
                    "description": "Store scraped content in IPFS",
                    "default": False
                },
                "check_archives": {
                    "type": "boolean",
                    "description": "Check archives before scraping",
                    "default": True
                }
            },
            "required": ["jurisdiction_urls"]
        }
    )
    async def batch_scrape_municode(
        jurisdiction_urls: list,
        max_concurrent: int = 5,
        enable_ipfs: bool = False,
        check_archives: bool = True
    ) -> Dict[str, Any]:
        """Batch scrape multiple Municode jurisdictions."""
        try:
            scraper = MunicodeScraper(
                enable_ipfs=enable_ipfs,
                check_archives=check_archives
            )
            
            results = await scraper.scrape_multiple(
                jurisdiction_urls=jurisdiction_urls,
                max_concurrent=max_concurrent
            )
            
            # Summarize results
            success_count = sum(1 for r in results if r.get('status') == 'success')
            cached_count = sum(1 for r in results if r.get('status') == 'cached')
            error_count = sum(1 for r in results if r.get('status') == 'error')
            
            return {
                "status": "complete",
                "total": len(results),
                "success": success_count,
                "cached": cached_count,
                "errors": error_count,
                "results": results
            }
        
        except Exception as e:
            logger.error(f"Error in batch scraping: {e}")
            return {
                "status": "error",
                "error": str(e),
                "total_requested": len(jurisdiction_urls)
            }
    
    @server.tool(
        name="import_municode_from_commoncrawl",
        description="Import historical Municode content from Common Crawl archives. Useful for accessing previously captured versions without live scraping.",
        schema={
            "type": "object",
            "properties": {
                "url_pattern": {
                    "type": "string",
                    "description": "URL pattern to search in Common Crawl (supports wildcards, e.g., 'library.municode.com/wa/*')",
                },
                "index_id": {
                    "type": "string",
                    "description": "Common Crawl index identifier (e.g., 'CC-MAIN-2025-47')",
                    "default": "CC-MAIN-2025-47"
                },
                "max_records": {
                    "type": "integer",
                    "description": "Maximum number of records to import",
                    "default": 100,
                    "minimum": 1,
                    "maximum": 1000
                }
            },
            "required": ["url_pattern"]
        }
    )
    async def import_municode_from_commoncrawl(
        url_pattern: str,
        index_id: str = "CC-MAIN-2025-47",
        max_records: int = 100
    ) -> Dict[str, Any]:
        """Import Municode content from Common Crawl archives."""
        try:
            scraper = MunicodeScraper(
                enable_warc=True,
                check_archives=True
            )
            
            records = await scraper.import_from_common_crawl(
                url_pattern=url_pattern,
                index_id=index_id,
                max_records=max_records
            )
            
            return {
                "status": "success",
                "index_id": index_id,
                "url_pattern": url_pattern,
                "records_imported": len(records),
                "records": records
            }
        
        except Exception as e:
            logger.error(f"Error importing from Common Crawl: {e}")
            return {
                "status": "error",
                "error": str(e),
                "url_pattern": url_pattern,
                "index_id": index_id
            }
    
    @server.tool(
        name="get_municode_statistics",
        description="Get statistics about scraped Municode content including cache hits, unique jurisdictions, and storage information.",
        schema={
            "type": "object",
            "properties": {
                "cache_dir": {
                    "type": "string",
                    "description": "Cache directory to analyze (optional)",
                }
            }
        }
    )
    async def get_municode_statistics(
        cache_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get Municode scraping statistics."""
        try:
            scraper = MunicodeScraper(cache_dir=cache_dir)
            stats = scraper.get_statistics()
            
            return {
                "status": "success",
                "statistics": stats
            }
        
        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    logger.info("✓ Registered 4 Municode MCP tools")
    return server


# Tool metadata for discovery
MUNICODE_TOOLS = [
    {
        "name": "scrape_municode_jurisdiction",
        "description": "Scrape a single Municode jurisdiction",
        "category": "legal_data",
        "subcategory": "municipal_codes"
    },
    {
        "name": "batch_scrape_municode",
        "description": "Batch scrape multiple Municode jurisdictions",
        "category": "legal_data",
        "subcategory": "municipal_codes"
    },
    {
        "name": "import_municode_from_commoncrawl",
        "description": "Import Municode content from Common Crawl",
        "category": "legal_data",
        "subcategory": "municipal_codes"
    },
    {
        "name": "get_municode_statistics",
        "description": "Get Municode scraping statistics",
        "category": "legal_data",
        "subcategory": "municipal_codes"
    }
]


if __name__ == "__main__":
    # Test tool definitions
    print("Municode MCP Tools:")
    for tool in MUNICODE_TOOLS:
        print(f"  - {tool['name']}: {tool['description']}")
    print(f"\nTotal: {len(MUNICODE_TOOLS)} tools")
