"""US Code scraper for building federal statutory law datasets.

This module downloads and parses title packages from GovInfo package endpoints,
producing section-level records suitable for full U.S. Code ingestion.
"""

import json
import logging
import re
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import anyio

try:
    import requests
    from bs4 import BeautifulSoup

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

logger = logging.getLogger(__name__)

DEFAULT_USCODE_CACHE_DIR = Path.home() / ".ipfs_datasets" / "us_code" / "cache"
DEFAULT_USCODE_INDEX_DIR = Path.home() / ".ipfs_datasets" / "us_code"
DEFAULT_USCODE_INDEX_PATH = DEFAULT_USCODE_INDEX_DIR / "uscode_index_latest.jsonl"
MIN_USCODE_YEAR = 1994
USER_AGENT = "ipfs-datasets-uscode-scraper/2.0"

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


def _title_sort_key(title: str) -> int:
    try:
        return int(str(title))
    except Exception:
        return 10**9


def _normalize_titles(titles: Optional[List[str]]) -> List[str]:
    if titles is None or "all" in [str(t).lower() for t in titles]:
        return sorted(list(US_CODE_TITLES.keys()), key=_title_sort_key)
    out: List[str] = []
    for value in titles:
        key = str(value).strip()
        if key in US_CODE_TITLES:
            out.append(key)
    return sorted(list(dict.fromkeys(out)), key=_title_sort_key)


def _make_session() -> "requests.Session":
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/zip, text/html, application/xhtml+xml;q=0.9, */*;q=0.8",
        }
    )
    return session


def _govinfo_zip_url(year: int, title_num: str) -> str:
    return (
        f"https://www.govinfo.gov/content/pkg/USCODE-{int(year)}-title{title_num}/"
        f"zip/USCODE-{int(year)}-title{title_num}.zip"
    )


def _govinfo_section_url(year: int, title_num: str, html_name: str) -> str:
    return (
        f"https://www.govinfo.gov/content/pkg/USCODE-{int(year)}-title{title_num}/"
        f"html/{html_name}"
    )


def _discover_latest_year(session: "requests.Session") -> Optional[int]:
    current_year = datetime.now().year
    for year in range(current_year, MIN_USCODE_YEAR - 1, -1):
        probe = _govinfo_zip_url(year, "1")
        try:
            response = session.get(probe, timeout=25, stream=True)
            if int(response.status_code) != 200:
                continue
            content_type = str(response.headers.get("content-type") or "").lower()
            if "zip" not in content_type:
                continue
            chunk = response.raw.read(4)
            if chunk == b"PK\x03\x04":
                return year
        except Exception:
            continue
    return None


def _download_title_zip(
    session: "requests.Session",
    *,
    year: int,
    title_num: str,
    cache_dir: Path,
    force_download: bool,
) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / f"USCODE-{int(year)}-title{title_num}.zip"
    if out_path.exists() and out_path.stat().st_size > 0 and not force_download:
        return out_path

    url = _govinfo_zip_url(year, title_num)
    response = session.get(url, timeout=60, stream=True)
    if int(response.status_code) != 200:
        raise RuntimeError(f"Failed to download title zip: HTTP {response.status_code} ({url})")

    with out_path.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if not chunk:
                continue
            handle.write(chunk)

    if out_path.stat().st_size <= 0:
        raise RuntimeError(f"Downloaded empty zip for title {title_num} year {year}")

    return out_path


def _extract_section_number_from_filename(file_name: str) -> str:
    match = re.search(r"-sec([^.]+)\.htm$", file_name, flags=re.IGNORECASE)
    if match:
        return str(match.group(1)).strip()
    return Path(file_name).stem


def _extract_sections_from_zip(
    zip_path: Path,
    *,
    year: int,
    title_num: str,
    title_name: str,
    include_metadata: bool,
) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    with zipfile.ZipFile(zip_path) as archive:
        names = sorted(archive.namelist())
        html_entries = [
            name
            for name in names
            if "/html/" in name and name.lower().endswith(".htm") and "-sec" in name.lower()
        ]

        for entry_name in html_entries:
            html_name = Path(entry_name).name
            raw = archive.read(entry_name)
            soup = BeautifulSoup(raw, "html.parser")

            heading_node = soup.find(["h1", "h2", "h3", "h4", "title"])
            heading = heading_node.get_text(" ", strip=True) if heading_node else html_name
            text = soup.get_text(" ", strip=True)
            section_number = _extract_section_number_from_filename(html_name)

            record: Dict[str, Any] = {
                "section_number": section_number,
                "heading": heading[:500],
                "text": text,
            }
            if include_metadata:
                record.update(
                    {
                        "title_number": title_num,
                        "title_name": title_name,
                        "year": int(year),
                        "package": f"USCODE-{int(year)}-title{title_num}",
                        "source_url": _govinfo_section_url(year, title_num, html_name),
                    }
                )
            sections.append(record)

    return sections


def _write_index_jsonl(sections: List[Dict[str, Any]], *, index_path: Path) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("w", encoding="utf-8") as handle:
        for item in sections:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def _load_index_jsonl(index_path: Path) -> List[Dict[str, Any]]:
    if not index_path.exists():
        return []
    out: List[Dict[str, Any]] = []
    with index_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


async def fetch_us_code_title(
    title_num: str,
    title_name: str,
    include_metadata: bool = True,
    rate_limit_delay: float = 1.0,
    year: Optional[int] = None,
    cache_dir: Optional[Path] = None,
    force_download: bool = False,
) -> Dict[str, Any]:
    """Fetch a US Code title from GovInfo package ZIP content.
    
    Args:
        title_num: Title number (e.g., "18")
        title_name: Title name (e.g., "Crimes and Criminal Procedure")
        include_metadata: Include metadata like effective dates
        rate_limit_delay: Delay between requests
        
    Returns:
        Dict with title data and sections
    """
    if not REQUESTS_AVAILABLE:
        return {
            "title_number": title_num,
            "title_name": title_name,
            "source": "US Code",
            "source_url": "https://www.govinfo.gov/",
            "scraped_at": datetime.now().isoformat(),
            "error": "Required libraries unavailable: install requests and beautifulsoup4",
            "sections": [],
        }

    cache_root = Path(cache_dir) if cache_dir is not None else DEFAULT_USCODE_CACHE_DIR
    try:
        session = _make_session()
        selected_year = int(year) if year is not None else _discover_latest_year(session)
        if selected_year is None:
            raise RuntimeError("Unable to discover an available USCODE package year")

        zip_path = _download_title_zip(
            session,
            year=selected_year,
            title_num=title_num,
            cache_dir=cache_root / str(selected_year),
            force_download=bool(force_download),
        )
        sections = _extract_sections_from_zip(
            zip_path,
            year=selected_year,
            title_num=title_num,
            title_name=title_name,
            include_metadata=include_metadata,
        )

        await anyio.sleep(max(0.0, float(rate_limit_delay)))
        return {
            "title_number": title_num,
            "title_name": title_name,
            "source": "US Code (GovInfo package ZIP)",
            "source_url": _govinfo_zip_url(selected_year, title_num),
            "scraped_at": datetime.now().isoformat(),
            "year": selected_year,
            "zip_path": str(zip_path),
            "sections": sections,
        }
    except Exception as e:
        logger.error("Failed to fetch title %s: %s", title_num, e)
        return {
            "title_number": title_num,
            "title_name": title_name,
            "source": "US Code",
            "source_url": "https://www.govinfo.gov/",
            "scraped_at": datetime.now().isoformat(),
            "error": str(e),
            "sections": [],
        }


async def search_us_code(
    query: str,
    titles: Optional[List[str]] = None,
    max_results: int = 100,
    limit: Optional[int] = None  # Alias for max_results
) -> Dict[str, Any]:
    """Search US Code for sections matching a query.
    
    Args:
        query: Search query string
        titles: Optional list of title numbers to search within
        max_results: Maximum number of results to return
        limit: Alias for max_results (for compatibility)
        
    Returns:
        Dict with search results
    """
    if limit is not None:
        max_results = limit

    try:
        query_text = str(query or "").strip().lower()
        if not query_text:
            return {
                "status": "error",
                "error": "Query must be non-empty",
                "results": [],
            }

        title_filter = set(_normalize_titles(titles)) if titles else None
        rows = _load_index_jsonl(DEFAULT_USCODE_INDEX_PATH)
        if not rows:
            return {
                "status": "error",
                "error": "No local US Code index found. Run scrape_us_code() first.",
                "results": [],
            }

        results: List[Dict[str, Any]] = []
        for row in rows:
            title_num = str(row.get("title_number") or "").strip()
            if title_filter and title_num not in title_filter:
                continue

            heading = str(row.get("heading") or "")
            text = str(row.get("text") or "")
            haystack = f"{heading}\n{text}".lower()
            if query_text not in haystack:
                continue

            idx = haystack.find(query_text)
            lo = max(0, idx - 200)
            hi = min(len(text), lo + 500)
            snippet = text[lo:hi].strip() if text else heading[:500]

            results.append(
                {
                    "title_number": title_num,
                    "title_name": row.get("title_name"),
                    "section_number": row.get("section_number"),
                    "title": f"Title {title_num} § {row.get('section_number')}",
                    "snippet": snippet,
                    "url": row.get("source_url", ""),
                    "year": row.get("year"),
                }
            )
            if len(results) >= int(max_results):
                break

        return {
            "status": "success",
            "query": query,
            "results": results,
            "count": len(results),
            "index_path": str(DEFAULT_USCODE_INDEX_PATH),
        }
    except Exception as e:
        logger.error("US Code search failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "results": [],
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
            "source": "US Code - GovInfo package titles"
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
    max_sections: Optional[int] = None,
    year: Optional[int] = None,
    cache_dir: Optional[str] = None,
    force_download: bool = False,
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
        selected_titles = _normalize_titles(titles)
        if not selected_titles:
            return {
                "status": "error",
                "error": "No valid titles specified",
                "data": [],
                "metadata": {},
            }

        logger.info("Starting US Code scraping for titles: %s", selected_titles)
        start_time = time.time()

        if not REQUESTS_AVAILABLE:
            return {
                "status": "error",
                "error": "Required libraries unavailable: install requests and beautifulsoup4",
                "data": [],
                "metadata": {},
            }

        cache_root = Path(cache_dir) if cache_dir else DEFAULT_USCODE_CACHE_DIR
        scraped_titles: List[Dict[str, Any]] = []
        sections_count = 0

        for title_num in selected_titles:
            if max_sections and sections_count >= max_sections:
                logger.info("Reached max_sections limit of %s", max_sections)
                break

            title_name = US_CODE_TITLES[title_num]
            logger.info("Scraping Title %s: %s", title_num, title_name)

            title_data = await fetch_us_code_title(
                title_num,
                title_name,
                include_metadata=include_metadata,
                rate_limit_delay=rate_limit_delay,
                year=year,
                cache_dir=cache_root,
                force_download=force_download,
            )

            sections = list(title_data.get("sections") or []) if isinstance(title_data, dict) else []
            if max_sections is not None and sections:
                remaining = int(max_sections) - int(sections_count)
                if remaining <= 0:
                    sections = []
                elif len(sections) > remaining:
                    sections = sections[:remaining]
                    title_data["sections"] = sections

            if sections:
                scraped_titles.append(title_data)
                sections_count += len(sections)

        elapsed_time = time.time() - start_time

        flat_sections: List[Dict[str, Any]] = []
        for title_blob in scraped_titles:
            title_num = str(title_blob.get("title_number") or "")
            title_name = str(title_blob.get("title_name") or US_CODE_TITLES.get(title_num, ""))
            year_value = title_blob.get("year")
            for section in title_blob.get("sections") or []:
                if not isinstance(section, dict):
                    continue
                row = dict(section)
                row.setdefault("title_number", title_num)
                row.setdefault("title_name", title_name)
                row.setdefault("year", year_value)
                flat_sections.append(row)

        _write_index_jsonl(flat_sections, index_path=DEFAULT_USCODE_INDEX_PATH)

        effective_year = None
        if scraped_titles:
            effective_year = scraped_titles[0].get("year")

        metadata = {
            "titles_scraped": selected_titles,
            "titles_count": len(scraped_titles),
            "sections_count": sections_count,
            "elapsed_time_seconds": elapsed_time,
            "scraped_at": datetime.now().isoformat(),
            "source": "GovInfo USCODE package ZIP",
            "rate_limit_delay": rate_limit_delay,
            "include_metadata": include_metadata,
            "year": effective_year,
            "cache_dir": str(cache_root),
            "index_path": str(DEFAULT_USCODE_INDEX_PATH),
            "force_download": bool(force_download),
        }

        logger.info("Completed US Code scraping: %s sections in %.2fs", sections_count, elapsed_time)

        return {
            "status": "success",
            "data": scraped_titles,
            "metadata": metadata,
            "output_format": output_format,
            "note": "Comprehensive title-package ingestion from GovInfo USCODE ZIP sources."
        }

    except Exception as e:
        logger.error("US Code scraping failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "data": [],
            "metadata": {},
        }


__all__ = [
    "get_us_code_titles",
    "scrape_us_code",
    "search_us_code",
    "fetch_us_code_title",
]
