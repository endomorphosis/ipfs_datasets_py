"""Federal Register scraper for building federal regulations datasets.

This tool scrapes the Federal Register from federalregister.gov
and provides structured access to federal regulations and notices.
"""
import logging
import time
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from urllib.parse import urlparse
import ipaddress
import socket

logger = logging.getLogger(__name__)

# Federal agencies commonly tracked in Federal Register
FEDERAL_AGENCIES = {
    "EPA": "Environmental Protection Agency",
    "FDA": "Food and Drug Administration",
    "DOL": "Department of Labor",
    "SEC": "Securities and Exchange Commission",
    "FTC": "Federal Trade Commission",
    "DOE": "Department of Energy",
    "DOT": "Department of Transportation",
    "HHS": "Department of Health and Human Services",
    "DHS": "Department of Homeland Security",
    "DOJ": "Department of Justice",
    "USDA": "Department of Agriculture",
    "DOD": "Department of Defense",
    "DOC": "Department of Commerce",
    "DOI": "Department of the Interior",
    "ED": "Department of Education",
    "HUD": "Department of Housing and Urban Development",
    "VA": "Department of Veterans Affairs",
    "SSA": "Social Security Administration",
    "FCC": "Federal Communications Commission",
    "CFPB": "Consumer Financial Protection Bureau"
}


def _is_public_ip(ip_str: str) -> bool:
    """Return True if the IP address is globally routable (not private/loopback/etc.)."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
    )


def _is_safe_federal_register_url(url: str) -> bool:
    """Validate that the URL points to the public Federal Register site and not an internal address."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    # Only allow official Federal Register domains
    if not (hostname == "www.federalregister.gov" or hostname.endswith(".federalregister.gov")):
        return False

    # Resolve hostname and ensure all addresses are public
    try:
        addrinfos = socket.getaddrinfo(hostname, None)
    except OSError:
        return False

    for family, _, _, _, sockaddr in addrinfos:
        if family in (socket.AF_INET, socket.AF_INET6):
            ip_str = sockaddr[0]
            if not _is_public_ip(ip_str):
                return False

    return True


async def search_federal_register(
    agencies: Optional[List[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    document_types: Optional[List[str]] = None,
    keywords: Optional[str] = None,
    limit: int = 100
) -> Dict[str, Any]:
    """Search Federal Register documents.
    
    Args:
        agencies: List of agency abbreviations (e.g., ["EPA", "FDA"])
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        document_types: Types of documents (e.g., ["RULE", "NOTICE", "PRORULE"])
        keywords: Search keywords
        limit: Maximum number of results
    
    Returns:
        Dict containing:
            - status: "success" or "error"
            - documents: List of matching documents
            - count: Number of documents found
            - search_params: Parameters used for search
            - error: Error message (if failed)
    """
    try:
        logger.info(f"Searching Federal Register: agencies={agencies}, dates={start_date} to {end_date}")
        
        # Import required libraries
        try:
            import requests
        except ImportError as ie:
            return {
                "status": "error",
                "error": f"Required library not available: {ie}. Install with: pip install requests",
                "documents": [],
                "count": 0
            }
        
        # Build search parameters
        search_params = {
            "agencies": agencies or [],
            "start_date": start_date,
            "end_date": end_date,
            "document_types": document_types or ["RULE", "NOTICE", "PRORULE"],
            "keywords": keywords,
            "limit": limit
        }
        
        # Query the Federal Register API
        # API endpoint: https://www.federalregister.gov/api/v1/documents.json
        # Documentation: https://www.federalregister.gov/developers/documentation/api/v1
        
        try:
            # Build API query parameters
            api_params = {
                "per_page": min(limit, 1000),  # API max is 1000
                "order": "newest"
            }
            
            # Add date filters
            if start_date:
                api_params["conditions[publication_date][gte]"] = start_date
            if end_date:
                api_params["conditions[publication_date][lte]"] = end_date
            
            # Add agency filter
            if agencies:
                # Federal Register uses agency slugs
                api_params["conditions[agencies][]"] = agencies
            
            # Add document type filter
            if document_types:
                api_params["conditions[type][]"] = document_types
            
            # Add keyword search
            if keywords:
                api_params["conditions[term]"] = keywords
            
            # Make API request
            api_url = "https://www.federalregister.gov/api/v1/documents.json"
            logger.info(f"Querying Federal Register API: {api_url}")
            
            response = requests.get(api_url, params=api_params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                results = data.get('results', [])
                
                # Transform results to our standardized format
                documents = []
                for result in results:
                    doc = {
                        "document_number": result.get('document_number', ''),
                        "title": result.get('title', ''),
                        "agency": result.get('agencies', [{}])[0].get('name', '') if result.get('agencies') else '',
                        "agency_abbr": result.get('agencies', [{}])[0].get('slug', '').upper() if result.get('agencies') else '',
                        "document_type": result.get('type', ''),
                        "publication_date": result.get('publication_date', ''),
                        "abstract": result.get('abstract', '')[:500] if result.get('abstract') else '',
                        "citation": result.get('citation', ''),
                        "fr_url": result.get('html_url', ''),
                        "pdf_url": result.get('pdf_url', ''),
                        "raw_text_url": result.get('raw_text_url', ''),
                        "signing_date": result.get('signing_date', ''),
                        "docket_ids": result.get('docket_ids', []),
                        "regulation_id_numbers": result.get('regulation_id_numbers', []),
                        "topics": result.get('topics', []),
                        "significant": result.get('significant', False)
                    }
                    documents.append(doc)
                
                return {
                    "status": "success",
                    "documents": documents,
                    "count": len(documents),
                    "total_available": data.get('count', len(documents)),
                    "search_params": search_params,
                    "api_endpoint": api_url,
                    "note": "Results from Federal Register API at federalregister.gov"
                }
            else:
                # API request failed
                logger.warning(f"Federal Register API returned status {response.status_code}")
                return {
                    "status": "error",
                    "error": f"API request failed with status {response.status_code}: {response.text[:200]}",
                    "documents": [],
                    "count": 0,
                    "search_params": search_params,
                    "api_endpoint": api_url
                }
                
        except requests.exceptions.Timeout:
            logger.error("Federal Register API request timed out")
            return {
                "status": "error",
                "error": "API request timed out after 30 seconds",
                "documents": [],
                "count": 0
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"Federal Register API request failed: {e}")
            return {
                "status": "error",
                "error": f"API request failed: {str(e)}",
                "documents": [],
                "count": 0
            }
        
    except Exception as e:
        logger.error(f"Federal Register search failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "documents": [],
            "count": 0
        }


async def scrape_federal_register(
    agencies: Optional[List[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    document_types: Optional[List[str]] = None,
    output_format: str = "json",
    include_full_text: bool = False,
    rate_limit_delay: float = 1.0,
    max_documents: Optional[int] = None
) -> Dict[str, Any]:
    """Scrape Federal Register documents and build a structured dataset.
    
    Args:
        agencies: List of agency abbreviations to scrape. If None or ["all"], scrapes all agencies.
        start_date: Start date in YYYY-MM-DD format (default: 30 days ago)
        end_date: End date in YYYY-MM-DD format (default: today)
        document_types: Types of documents to scrape (default: ["RULE", "NOTICE", "PRORULE"])
        output_format: Output format - "json" or "parquet"
        include_full_text: Include full document text (increases scraping time)
        rate_limit_delay: Delay between requests in seconds (default 1.0)
        max_documents: Maximum number of documents to scrape
    
    Returns:
        Dict containing:
            - status: "success" or "error"
            - data: Scraped Federal Register documents
            - metadata: Scraping metadata
            - output_format: Format of the data
            - error: Error message (if failed)
    """
    try:
        # Set default date range if not provided
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        
        # Validate and process agencies
        if agencies is None or "all" in agencies:
            selected_agencies = list(FEDERAL_AGENCIES.keys())
        else:
            selected_agencies = [a for a in agencies if a in FEDERAL_AGENCIES]
            if not selected_agencies:
                return {
                    "status": "error",
                    "error": "No valid agencies specified",
                    "data": [],
                    "metadata": {}
                }
        
        logger.info(f"Starting Federal Register scraping: {len(selected_agencies)} agencies, {start_date} to {end_date}")
        start_time = time.time()
        
        # Import required libraries
        try:
            import requests
        except ImportError as ie:
            return {
                "status": "error",
                "error": f"Required library not available: {ie}. Install with: pip install requests",
                "data": [],
                "metadata": {}
            }
        
        scraped_documents = []
        documents_count = 0
        
        # Use the search function to get documents from all agencies
        for agency in selected_agencies:
            if max_documents and documents_count >= max_documents:
                logger.info(f"Reached max_documents limit of {max_documents}")
                break
            
            agency_name = FEDERAL_AGENCIES[agency]
            logger.info(f"Scraping {agency}: {agency_name}")
            
            # Use search function to query Federal Register API
            search_result = await search_federal_register(
                agencies=[agency],
                start_date=start_date,
                end_date=end_date,
                document_types=document_types,
                limit=min(100, max_documents - documents_count if max_documents else 100)
            )
            
            if search_result['status'] == 'success' and search_result['documents']:
                for doc in search_result['documents']:
                    if max_documents and documents_count >= max_documents:
                        break
                    
                    # Optionally fetch full text
                    if include_full_text and doc.get('raw_text_url'):
                        raw_url = doc.get('raw_text_url')
                        if _is_safe_federal_register_url(str(raw_url)):
                            try:
                                text_response = requests.get(raw_url, timeout=30)
                                if text_response.status_code == 200:
                                    doc['full_text'] = text_response.text
                            except Exception as e:
                                logger.warning(f"Failed to fetch full text for {doc.get('document_number')}: {e}")
                                doc['full_text'] = None
                        else:
                            logger.warning(
                                f"Skipping full text fetch for {doc.get('document_number')}: "
                                f"unsafe raw_text_url={raw_url!r}"
                            )
                    
                    doc['scraped_at'] = datetime.now().isoformat()
                    scraped_documents.append(doc)
                    documents_count += 1
            
            # Rate limiting between agency requests
            time.sleep(rate_limit_delay)
        
        elapsed_time = time.time() - start_time
        
        metadata = {
            "agencies_scraped": selected_agencies,
            "agencies_count": len(selected_agencies),
            "documents_count": documents_count,
            "date_range": {
                "start_date": start_date,
                "end_date": end_date
            },
            "elapsed_time_seconds": elapsed_time,
            "scraped_at": datetime.now().isoformat(),
            "source": "Federal Register API (federalregister.gov)",
            "api_endpoint": "https://www.federalregister.gov/api/v1/documents.json",
            "rate_limit_delay": rate_limit_delay,
            "include_full_text": include_full_text
        }
        
        logger.info(f"Completed Federal Register scraping: {documents_count} documents in {elapsed_time:.2f}s")
        
        return {
            "status": "success",
            "data": scraped_documents,
            "metadata": metadata,
            "output_format": output_format,
            "note": "Documents fetched from Federal Register API at federalregister.gov"
        }
        
    except Exception as e:
        logger.error(f"Federal Register scraping failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "data": [],
            "metadata": {}
        }
