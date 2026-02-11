"""Common Crawl Search Engine tools for MCP server.

These tools provide access to the common_crawl_search_engine submodule for advanced
web archiving and internet search capabilities as a fallback/redundancy system.
"""

import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


async def search_common_crawl_advanced(
    domain: str,
    max_matches: int = 100,
    collection: Optional[str] = None,
    master_db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Search Common Crawl using the advanced search engine submodule.
    
    This tool uses the common_crawl_search_engine submodule for fast domain/URL lookups
    with rowgroup slicing and optimized indexes. It provides a redundancy/fallback
    system for internet data retrieval when dealing with Cloudflare bottlenecks.
    
    Args:
        domain: Domain to search for (e.g., "example.com")
        max_matches: Maximum number of matches to return (default: 100)
        collection: Specific Common Crawl collection (e.g., "CC-MAIN-2024-10")
        master_db_path: Path to master DuckDB index (optional)
        
    Returns:
        Dict containing:
            - status: "success" or "error"
            - results: List of matching records with URL, timestamp, and WARC info
            - count: Number of results returned
            - engine: "common_crawl_search_engine" (identifies which engine was used)
            - error: Error message (if failed)
    """
    try:
        from ipfs_datasets_py.web_archiving.common_crawl_integration import CommonCrawlSearchEngine
        
        # Initialize search engine
        engine = CommonCrawlSearchEngine(master_db_path=master_db_path)
        
        if not engine.is_available():
            return {
                "status": "error",
                "error": "Common Crawl Search Engine submodule not available. "
                        "Run: git submodule update --init",
                "fallback_available": True,
                "fallback_tool": "search_common_crawl"
            }
        
        # Perform search
        results = engine.search_domain(
            domain=domain,
            max_matches=max_matches,
            collection=collection
        )
        
        return {
            "status": "success",
            "results": results,
            "count": len(results),
            "engine": "common_crawl_search_engine",
            "domain": domain,
            "max_matches": max_matches,
            "collection": collection or "auto"
        }
        
    except Exception as e:
        logger.error(f"Advanced Common Crawl search failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "fallback_available": True,
            "fallback_tool": "search_common_crawl"
        }


async def fetch_warc_record_advanced(
    warc_filename: str,
    warc_offset: int,
    warc_length: int,
    decode_content: bool = True,
) -> Dict[str, Any]:
    """
    Fetch a WARC record from Common Crawl using the advanced search engine.
    
    Args:
        warc_filename: WARC file name
        warc_offset: Byte offset in the WARC file
        warc_length: Length of the record in bytes
        decode_content: Whether to decode the content (default: True)
        
    Returns:
        Dict containing:
            - status: "success" or "error"
            - content: Record content (if decode_content=True)
            - raw_content: Raw bytes (if decode_content=False)
            - warc_info: Metadata about the WARC record
            - error: Error message (if failed)
    """
    try:
        from ipfs_datasets_py.web_archiving.common_crawl_integration import CommonCrawlSearchEngine
        
        # Initialize search engine
        engine = CommonCrawlSearchEngine()
        
        if not engine.is_available():
            return {
                "status": "error",
                "error": "Common Crawl Search Engine submodule not available"
            }
        
        # Fetch WARC record
        raw_content = engine.fetch_warc_record(
            warc_filename=warc_filename,
            warc_offset=warc_offset,
            warc_length=warc_length
        )
        
        result = {
            "status": "success",
            "warc_info": {
                "filename": warc_filename,
                "offset": warc_offset,
                "length": warc_length
            }
        }
        
        if decode_content:
            # Decode content if requested
            try:
                result["content"] = raw_content.decode('utf-8', errors='replace')
            except Exception as decode_error:
                logger.warning(f"Failed to decode content: {decode_error}")
                result["raw_content"] = raw_content.hex()
        else:
            result["raw_content"] = raw_content.hex()
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to fetch WARC record: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


async def list_common_crawl_collections_advanced() -> Dict[str, Any]:
    """
    List available Common Crawl collections using the advanced search engine.
    
    Returns:
        Dict containing:
            - status: "success" or "error"
            - collections: List of collection names
            - count: Number of collections available
            - error: Error message (if failed)
    """
    try:
        from ipfs_datasets_py.web_archiving.common_crawl_integration import CommonCrawlSearchEngine
        
        # Initialize search engine
        engine = CommonCrawlSearchEngine()
        
        if not engine.is_available():
            return {
                "status": "error",
                "error": "Common Crawl Search Engine submodule not available"
            }
        
        # List collections
        collections = engine.list_collections()
        
        return {
            "status": "success",
            "collections": collections,
            "count": len(collections),
            "engine": "common_crawl_search_engine"
        }
        
    except Exception as e:
        logger.error(f"Failed to list collections: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


async def get_common_crawl_collection_info_advanced(
    collection: str
) -> Dict[str, Any]:
    """
    Get information about a specific Common Crawl collection.
    
    Args:
        collection: Collection name (e.g., "CC-MAIN-2024-10")
        
    Returns:
        Dict containing:
            - status: "success" or "error"
            - collection: Collection name
            - info: Metadata about the collection
            - error: Error message (if failed)
    """
    try:
        from ipfs_datasets_py.web_archiving.common_crawl_integration import CommonCrawlSearchEngine
        
        # Initialize search engine
        engine = CommonCrawlSearchEngine()
        
        if not engine.is_available():
            return {
                "status": "error",
                "error": "Common Crawl Search Engine submodule not available"
            }
        
        # Get collection info
        info = engine.get_collection_info(collection)
        
        return {
            "status": "success",
            "collection": collection,
            "info": info,
            "engine": "common_crawl_search_engine"
        }
        
    except Exception as e:
        logger.error(f"Failed to get collection info: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


__all__ = [
    "search_common_crawl_advanced",
    "fetch_warc_record_advanced",
    "list_common_crawl_collections_advanced",
    "get_common_crawl_collection_info_advanced",
]
