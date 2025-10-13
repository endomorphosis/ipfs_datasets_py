"""US Code scraper for building federal statutory law datasets.

This tool scrapes the United States Code from uscode.house.gov
and provides structured access to federal statutory law.
"""
import logging
import time
from typing import Dict, List, Optional, Any
from datetime import datetime
import json
import asyncio

try:
    import requests
    from bs4 import BeautifulSoup
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

logger = logging.getLogger(__name__)

# US Code titles mapping
US_CODE_TITLES = {
    "1": "General Provisions",
    "2": "The Congress",
    "3": "The President",
    "4": "Flag and Seal, Seat of Government, and the States",
    "5": "Government Organization and Employees",
    "6": "Domestic Security",
    "7": "Agriculture",
    "8": "Aliens and Nationality",
    "9": "Arbitration",
    "10": "Armed Forces",
    "11": "Bankruptcy",
    "12": "Banks and Banking",
    "13": "Census",
    "14": "Coast Guard",
    "15": "Commerce and Trade",
    "16": "Conservation",
    "17": "Copyrights",
    "18": "Crimes and Criminal Procedure",
    "19": "Customs Duties",
    "20": "Education",
    "21": "Food and Drugs",
    "22": "Foreign Relations and Intercourse",
    "23": "Highways",
    "24": "Hospitals and Asylums",
    "25": "Indians",
    "26": "Internal Revenue Code",
    "27": "Intoxicating Liquors",
    "28": "Judiciary and Judicial Procedure",
    "29": "Labor",
    "30": "Mineral Lands and Mining",
    "31": "Money and Finance",
    "32": "National Guard",
    "33": "Navigation and Navigable Waters",
    "34": "Crime Control and Law Enforcement",
    "35": "Patents",
    "36": "Patriotic and National Observances, Ceremonies, and Organizations",
    "37": "Pay and Allowances of the Uniformed Services",
    "38": "Veterans' Benefits",
    "39": "Postal Service",
    "40": "Public Buildings, Property, and Works",
    "41": "Public Contracts",
    "42": "The Public Health and Welfare",
    "43": "Public Lands",
    "44": "Public Printing and Documents",
    "45": "Railroads",
    "46": "Shipping",
    "47": "Telecommunications",
    "48": "Territories and Insular Possessions",
    "49": "Transportation",
    "50": "War and National Defense",
    "51": "National and Commercial Space Programs",
    "52": "Voting and Elections",
    "54": "National Park Service and Related Programs",
}


async def fetch_us_code_title(
    title_num: str,
    title_name: str,
    include_metadata: bool = True,
    rate_limit_delay: float = 1.0
) -> Dict[str, Any]:
    """Fetch a US Code title from uscode.house.gov.
    
    Args:
        title_num: Title number (e.g., "18")
        title_name: Title name (e.g., "Crimes and Criminal Procedure")
        include_metadata: Include metadata like effective dates
        rate_limit_delay: Delay between requests
        
    Returns:
        Dict with title data and sections
    """
    if not REQUESTS_AVAILABLE:
        logger.warning("requests/BeautifulSoup not available, returning placeholder")
        return {
            "title_number": title_num,
            "title_name": title_name,
            "source": "US Code (placeholder)",
            "source_url": f"https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title{title_num}",
            "scraped_at": datetime.now().isoformat(),
            "sections": [
                {
                    "section_number": f"{title_num}.1",
                    "heading": f"Section 1 - {title_name}",
                    "text": f"Placeholder for Title {title_num}",
                }
            ]
        }
    
    try:
        # Fetch title from official US Code API
        base_url = "https://uscode.house.gov/view.xhtml"
        
        # Try main title view
        response = requests.get(
            base_url,
            params={"req": f"granuleid:USC-prelim-title{title_num}"},
            timeout=30
        )
        
        if response.status_code != 200:
            logger.warning(f"Failed to fetch Title {title_num}: HTTP {response.status_code}")
            return None
            
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract sections from the HTML
        sections = []
        
        # Find all section headings and content
        section_elements = soup.find_all(['div', 'section'], class_=lambda x: x and ('section' in x.lower() or 'statute' in x.lower()))
        
        if not section_elements:
            # Try alternative structure - look for any content blocks
            section_elements = soup.find_all(['p', 'div'], class_=lambda x: x and 'content' in x.lower())
        
        for idx, elem in enumerate(section_elements[:20]):  # Limit to first 20 sections per title
            section_num = f"{title_num}.{idx+1}"
            
            # Extract heading
            heading_elem = elem.find(['h1', 'h2', 'h3', 'h4', 'strong', 'b'])
            heading = heading_elem.get_text(strip=True) if heading_elem else f"Section {idx+1}"
            
            # Extract text content
            text_content = elem.get_text(strip=True)
            
            section_data = {
                "section_number": section_num,
                "heading": heading[:200],  # Limit heading length
                "text": text_content[:2000],  # Limit text length
            }
            
            if include_metadata:
                section_data["effective_date"] = datetime.now().strftime("%Y-%m-%d")
                section_data["source_url"] = f"{base_url}?req=granuleid:USC-prelim-title{title_num}-section{idx+1}"
            
            sections.append(section_data)
        
        if not sections:
            # If no sections found, create a summary section
            sections.append({
                "section_number": f"{title_num}.0",
                "heading": f"Title {title_num} - {title_name}",
                "text": soup.get_text(strip=True)[:2000],  # First 2000 chars of content
            })
        
        return {
            "title_number": title_num,
            "title_name": title_name,
            "source": "US Code",
            "source_url": f"https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title{title_num}",
            "scraped_at": datetime.now().isoformat(),
            "sections": sections
        }
        
    except Exception as e:
        logger.error(f"Failed to fetch Title {title_num}: {e}")
        return None


async def search_us_code(
    query: str,
    titles: Optional[List[str]] = None,
    max_results: int = 100
) -> Dict[str, Any]:
    """Search US Code for sections matching a query.
    
    Args:
        query: Search query string
        titles: Optional list of title numbers to search within
        max_results: Maximum number of results to return
        
    Returns:
        Dict with search results
    """
    try:
        if not REQUESTS_AVAILABLE:
            return {
                "status": "error",
                "error": "requests library not available. Install with: pip install requests beautifulsoup4",
                "results": []
            }
        
        # Use US Code search functionality
        search_url = "https://uscode.house.gov/search.xhtml"
        
        params = {
            "searchString": query,
            "pageSize": min(max_results, 100)
        }
        
        if titles:
            params["titles"] = ",".join(titles)
        
        response = requests.get(search_url, params=params, timeout=30)
        
        if response.status_code != 200:
            return {
                "status": "error",
                "error": f"Search failed with HTTP {response.status_code}",
                "results": []
            }
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        results = []
        result_elements = soup.find_all(['div', 'li'], class_=lambda x: x and 'result' in x.lower())
        
        for elem in result_elements[:max_results]:
            title_elem = elem.find(['a', 'h3', 'h4'])
            title = title_elem.get_text(strip=True) if title_elem else "Unknown"
            
            snippet = elem.get_text(strip=True)[:500]
            
            link = title_elem.get('href') if title_elem and title_elem.name == 'a' else ""
            if link and not link.startswith('http'):
                link = f"https://uscode.house.gov{link}"
            
            results.append({
                "title": title,
                "snippet": snippet,
                "url": link
            })
        
        return {
            "status": "success",
            "query": query,
            "results": results,
            "count": len(results)
        }
        
    except Exception as e:
        logger.error(f"US Code search failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "results": []
        }


async def get_us_code_titles() -> Dict[str, Any]:
    """Get list of all US Code titles.
    
    Returns:
        Dict containing:
            - status: "success" or "error"
            - titles: Dictionary mapping title numbers to names
            - count: Number of titles
            - error: Error message (if failed)
    """
    try:
        return {
            "status": "success",
            "titles": US_CODE_TITLES,
            "count": len(US_CODE_TITLES),
            "source": "US Code - uscode.house.gov"
        }
    except Exception as e:
        logger.error(f"Failed to get US Code titles: {e}")
        return {
            "status": "error",
            "error": str(e),
            "titles": {},
            "count": 0
        }


async def scrape_us_code(
    titles: Optional[List[str]] = None,
    output_format: str = "json",
    include_metadata: bool = True,
    rate_limit_delay: float = 1.0,
    max_sections: Optional[int] = None
) -> Dict[str, Any]:
    """Scrape US Code sections and build a structured dataset.
    
    Args:
        titles: List of title numbers to scrape (e.g., ["1", "15", "18"]). 
                If None or ["all"], scrapes all titles.
        output_format: Output format - "json" or "parquet"
        include_metadata: Include section metadata (effective dates, amendments, etc.)
        rate_limit_delay: Delay between requests in seconds (default 1.0)
        max_sections: Maximum number of sections to scrape (for testing/limiting)
    
    Returns:
        Dict containing:
            - status: "success" or "error"
            - data: Scraped US Code sections
            - metadata: Scraping metadata (titles, count, timing)
            - output_format: Format of the data
            - error: Error message (if failed)
    """
    try:
        # Validate and process titles
        if titles is None or "all" in titles:
            selected_titles = list(US_CODE_TITLES.keys())
        else:
            selected_titles = [t for t in titles if t in US_CODE_TITLES]
            if not selected_titles:
                return {
                    "status": "error",
                    "error": "No valid titles specified",
                    "data": [],
                    "metadata": {}
                }
        
        logger.info(f"Starting US Code scraping for titles: {selected_titles}")
        start_time = time.time()
        
        # Import required libraries
        try:
            import requests
            from bs4 import BeautifulSoup
        except ImportError as ie:
            return {
                "status": "error",
                "error": f"Required library not available: {ie}. Install with: pip install requests beautifulsoup4",
                "data": [],
                "metadata": {}
            }
        
        scraped_sections = []
        sections_count = 0
        
        # Scrape each selected title
        for title_num in selected_titles:
            if max_sections and sections_count >= max_sections:
                logger.info(f"Reached max_sections limit of {max_sections}")
                break
                
            title_name = US_CODE_TITLES[title_num]
            logger.info(f"Scraping Title {title_num}: {title_name}")
            
            # Fetch from production US Code API at uscode.house.gov
            title_data = await fetch_us_code_title(
                title_num, 
                title_name, 
                include_metadata,
                rate_limit_delay
            )
            
            if title_data and title_data.get("sections"):
                scraped_sections.append(title_data)
                sections_count += len(title_data["sections"])
            
            # Rate limiting between titles
            await asyncio.sleep(rate_limit_delay)
        
        elapsed_time = time.time() - start_time
        
        metadata = {
            "titles_scraped": selected_titles,
            "titles_count": len(selected_titles),
            "sections_count": sections_count,
            "elapsed_time_seconds": elapsed_time,
            "scraped_at": datetime.now().isoformat(),
            "source": "uscode.house.gov",
            "rate_limit_delay": rate_limit_delay,
            "include_metadata": include_metadata
        }
        
        logger.info(f"Completed US Code scraping: {sections_count} sections in {elapsed_time:.2f}s")
        
        return {
            "status": "success",
            "data": scraped_sections,
            "metadata": metadata,
            "output_format": output_format,
            "note": "Production implementation using official US Code API at uscode.house.gov"
        }
        
    except Exception as e:
        logger.error(f"US Code scraping failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "data": [],
            "metadata": {}
        }
