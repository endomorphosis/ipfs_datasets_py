"""Federal Register scraper for building federal regulations datasets.

This tool scrapes the Federal Register from federalregister.gov
and provides structured access to federal regulations and notices.
"""
import logging
import time
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta, date
from urllib.parse import urlparse
import ipaddress
import socket
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

FEDERAL_REGISTER_API_URL = "https://www.federalregister.gov/api/v1/documents.json"
FEDERAL_REGISTER_MAX_PER_PAGE = 1000
FEDERAL_REGISTER_COUNT_CAP = 10000

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


def _safe_get_federal_register_url(url: str) -> Optional[requests.Response]:
    """
    Safely perform a GET request to a Federal Register URL.

    Enforces:
      - http/https scheme
      - Hostname restricted to federalregister.gov or its subdomains
      - Resolved IP address is not private, loopback, or otherwise non-public
      - No redirects to other hosts
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            logger.warning(f"Blocked Federal Register request with disallowed scheme: {url!r}")
            return None

        hostname = parsed.hostname or ""
        if not hostname or not (
            hostname == "federalregister.gov"
            or hostname.endswith(".federalregister.gov")
        ):
            logger.warning(f"Blocked Federal Register request with disallowed host: {url!r}")
            return None

        try:
            ip_str = socket.gethostbyname(hostname)
            ip = ipaddress.ip_address(ip_str)
        except Exception as e:
            logger.warning(f"Failed to resolve Federal Register host {hostname!r}: {e}")
            return None

        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
        ):
            logger.warning(
                f"Blocked Federal Register request to non-public IP {ip_str} for URL {url!r}"
            )
            return None

        # Use a session and disallow redirects to avoid being bounced to an unsafe host.
        with requests.Session() as session:
            response = session.get(url, timeout=30, allow_redirects=False)
        return response
    except Exception as e:
        logger.warning(f"Safe Federal Register request failed for URL {url!r}: {e}")
        return None


def _make_retry_session() -> requests.Session:
    """Create a requests session with conservative retry/backoff behavior."""
    session = requests.Session()
    retry_strategy = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,
        backoff_factor=1.0,
        status_forcelist=[408, 429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _normalize_document(result: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize Federal Register API result objects to scraper output schema."""
    agencies = result.get("agencies") or []
    agency_names = [a.get("name", "") for a in agencies if isinstance(a, dict)]
    agency_slugs = [str(a.get("slug", "")).upper() for a in agencies if isinstance(a, dict)]

    return {
        "document_number": result.get("document_number", ""),
        "title": result.get("title", ""),
        "agency": agency_names[0] if agency_names else "",
        "agencies": agency_names,
        "agency_abbr": agency_slugs[0] if agency_slugs else "",
        "agency_abbrs": agency_slugs,
        "document_type": result.get("type", ""),
        "publication_date": result.get("publication_date", ""),
        "abstract": result.get("abstract", "")[:500] if result.get("abstract") else "",
        "citation": result.get("citation", ""),
        "fr_url": result.get("html_url", ""),
        "pdf_url": result.get("pdf_url", ""),
        "raw_text_url": result.get("raw_text_url", ""),
        "signing_date": result.get("signing_date", ""),
        "effective_date": result.get("effective_on") or result.get("effective_date") or "",
        "docket_ids": result.get("docket_ids", []),
        "regulation_id_numbers": result.get("regulation_id_numbers", []),
        "topics": result.get("topics", []),
        "significant": result.get("significant", False),
    }


def _parse_iso_date(value: str) -> date:
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def _midpoint_date(start: date, end: date) -> date:
    delta_days = (end - start).days
    return start + timedelta(days=max(0, delta_days // 2))


async def _search_with_date_partitioning(
    *,
    agencies: Optional[List[str]],
    start_date: str,
    end_date: str,
    document_types: Optional[List[str]],
    keywords: Optional[str],
    page_size: int = 1000,
) -> Dict[str, Any]:
    """Collect documents by recursively splitting date ranges that hit API count caps."""
    ranges_to_query: List[tuple[date, date]] = [(_parse_iso_date(start_date), _parse_iso_date(end_date))]
    queried_ranges = 0
    split_ranges = 0
    documents: List[Dict[str, Any]] = []
    seen_doc_numbers = set()
    failed_ranges: List[Dict[str, Any]] = []

    while ranges_to_query:
        range_start, range_end = ranges_to_query.pop(0)
        queried_ranges += 1

        result = await search_federal_register(
            agencies=agencies,
            start_date=range_start.isoformat(),
            end_date=range_end.isoformat(),
            document_types=document_types,
            keywords=keywords,
            limit=0,
            fetch_all=True,
            page_size=page_size,
        )

        total_available = int(result.get("total_available") or 0)
        result_documents = list(result.get("documents") or [])
        result_count = int(result.get("count") or len(result_documents))
        range_is_splittable = range_start < range_end

        if result.get("status") != "success":
            should_split = range_is_splittable and (
                total_available >= FEDERAL_REGISTER_COUNT_CAP
                or result_count >= FEDERAL_REGISTER_COUNT_CAP
                or len(result_documents) >= FEDERAL_REGISTER_COUNT_CAP
            )
            if should_split:
                split_point = _midpoint_date(range_start, range_end)
                left_end = split_point
                right_start = split_point + timedelta(days=1)
                if left_end >= range_start and right_start <= range_end:
                    split_ranges += 1
                    ranges_to_query.insert(0, (right_start, range_end))
                    ranges_to_query.insert(0, (range_start, left_end))
                    continue

            failed_ranges.append(
                {
                    "start_date": range_start.isoformat(),
                    "end_date": range_end.isoformat(),
                    "error": result.get("error", "unknown error"),
                }
            )
            continue

        if total_available >= FEDERAL_REGISTER_COUNT_CAP and range_is_splittable:
            split_point = _midpoint_date(range_start, range_end)
            left_end = split_point
            right_start = split_point + timedelta(days=1)
            if left_end < range_start or right_start > range_end:
                # Defensive fallback, keep current results if split boundaries degrade.
                pass
            else:
                split_ranges += 1
                ranges_to_query.insert(0, (right_start, range_end))
                ranges_to_query.insert(0, (range_start, left_end))
                continue

        for doc in result_documents:
            doc_number = str(doc.get("document_number") or "")
            if doc_number and doc_number in seen_doc_numbers:
                continue
            if doc_number:
                seen_doc_numbers.add(doc_number)
            documents.append(doc)

    return {
        "status": "success" if not failed_ranges else "partial_success",
        "documents": documents,
        "count": len(documents),
        "queried_ranges": queried_ranges,
        "split_ranges": split_ranges,
        "failed_ranges": failed_ranges,
    }


async def search_federal_register(
    agencies: Optional[List[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    document_types: Optional[List[str]] = None,
    keywords: Optional[str] = None,
    limit: int = 100,
    fetch_all: bool = False,
    page_size: int = 1000,
    max_pages: Optional[int] = None,
    request_timeout: float = 30.0,
) -> Dict[str, Any]:
    """Search Federal Register documents.
    
    Args:
        agencies: List of agency abbreviations (e.g., ["EPA", "FDA"])
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        document_types: Types of documents (e.g., ["RULE", "NOTICE", "PRORULE"])
        keywords: Search keywords
        limit: Maximum number of results. Use 0 for unbounded (fetch all).
        fetch_all: If True, page through the full result set.
        page_size: Per-page API size (capped at 1000 by Federal Register).
        max_pages: Optional upper bound on pages when fetch_all=True.
        request_timeout: Timeout for each page request in seconds.
    
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
        
        normalized_limit = int(limit) if int(limit) >= 0 else 0
        if normalized_limit == 0:
            fetch_all = True

        effective_page_size = max(1, min(int(page_size), FEDERAL_REGISTER_MAX_PER_PAGE))

        # Build search parameters
        search_params = {
            "agencies": agencies or [],
            "start_date": start_date,
            "end_date": end_date,
            "document_types": document_types or ["RULE", "NOTICE", "PRORULE"],
            "keywords": keywords,
            "limit": normalized_limit,
            "fetch_all": bool(fetch_all),
            "page_size": effective_page_size,
            "max_pages": max_pages,
        }
        
        # Query the Federal Register API
        # API endpoint: https://www.federalregister.gov/api/v1/documents.json
        # Documentation: https://www.federalregister.gov/developers/documentation/api/v1
        
        try:
            api_base_params = {
                "per_page": effective_page_size,
                "order": "newest",
            }
            
            # Add date filters
            if start_date:
                api_base_params["conditions[publication_date][gte]"] = start_date
            if end_date:
                api_base_params["conditions[publication_date][lte]"] = end_date
            
            # Add agency filter
            if agencies:
                # Federal Register API expects agency slugs. Allow pre-normalized values.
                api_base_params["conditions[agencies][]"] = [str(a).strip().lower() for a in agencies if str(a).strip()]
            
            # Add document type filter
            if document_types:
                api_base_params["conditions[type][]"] = document_types
            
            # Add keyword search
            if keywords:
                api_base_params["conditions[term]"] = keywords
            
            logger.info("Querying Federal Register API: %s", FEDERAL_REGISTER_API_URL)

            documents: List[Dict[str, Any]] = []
            seen_doc_numbers = set()
            current_page = 1
            total_available = None
            pages_fetched = 0

            with _make_retry_session() as session:
                while True:
                    if max_pages is not None and pages_fetched >= int(max_pages):
                        break
                    if not fetch_all and normalized_limit > 0 and len(documents) >= normalized_limit:
                        break

                    api_params = dict(api_base_params)
                    api_params["page"] = current_page

                    response = session.get(
                        FEDERAL_REGISTER_API_URL,
                        params=api_params,
                        timeout=float(request_timeout),
                    )

                    if int(response.status_code) != 200:
                        logger.warning("Federal Register API returned status %s on page %s", response.status_code, current_page)
                        return {
                            "status": "error",
                            "error": f"API request failed with status {response.status_code}: {response.text[:200]}",
                            "documents": documents,
                            "count": len(documents),
                            "total_available": total_available if total_available is not None else len(documents),
                            "pages_fetched": pages_fetched,
                            "search_params": search_params,
                            "api_endpoint": FEDERAL_REGISTER_API_URL,
                        }

                    data = response.json()
                    results = data.get("results", [])
                    pages_fetched += 1

                    if total_available is None:
                        total_available = int(data.get("count", 0))

                    if not results:
                        break

                    for result in results:
                        normalized = _normalize_document(result)
                        doc_number = str(normalized.get("document_number") or "")
                        if doc_number and doc_number in seen_doc_numbers:
                            continue
                        if doc_number:
                            seen_doc_numbers.add(doc_number)
                        documents.append(normalized)

                        if not fetch_all and normalized_limit > 0 and len(documents) >= normalized_limit:
                            break

                    if not fetch_all and normalized_limit > 0 and len(documents) >= normalized_limit:
                        break
                    if len(results) < effective_page_size:
                        break

                    current_page += 1

            if not fetch_all and normalized_limit > 0:
                documents = documents[:normalized_limit]

            return {
                "status": "success",
                "documents": documents,
                "count": len(documents),
                "total_available": total_available if total_available is not None else len(documents),
                "pages_fetched": pages_fetched,
                "search_params": search_params,
                "api_endpoint": FEDERAL_REGISTER_API_URL,
                "note": "Results from Federal Register API at federalregister.gov",
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
    keywords: Optional[str] = None,
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
        keywords: Optional Federal Register term query
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
        
        # Validate and process agencies. For comprehensive ingest, agencies=None scrapes globally.
        if agencies is None or "all" in agencies:
            selected_agencies = []
        else:
            selected_agencies = [a for a in agencies if a in FEDERAL_AGENCIES]
            if not selected_agencies:
                return {
                    "status": "error",
                    "error": "No valid agencies specified",
                    "data": [],
                    "metadata": {}
                }
        
        if selected_agencies:
            logger.info("Starting Federal Register scraping: %s agencies, %s to %s", len(selected_agencies), start_date, end_date)
        else:
            logger.info("Starting Federal Register scraping: all agencies, %s to %s", start_date, end_date)
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
        seen_doc_numbers = set()
        failed_agencies: List[Dict[str, Any]] = []
        
        scrape_targets = selected_agencies if selected_agencies else [None]
        partition_stats: Dict[str, Any] = {
            "enabled": False,
            "queried_ranges": 0,
            "split_ranges": 0,
            "failed_ranges": 0,
        }

        # Use either per-agency fetches or one global fetch.
        for agency in scrape_targets:
            if max_documents and documents_count >= max_documents:
                logger.info("Reached max_documents limit of %s", max_documents)
                break

            agency_name = FEDERAL_AGENCIES.get(agency, "ALL") if agency else "ALL"
            logger.info("Scraping Federal Register target: %s", agency_name)

            use_partitioning = (
                agency is None
                and not max_documents
                and bool(start_date)
                and bool(end_date)
            )

            if use_partitioning:
                partition_stats["enabled"] = True
                partitioned = await _search_with_date_partitioning(
                    agencies=None,
                    start_date=start_date,
                    end_date=end_date,
                    document_types=document_types,
                    keywords=keywords,
                    page_size=1000,
                )
                search_result = {
                    "status": "success" if partitioned.get("status") == "success" else "partial_success",
                    "documents": partitioned.get("documents", []),
                }
                partition_stats["queried_ranges"] = int(partitioned.get("queried_ranges") or 0)
                partition_stats["split_ranges"] = int(partitioned.get("split_ranges") or 0)
                partition_stats["failed_ranges"] = len(partitioned.get("failed_ranges") or [])
                partition_stats["failed_range_details"] = partitioned.get("failed_ranges", [])[:20]
            elif agency:
                agency_keywords = FEDERAL_AGENCIES.get(agency, agency)
                search_result = await search_federal_register(
                    agencies=None,
                    start_date=start_date,
                    end_date=end_date,
                    document_types=document_types,
                    keywords=agency_keywords,
                    limit=max_documents if max_documents else 0,
                    fetch_all=not bool(max_documents),
                    page_size=1000,
                )
            else:
                search_result = await search_federal_register(
                    agencies=None,
                    start_date=start_date,
                    end_date=end_date,
                    document_types=document_types,
                    keywords=keywords,
                    limit=max_documents if max_documents else 0,
                    fetch_all=not bool(max_documents),
                    page_size=1000,
                )

            if search_result.get("status") != "success":
                failed_agencies.append(
                    {
                        "agency": agency,
                        "agency_name": agency_name,
                        "error": search_result.get("error", "unknown error"),
                    }
                )
                continue

            for doc in search_result.get("documents", []):
                if max_documents and documents_count >= max_documents:
                    break

                doc_number = str(doc.get("document_number") or "")
                if doc_number and doc_number in seen_doc_numbers:
                    continue
                if doc_number:
                    seen_doc_numbers.add(doc_number)

                # For agency-specific scraping, apply an explicit client-side filter.
                if agency:
                    agency_match = False
                    for doc_agency in doc.get("agency_abbrs", []):
                        if str(doc_agency).upper() == str(agency).upper():
                            agency_match = True
                            break
                    if not agency_match:
                        continue

                # Optionally fetch full text
                if include_full_text and doc.get("raw_text_url"):
                    raw_url = doc.get("raw_text_url")
                    parsed_url = urlparse(str(raw_url))
                    is_allowed_scheme = parsed_url.scheme in ("http", "https")
                    hostname = parsed_url.hostname or ""
                    is_federalregister_host = bool(hostname) and (
                        hostname == "federalregister.gov" or hostname.endswith(".federalregister.gov")
                    )
                    if _is_safe_federal_register_url(str(raw_url)) and is_allowed_scheme and is_federalregister_host:
                        try:
                            text_response = _safe_get_federal_register_url(str(raw_url))
                            if text_response is not None and text_response.status_code == 200:
                                doc["full_text"] = text_response.text
                            else:
                                if text_response is not None:
                                    logger.warning(
                                        "Full text fetch for %s returned status %s",
                                        doc.get("document_number"),
                                        text_response.status_code,
                                    )
                                doc["full_text"] = None
                        except Exception as e:
                            logger.warning("Failed to fetch full text for %s: %s", doc.get("document_number"), e)
                            doc["full_text"] = None
                    else:
                        logger.warning(
                            "Skipping full text fetch for %s: unsafe raw_text_url=%r",
                            doc.get("document_number"),
                            raw_url,
                        )

                doc["scraped_at"] = datetime.now().isoformat()
                scraped_documents.append(doc)
                documents_count += 1

            if rate_limit_delay > 0:
                time.sleep(rate_limit_delay)
        
        elapsed_time = time.time() - start_time
        
        metadata = {
            "agencies_scraped": selected_agencies if selected_agencies else ["all"],
            "agencies_count": len(selected_agencies) if selected_agencies else 0,
            "documents_count": documents_count,
            "deduplicated_documents": len(seen_doc_numbers),
            "date_range": {
                "start_date": start_date,
                "end_date": end_date
            },
            "elapsed_time_seconds": elapsed_time,
            "scraped_at": datetime.now().isoformat(),
            "source": "Federal Register API (federalregister.gov)",
            "api_endpoint": FEDERAL_REGISTER_API_URL,
            "rate_limit_delay": rate_limit_delay,
            "include_full_text": include_full_text,
            "failed_agencies": failed_agencies,
            "partitioning": partition_stats,
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


__all__ = [
    "search_federal_register",
    "scrape_federal_register",
]
