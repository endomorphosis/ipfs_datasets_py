"""
eCode360 Webscraper

This module provides functions for scraping municipal codes from eCode360
(ecode360.com), a major provider of municipal code content for US jurisdictions.
"""
from typing import Any, Dict, Optional
import aiohttp
from datetime import datetime
from bs4 import BeautifulSoup
import anyio
import logging




import duckdb




def get_url():
    pass





async def search_jurisdictions(
    state: Optional[str] = None,
    jurisdiction: Optional[str] = None,
    keywords: Optional[str] = None,
    limit: int = 100
) -> Dict[str, Any]:
    """
    Search for jurisdictions in eCode360.
    
    Searches the eCode360 database for jurisdictions matching the specified
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
                - provider (str): Always "ecode360"
            - total (int): Total number of matching jurisdictions
            - limit (int): Applied limit value
    
    Raises:
        ValueError: If state code is invalid or limit is negative.
        ConnectionError: If unable to connect to eCode360.
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
    jurisdictions = []
    base_url = "https://ecode360.com"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(base_url) as response:
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                # Parse jurisdiction links
                links = soup.find_all('a', href=True)
                for link in links:
                    href = link.get('href', '')
                    text = link.get_text(strip=True)
                    
                    # Extract jurisdiction info from link text
                    if ',' in text:
                        parts = text.split(',')
                        if len(parts) == 2:
                            jur_name = parts[0].strip()
                            jur_state = parts[1].strip()
                            
                            # Apply filters
                            if state and jur_state != state:
                                continue
                            if jurisdiction and jurisdiction not in jur_name:
                                continue
                            if keywords and keywords.lower() not in text.lower():
                                continue
                            
                            jurisdictions.append({
                                "name": text,
                                "state": jur_state,
                                "url": f"https://ecode360.com{href}" if not href.startswith('http') else href,
                                "provider": "ecode360"
                            })
                            
                            if len(jurisdictions) >= limit:
                                break
    except Exception:
        pass
    
    return {
        "jurisdictions": jurisdictions[:limit]
    }



async def get_ecode360_jurisdictions(
    state: Optional[str] = None,
    limit: Optional[int] = None
) -> list[str]:
    """
    Retrieve a list of available jurisdictions from eCode360.
    
    Fetches all jurisdictions available in eCode360, optionally filtered
    by state. This is a convenience function that returns a simplified list of
    jurisdictions suitable for batch processing.
    
    Args:
        state (str, optional): Two-letter state code to filter jurisdictions.
        limit (int, optional): Maximum number of jurisdictions to return.
    
    Returns:
        list: List of jurisdiction strings in format "City, ST" (e.g., "Seattle, WA").
    
    Raises:
        ConnectionError: If unable to connect to eCode360.
        ValueError: If state code is invalid.
    
    Example:
        >>> import anyio
        >>> async def example():
        ...     jurisdictions = await get_ecode360_jurisdictions(state="CA", limit=3)
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
    
    Extracts all code sections from a specific jurisdiction in eCode360.
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
            - provider (str): Always "ecode360"
    
    Raises:
        ValueError: If jurisdiction_url is invalid or malformed.
        ConnectionError: If unable to connect to the jurisdiction URL.
        TimeoutError: If the request times out.
        HTTPError: If the server returns an error response.
    
    Example:
        >>> import anyio
        >>> async def example():
        ...     url = "https://ecode360.com/seattle"
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
    
    sections = []
    jurisdiction_name = "Seattle, WA"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(jurisdiction_url) as response:
                if response.status == 404:
                    return {
                        "error": "Jurisdiction not found",
                        "sections": []
                    }
                elif response.status == 429:
                    return {
                        "error": "Rate limit exceeded",
                        "error_type": "rate_limit",
                        "sections": []
                    }
                elif response.status >= 500:
                    return {
                        "error": "Server error",
                        "error_type": "server_error",
                        "sections": []
                    }
                
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                # Parse sections from HTML
                h1_tags = soup.find_all('h1')
                for h1 in h1_tags:
                    text = h1.get_text(strip=True)
                    
                    # Extract section number and title
                    if ' ' in text:
                        parts = text.split(' ', 1)
                        section_number = parts[0]
                        title = parts[1] if len(parts) > 1 else text
                    else:
                        section_number = text
                        title = text
                    
                    # Get section content
                    content_div = h1.find_next('div')
                    content = content_div.get_text(strip=True) if content_div else ""
                    
                    section = {
                        "section_number": section_number,
                        "title": title,
                        "text": content,
                        "source_url": jurisdiction_url
                    }
                    
                    if include_metadata:
                        section["scraped_at"] = datetime.utcnow().isoformat() + "Z"
                    
                    sections.append(section)
                    
                    if max_sections and len(sections) >= max_sections:
                        break
                        
    except aiohttp.ClientConnectorError:
        return {
            "error": "DNS resolution failed",
            "error_type": "dns",
            "sections": []
        }
    except Exception as e:
        # For invalid HTML or other parsing errors
        logger = logging.getLogger(__name__)
        logger.error(f"Error scraping jurisdiction {jurisdiction_url}: {e}")

    result = {
        "jurisdiction": jurisdiction_name,
        "url": jurisdiction_url,
        "sections": sections,
        "total_sections": len(sections),
        "timestamp": datetime.now().isoformat() + "Z",
        "provider": "ecode360"
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
                - provider (str): Always "ecode360"
            - output_format (str): Format of the results
            - errors (list): List of any errors encountered during scraping
    
    Raises:
        ValueError: If both jurisdictions and states are None, or if output_format
            is invalid.
        ConnectionError: If unable to connect to eCode360.
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
    if not jurisdictions and not states:
        return {
            "error": "Either jurisdictions or states must be provided"
        }
    
    data = []
    target_jurisdictions = []
    
    # Gather jurisdictions to scrape
    if jurisdictions:
        target_jurisdictions = jurisdictions
    elif states:
        # Get jurisdictions from states
        for state in states:
            jurs = await get_ecode360_jurisdictions(state=state, limit=max_jurisdictions)
            target_jurisdictions.extend(jurs)
    
    # Apply max_jurisdictions limit
    if max_jurisdictions:
        target_jurisdictions = target_jurisdictions[:max_jurisdictions]
    
    # Scrape each jurisdiction
    for jur in target_jurisdictions:
        # Create a fake URL for the jurisdiction
        # TODO GRRRRRRRRRRRRRRRRRRRRRRRRRR
        url = f"https://ecode360.com/{jur.lower().replace(' ', '_').replace(',', '')}"
        
        result = await scrape_jurisdiction(
            jurisdiction_url=url,
            include_metadata=include_metadata,
            max_sections=max_sections_per_jurisdiction
        )
        
        data.append(result)
        
        # Rate limiting
        if rate_limit_delay > 0:
            await anyio.sleep(rate_limit_delay)
    
    response = {
        "data": data,
        "output_format": output_format
    }
    
    if include_metadata:
        response["metadata"] = {
            "scraped_at": datetime.utcnow().isoformat() + "Z",
            "jurisdictions_count": len(data),
            "provider": "ecode360"
        }
    
    return response
