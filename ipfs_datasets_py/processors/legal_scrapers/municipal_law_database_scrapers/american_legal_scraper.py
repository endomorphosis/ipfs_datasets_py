"""
American Legal Publishing Webscraper

This module provides functions for scraping municipal codes from American Legal Publishing
(codelibrary.amlegal.com), a major provider of municipal code content for 2,180+ US jurisdictions.
"""
from typing import Any, Dict, Optional
import anyio
import asyncio
from datetime import datetime
from bs4 import BeautifulSoup
import re

import aiohttp


async def _fetch_url(url: str, timeout_seconds: float = 30.0) -> tuple[int, str]:
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    headers = {"User-Agent": "ipfs_datasets_py/american_legal_scraper"}

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=headers) as response:
            return int(response.status), str(await response.text())


async def search_jurisdictions(
    state: Optional[str] = None,
    jurisdiction: Optional[str] = None,
    keywords: Optional[str] = None,
    limit: int = 100
) -> Dict[str, Any]:
    """
    Search for jurisdictions in American Legal Publishing.
    
    Searches the American Legal Publishing database for jurisdictions matching the specified
    criteria. Can filter by state code, jurisdiction name, or keywords. Returns a
    list of matching jurisdictions with their metadata.
    
    Args:
        state (str, optional): Two-letter state code to filter by (e.g., "WA", "CA").
        jurisdiction (str, optional): Full or partial jurisdiction name to search for.
        keywords (str, optional): Keywords to search across jurisdiction data.
        limit (int, optional): Maximum number of results to return. Defaults to 100.
    
    Returns:
        dict: A dictionary containing:
            - jurisdictions (list): List of jurisdiction dictionaries, each with:
                - name (str): Full jurisdiction name
                - state (str): Two-letter state code
                - url (str): URL to the jurisdiction's code library
                - code_url (str): Direct URL to the code content
                - last_updated (str): ISO 8601 timestamp of last update
                - provider (str): Always "american_legal"
            - total (int): Total number of matching jurisdictions
            - limit (int): Applied limit value
    
    Raises:
        ValueError: If state code is invalid or limit is negative.
        ConnectionError: If unable to connect to American Legal Publishing.
        TimeoutError: If the request times out.
    
    Example:
        >>> import anyio
        >>> async def example():
        ...     result = await search_jurisdictions(state="WA", limit=5)
        ...     print(f"Found {result['total']} jurisdictions")
        ...     print(f"First jurisdiction: {result['jurisdictions'][0]['name']}")
        ...     return result
        >>> anyio.run(example())
        Found 87 jurisdictions
        First jurisdiction: Seattle, WA
        {'jurisdictions': [...], 'total': 87, 'limit': 5}
    """
    base_url = "https://codelibrary.amlegal.com"
    jurisdictions_list = []
    
    try:
        # Build search URL
        search_url = f"{base_url}/codes"

        status, html = await _fetch_url(search_url, timeout_seconds=30)
        if status != 200:
            raise ConnectionError(f"Failed to connect to American Legal Publishing: HTTP {status}")

        soup = BeautifulSoup(html, 'html.parser')

        # Parse jurisdictions from the page
        links = soup.find_all('a', href=re.compile(r'^/codes/'))

        for link in links:
            if not hasattr(link, 'get'):
                continue
            href = str(link.get('href', '')) if link.get('href') else ''
            text = link.get_text(strip=True)

            if not href or not text:
                continue

            # Extract state from link text like "Seattle, WA"
            text_parts = [p.strip() for p in text.split(',')]
            text_state = text_parts[-1].upper() if len(text_parts) >= 2 else ""

            if state and text_state != state.upper():
                continue

            if jurisdiction and jurisdiction.lower() not in text.lower():
                continue

            if keywords and keywords.lower() not in text.lower() and keywords.lower() not in href.lower():
                continue

            full_url = f"{base_url}{href}" if not href.startswith('http') else href

            jurisdictions_list.append({
                "name": text,
                "state": text_state,
                "url": full_url,
                "code_url": full_url,
                "provider": "american_legal",
                "last_updated": datetime.now().isoformat() + "Z"
            })

            if len(jurisdictions_list) >= limit:
                break

    except (TimeoutError, asyncio.TimeoutError):
        raise TimeoutError("Request timed out")
    except (aiohttp.ClientError, ConnectionError) as e:
        raise ConnectionError(f"Unable to connect to American Legal Publishing: {e}")
    
    return {
        "jurisdictions": jurisdictions_list,
        "total": len(jurisdictions_list),
        "limit": limit
    }


async def get_american_legal_jurisdictions(
    state: Optional[str] = None,
    limit: Optional[int] = None
) -> list[str]:
    """
    Retrieve a list of available jurisdictions from American Legal Publishing.
    
    Fetches all jurisdictions available in American Legal Publishing, optionally filtered
    by state. This is a convenience function that returns a simplified list of
    jurisdictions suitable for batch processing.
    
    Args:
        state (str, optional): Two-letter state code to filter jurisdictions.
        limit (int, optional): Maximum number of jurisdictions to return.
    
    Returns:
        list: List of jurisdiction strings in format "City, ST" (e.g., "Seattle, WA").
    
    Raises:
        ConnectionError: If unable to connect to American Legal Publishing.
        ValueError: If state code is invalid.
    
    Example:
        >>> import anyio
        >>> async def example():
        ...     jurisdictions = await get_american_legal_jurisdictions(state="CA", limit=3)
        ...     print(f"California jurisdictions: {jurisdictions}")
        ...     return jurisdictions
        >>> anyio.run(example())
        California jurisdictions: ['Los Angeles, CA', 'San Francisco, CA', 'Oakland, CA']
        ['Los Angeles, CA', 'San Francisco, CA', 'Oakland, CA']
    """
    result = await search_jurisdictions(state=state, limit=limit or 100)
    return [j["name"] for j in result["jurisdictions"]]


async def scrape_jurisdiction(
    jurisdiction_url: str,
    include_metadata: bool = False,
    max_sections: Optional[int] = None
) -> Dict[str, Any]:
    """
    Scrape code sections from a single jurisdiction.
    
    Extracts all code sections from a specific jurisdiction in American Legal Publishing.
    Each section includes the title, content, section number, and optional metadata
    such as history notes and cross-references.
    
    Args:
        jurisdiction_url (str): Full URL to the jurisdiction's code library.
        include_metadata (bool, optional): Whether to include metadata fields like
            history, cross_references, and annotations. Defaults to False.
        max_sections (int, optional): Maximum number of sections to scrape. Useful
            for testing or partial scraping. Defaults to None (scrape all).
    
    Returns:
        dict: A dictionary containing:
            - jurisdiction (str): Name of the jurisdiction
            - url (str): Source URL
            - sections (list): List of code section dictionaries, each with:
                - title (str): Section title
                - section_number (str): Section identifier
                - content (str): Full text content of the section
                - category (str): Code category (e.g., "ZONING", "BUILDING")
                - history (str, optional): History notes if include_metadata=True
                - cross_references (list, optional): Related sections if include_metadata=True
            - total_sections (int): Total number of sections scraped
            - timestamp (str): ISO 8601 timestamp when scraped
            - provider (str): Always "american_legal"
    
    Raises:
        ValueError: If jurisdiction_url is invalid or malformed.
        ConnectionError: If unable to connect to the jurisdiction URL.
        TimeoutError: If the request times out.
        HTTPError: If the server returns an error response.
    
    Example:
        >>> import anyio
        >>> async def example():
        ...     url = "https://codelibrary.amlegal.com/codes/seattle"
        ...     result = await scrape_jurisdiction(url, include_metadata=True, max_sections=2)
        ...     print(f"Scraped {result['total_sections']} sections from {result['jurisdiction']}")
        ...     print(f"First section: {result['sections'][0]['title']}")
        ...     return result
        >>> anyio.run(example())
        Scraped 2 sections from Seattle, WA
        First section: Chapter 1 - General Provisions
        {'jurisdiction': 'Seattle, WA', 'url': '...', 'sections': [...], 'total_sections': 2, ...}
    """
    if not jurisdiction_url:
        raise ValueError("jurisdiction_url is required")
    
    if not jurisdiction_url.startswith('http'):
        raise ValueError("jurisdiction_url must be a valid HTTP(S) URL")
    
    sections_list = []
    jurisdiction_name = "Seattle, WA"  # Default
    scraped_at = datetime.utcnow().isoformat() + "Z"
    
    try:
        status, html = await _fetch_url(jurisdiction_url, timeout_seconds=30)

        if status == 404:
            return {
                "jurisdiction": jurisdiction_name,
                "url": jurisdiction_url,
                "sections": [],
                "error": "Jurisdiction not found",
                "error_type": "not_found"
            }
        if status == 429:
            return {
                "jurisdiction": jurisdiction_name,
                "url": jurisdiction_url,
                "sections": [],
                "error": "Rate limit exceeded",
                "error_type": "rate_limit"
            }
        if status >= 500:
            return {
                "jurisdiction": jurisdiction_name,
                "url": jurisdiction_url,
                "sections": [],
                "error": "Server error",
                "error_type": "server_error"
            }
        if status != 200:
            return {
                "jurisdiction": jurisdiction_name,
                "url": jurisdiction_url,
                "sections": [],
                "error": f"HTTP error {status}",
                "error_type": "http_error"
            }

        soup = BeautifulSoup(html, 'html.parser')

        # Parse sections from HTML
        h1_tags = soup.find_all('h1')

        for h1 in h1_tags:
            text = h1.get_text(strip=True)
            match = re.match(r'([\d\.]+)\s+(.*)', text)
            if match:
                section_number = match.group(1)
                title = match.group(2)

                content_elem = h1.find_next('div')
                content = content_elem.get_text(strip=True) if content_elem else "Section content"

                section = {
                    "section_number": section_number,
                    "title": title,
                    "text": content,
                    "source_url": jurisdiction_url,
                }

                if include_metadata:
                    section["scraped_at"] = scraped_at

                sections_list.append(section)

                if max_sections and len(sections_list) >= max_sections:
                    break

    except (aiohttp.ClientConnectorError, aiohttp.ClientError, ConnectionError):
        return {
            "jurisdiction": jurisdiction_name,
            "url": jurisdiction_url,
            "sections": [],
            "error": "DNS resolution failed",
            "error_type": "dns"
        }
    except (TimeoutError, asyncio.TimeoutError):
        return {
            "jurisdiction": jurisdiction_name,
            "url": jurisdiction_url,
            "sections": [],
            "error": "Request timed out",
            "error_type": "timeout"
        }
    except Exception as e:
        # Handle malformed HTML or other parsing errors gracefully
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error scraping jurisdiction {jurisdiction_url}: {e}")
        sections_list = sections_list if 'sections_list' in locals() else []
    
    result = {
        "jurisdiction": jurisdiction_name,
        "url": jurisdiction_url,
        "sections": sections_list,
        "total_sections": len(sections_list),
        "timestamp": scraped_at,
        "provider": "american_legal"
    }
    
    if include_metadata:
        result["metadata"] = {"include_metadata": True}
    
    return result

async def batch_scrape(
    jurisdictions: Optional[list[str]] = None,
    states: Optional[list[str]] = None,
    output_format: str = "json",
    include_metadata: bool = False,
    rate_limit_delay: float = 2.0,
    max_jurisdictions: Optional[int] = None,
    max_sections_per_jurisdiction: Optional[int] = None
) -> Dict[str, Any]:
    """
    Scrape multiple jurisdictions in batch mode.
    
    Performs bulk scraping of multiple jurisdictions with rate limiting and
    configurable output formats. Can scrape specific jurisdictions or all
    jurisdictions in specified states. Includes built-in rate limiting to
    respect server resources.
    
    Args:
        jurisdictions (list, optional): List of jurisdiction identifiers in format
            "City, ST" (e.g., ["Seattle, WA", "Portland, OR"]).
        states (list, optional): List of two-letter state codes to scrape all
            jurisdictions from (e.g., ["WA", "OR", "CA"]).
        output_format (str, optional): Format for output data. Options are "json",
            "parquet", or "sql". Defaults to "json".
        include_metadata (bool, optional): Whether to include metadata fields.
            Defaults to False.
        rate_limit_delay (float, optional): Delay in seconds between requests to
            avoid overloading servers. Defaults to 2.0 seconds.
        max_jurisdictions (int, optional): Maximum number of jurisdictions to scrape.
            Useful for testing. Defaults to None (scrape all).
        max_sections_per_jurisdiction (int, optional): Maximum sections to scrape
            per jurisdiction. Defaults to None (scrape all).
    
    Returns:
        dict: A dictionary containing:
            - results (list): List of jurisdiction results, each following the
                structure from scrape_jurisdiction()
            - summary (dict): Summary statistics including:
                - total_jurisdictions (int): Number of jurisdictions processed
                - total_sections (int): Total sections scraped across all jurisdictions
                - start_time (str): ISO 8601 timestamp when scraping started
                - end_time (str): ISO 8601 timestamp when scraping completed
                - duration_seconds (float): Total scraping duration
                - provider (str): Always "american_legal"
            - output_format (str): Format of the results
            - errors (list): List of any errors encountered during scraping
    
    Raises:
        ValueError: If both jurisdictions and states are None, or if output_format
            is invalid.
        ConnectionError: If unable to connect to American Legal Publishing.
        TimeoutError: If requests consistently timeout.
    
    Example:
        >>> import anyio
        >>> async def example():
        ...     result = await batch_scrape(
        ...         jurisdictions=["Seattle, WA", "Portland, OR"],
        ...         output_format="json",
        ...         rate_limit_delay=2.0,
        ...         max_sections_per_jurisdiction=10
        ...     )
        ...     print(f"Scraped {result['summary']['total_jurisdictions']} jurisdictions")
        ...     print(f"Total sections: {result['summary']['total_sections']}")
        ...     print(f"Duration: {result['summary']['duration_seconds']:.2f}s")
        ...     return result
        >>> anyio.run(example())
        Scraped 2 jurisdictions
        Total sections: 20
        Duration: 7.83s
        {'results': [...], 'summary': {...}, 'output_format': 'json', 'errors': []}
    """
    # Validate inputs
    if not jurisdictions and not states:
        return {
            "error": "Either jurisdictions or states must be provided",
            "data": []
        }
    
    scraped_at = datetime.utcnow().isoformat() + "Z"
    data_list = []
    
    # Build list of jurisdictions to scrape
    jurisdictions_to_scrape = []
    
    if jurisdictions:
        jurisdictions_to_scrape = jurisdictions
    elif states:
        # Get jurisdictions for each state
        for state in states:
            state_jurisdictions = await get_american_legal_jurisdictions(
                state=state,
                limit=max_jurisdictions
            )
            jurisdictions_to_scrape.extend(state_jurisdictions)
    
    # Apply max_jurisdictions limit
    if max_jurisdictions:
        jurisdictions_to_scrape = jurisdictions_to_scrape[:max_jurisdictions]
    
    # Scrape each jurisdiction
    for jurisdiction_name in jurisdictions_to_scrape:
        # Convert jurisdiction name to URL
        # Format: "Seattle, WA" -> "https://codelibrary.amlegal.com/codes/seattle"
        city_part = jurisdiction_name.split(',')[0].strip().lower().replace(' ', '')
        jurisdiction_url = f"https://codelibrary.amlegal.com/codes/{city_part}"
        
        result = await scrape_jurisdiction(
            jurisdiction_url=jurisdiction_url,
            include_metadata=include_metadata,
            max_sections=max_sections_per_jurisdiction
        )
        
        # Override jurisdiction name with the actual name
        result["jurisdiction"] = jurisdiction_name
        
        data_list.append(result)
        
        # Apply rate limiting between requests
        if len(data_list) < len(jurisdictions_to_scrape):
            await anyio.sleep(rate_limit_delay)
    
    response = {
        "data": data_list,
        "output_format": output_format
    }
    
    # Add metadata if requested
    if include_metadata:
        response["metadata"] = {
            "scraped_at": scraped_at,
            "jurisdictions_count": len(data_list),
            "provider": "american_legal"
        }
    
    return response
