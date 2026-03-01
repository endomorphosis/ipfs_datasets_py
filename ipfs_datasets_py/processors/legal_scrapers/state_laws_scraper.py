"""State laws scraper for building state statutory law datasets.

This tool scrapes state statutes and regulations from various state
legislative websites and legal databases.
"""
import logging
import time
from typing import Dict, List, Optional, Any
from datetime import datetime
import json
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_QUALITY_NAV_RE = re.compile(
    r"skip to|session:|all rights reserved|committee|legislature|bill status|meeting|calendar|login|contact",
    re.IGNORECASE,
)
_QUALITY_SECTION_FALLBACK_RE = re.compile(r"^Section-\d+$", re.IGNORECASE)
_QUALITY_SECTION_SIGNAL_RE = re.compile(r"\b\d{1,2}-\d{3,5}(?:\.\d+)?\b")

# US States and territories
US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia"
}


async def list_state_jurisdictions() -> Dict[str, Any]:
    """Get list of all US state jurisdictions.
    
    Returns:
        Dict containing:
            - status: "success" or "error"
            - states: Dictionary mapping state codes to names
            - count: Number of states/territories
            - error: Error message (if failed)
    """
    try:
        return {
            "status": "success",
            "states": US_STATES,
            "count": len(US_STATES),
            "note": "Includes all 50 US states and DC"
        }
    except Exception as e:
        logger.error(f"Failed to get state jurisdictions: {e}")
        return {
            "status": "error",
            "error": str(e),
            "states": {},
            "count": 0
        }


async def scrape_state_laws(
    states: Optional[List[str]] = None,
    legal_areas: Optional[List[str]] = None,
    output_format: str = "json",
    include_metadata: bool = True,
    rate_limit_delay: float = 2.0,
    max_statutes: Optional[int] = None,
    use_state_specific_scrapers: bool = True,
    output_dir: Optional[str] = None,
    write_jsonld: bool = True,
    strict_full_text: bool = False,
    min_full_text_chars: int = 300,
    hydrate_statute_text: bool = True,
) -> Dict[str, Any]:
    """Scrape state statutes and build a structured dataset.
    
    This function now uses state-specific scrapers that go directly to
    each state's official legislative website and normalize the data
    into a consistent schema.
    
    Args:
        states: List of state codes to scrape (e.g., ["CA", "NY", "TX"]).
                If None or ["all"], scrapes all states.
        legal_areas: Specific areas of law to focus on (e.g., ["criminal", "civil", "family"])
        output_format: Output format - "json" or "parquet"
        include_metadata: Include statute metadata (effective dates, amendments, etc.)
        rate_limit_delay: Delay between requests in seconds (default 2.0, higher for state sites)
        max_statutes: Maximum number of statutes to scrape
        use_state_specific_scrapers: Use state-specific scrapers (True) or fallback to Justia (False)
    
    Returns:
        Dict containing:
            - status: "success" or "error"
            - data: Scraped state statutes in normalized schema
            - metadata: Scraping metadata
            - output_format: Format of the data
            - error: Error message (if failed)
    """
    try:
        # Validate and process states
        if states is None or "all" in states:
            selected_states = list(US_STATES.keys())
        else:
            selected_states = [s.upper() for s in states if s.upper() in US_STATES]
            if not selected_states:
                return {
                    "status": "error",
                    "error": "No valid states specified",
                    "data": [],
                    "metadata": {}
                }
        
        logger.info(f"Starting state laws scraping for states: {selected_states}")
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
        
        scraped_statutes = []
        statutes_count = 0
        errors = []
        warnings = []
        zero_statute_states = []
        quality_by_state: Dict[str, Dict[str, Any]] = {}
        low_quality_states: List[str] = []
        
        # Try to use state-specific scrapers if enabled
        if use_state_specific_scrapers:
            try:
                from .state_scrapers import get_scraper_for_state, GenericStateScraper, StateScraperRegistry
                
                for state_code in selected_states:
                    if max_statutes and statutes_count >= max_statutes:
                        logger.info(f"Reached max_statutes limit of {max_statutes}")
                        break
                    
                    state_name = US_STATES[state_code]
                    logger.info(f"Scraping {state_code}: {state_name}")
                    
                    try:
                        # Get state-specific scraper or fallback to generic
                        scraper = get_scraper_for_state(state_code, state_name)
                        if not scraper:
                            logger.info(f"No specific scraper for {state_code}, using generic scraper")
                            scraper = GenericStateScraper(state_code, state_name)
                        
                        # Scrape using the state-specific scraper
                        remaining_statutes = max_statutes - statutes_count if max_statutes else None
                        normalized_statutes = await scraper.scrape_all(
                            legal_areas=legal_areas,
                            max_statutes=remaining_statutes,
                            rate_limit_delay=rate_limit_delay,
                            hydrate_statute_text=hydrate_statute_text,
                        )

                        strict_removed_count = 0
                        if strict_full_text:
                            normalized_statutes, strict_removed_count = _filter_strict_full_text_statutes(
                                normalized_statutes,
                                min_full_text_chars=min_full_text_chars,
                            )
                        
                        # Convert normalized statutes to output format
                        statute_data = {
                            "state_code": state_code,
                            "state_name": state_name,
                            "title": f"{state_name} Laws",
                            "source": "Official State Legislative Website",
                            "source_url": scraper.get_base_url(),
                            "official_url": scraper.get_base_url(),
                            "scraped_at": datetime.now().isoformat(),
                            "statutes": [statute.to_dict() for statute in normalized_statutes],
                            "schema_version": "1.0",
                            "normalized": True,
                            "strict_full_text": strict_full_text,
                            "strict_removed_count": strict_removed_count,
                        }

                        quality_metrics = _compute_state_quality_metrics(statute_data["statutes"])
                        statute_data["quality_metrics"] = quality_metrics
                        quality_by_state[state_code] = quality_metrics

                        # Gate states that are likely link/navigation contamination.
                        total_q = int(quality_metrics.get("total", 0) or 0)
                        nav_q = float(quality_metrics.get("nav_like_ratio", 0.0) or 0.0)
                        fallback_q = float(quality_metrics.get("fallback_section_ratio", 0.0) or 0.0)
                        numeric_q = float(quality_metrics.get("numeric_section_name_ratio", 0.0) or 0.0)

                        quality_flag = False
                        if total_q >= 10 and (nav_q >= 0.2 or fallback_q >= 0.7 or numeric_q <= 0.2):
                            quality_flag = True
                        elif 1 <= total_q < 10 and (nav_q >= 0.5 or fallback_q >= 0.8 or numeric_q == 0.0):
                            quality_flag = True

                        if quality_flag:
                            low_quality_states.append(state_code)
                            warnings.append(
                                f"{state_code} quality gate triggered "
                                f"(total={total_q}, nav={nav_q}, fallback={fallback_q}, numeric={numeric_q})"
                            )
                        
                        scraped_statutes.append(statute_data)
                        statutes_count += len(normalized_statutes)
                        if len(normalized_statutes) == 0:
                            warn_msg = f"{state_code} returned zero statutes"
                            warnings.append(warn_msg)
                            zero_statute_states.append(state_code)
                        logger.info(f"Successfully scraped {len(normalized_statutes)} statutes for {state_name}")
                        
                    except Exception as e:
                        error_msg = f"Failed to scrape {state_name} using state-specific scraper: {str(e)}"
                        logger.error(error_msg)
                        errors.append(error_msg)
                        
                        # Add minimal data even on error
                        statute_data = {
                            "state_code": state_code,
                            "state_name": state_name,
                            "title": f"{state_name} Laws",
                            "source": "Official State Legislative Website",
                            "error": str(e),
                            "scraped_at": datetime.now().isoformat(),
                            "statutes": []
                        }
                        scraped_statutes.append(statute_data)
                    
                    # Rate limiting
                    time.sleep(rate_limit_delay)
                
            except ImportError as e:
                logger.warning(f"State-specific scrapers not available: {e}, falling back to Justia")
                use_state_specific_scrapers = False
        
        # Fallback to Justia-based scraping if state-specific scrapers are disabled or failed
        if not use_state_specific_scrapers or not scraped_statutes:
            logger.info("Using Justia fallback scraper")
            
            # State code sources mapping - using Justia as a reliable aggregator
            state_sources = {
                state_code: {
                    "name": US_STATES[state_code],
                    "justia_url": f"https://law.justia.com/codes/{state_code.lower()}/",
                    "official_url": _get_official_state_url(state_code)
                }
                for state_code in US_STATES.keys()
            }
            
            # Scrape each selected state
            for state_code in selected_states:
                if max_statutes and statutes_count >= max_statutes:
                    logger.info(f"Reached max_statutes limit of {max_statutes}")
                    break
                
                state_name = US_STATES[state_code]
                logger.info(f"Scraping {state_code}: {state_name}")
                
                try:
                    # Fetch state code overview from Justia
                    state_info = state_sources[state_code]
                    justia_url = state_info["justia_url"]
                    
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                    }
                    
                    response = requests.get(justia_url, headers=headers, timeout=30)
                    response.raise_for_status()
                    
                    soup = BeautifulSoup(response.content, 'html.parser')
                    
                    # Extract code titles/sections
                    statutes = []
                    code_links = soup.find_all('a', href=True)
                    
                    for link in code_links:
                        href = link.get('href', '')
                        text = link.get_text(strip=True)
                        
                        # Look for statute/code links
                        if text and len(text) > 10 and (
                            '/codes/' in href or 
                            'title' in text.lower() or 
                            'chapter' in text.lower() or
                            'article' in text.lower()
                        ):
                            # Filter by legal area if specified
                            if legal_areas:
                                area_match = any(area.lower() in text.lower() for area in legal_areas)
                                if not area_match:
                                    continue
                            
                            statute = {
                                "statute_number": text[:100],
                                "title": text[:200],
                                "url": href if href.startswith('http') else f"https://law.justia.com{href}",
                                "legal_area": _identify_legal_area(text, legal_areas),
                            }
                            
                            if include_metadata:
                                statute["scraped_at"] = datetime.now().isoformat()
                                statute["source"] = "Justia"
                            
                            statutes.append(statute)
                            statutes_count += 1
                            
                            if max_statutes and statutes_count >= max_statutes:
                                break
                    
                    statute_data = {
                        "state_code": state_code,
                        "state_name": state_name,
                        "title": f"{state_name} Code",
                        "source": "Justia Legal Database (Fallback)",
                        "source_url": justia_url,
                        "official_url": state_info["official_url"],
                        "scraped_at": datetime.now().isoformat(),
                        "statutes": statutes[:max_statutes] if max_statutes else statutes,
                        "normalized": False
                    }
                    
                    scraped_statutes.append(statute_data)
                    logger.info(f"Successfully scraped {len(statutes)} statutes for {state_name}")
                    
                except Exception as e:
                    error_msg = f"Failed to scrape {state_name}: {str(e)}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    
                    # Add minimal data even on error
                    state_info = state_sources.get(state_code, {})
                    statute_data = {
                        "state_code": state_code,
                        "state_name": state_name,
                        "title": f"{state_name} Code",
                        "source": "Justia Legal Database (Fallback)",
                        "source_url": state_info.get("justia_url", ""),
                        "official_url": state_info.get("official_url", ""),
                        "error": str(e),
                        "scraped_at": datetime.now().isoformat(),
                        "statutes": []
                    }
                    scraped_statutes.append(statute_data)
                
                # Rate limiting to be respectful to servers
                time.sleep(rate_limit_delay)
        
        elapsed_time = time.time() - start_time
        
        scraper_info = "State-specific scrapers" if use_state_specific_scrapers else "Justia fallback scraper"
        
        jsonld_paths: List[str] = []
        if use_state_specific_scrapers and write_jsonld:
            output_root = _resolve_state_output_dir(output_dir)
            jsonld_dir = output_root / "state_laws_jsonld"
            jsonld_dir.mkdir(parents=True, exist_ok=True)
            jsonld_paths = _write_state_jsonld_files(scraped_statutes, jsonld_dir)

        strict_removed_total = 0
        for block in scraped_statutes:
            if isinstance(block, dict):
                strict_removed_total += int(block.get("strict_removed_count") or 0)

        metadata = {
            "states_scraped": selected_states,
            "states_count": len(selected_states),
            "statutes_count": statutes_count,
            "legal_areas": legal_areas or ["all"],
            "elapsed_time_seconds": elapsed_time,
            "scraped_at": datetime.now().isoformat(),
            "scraper_type": scraper_info,
            "sources": "Official State Legislative Websites" if use_state_specific_scrapers else "Justia Legal Database (https://law.justia.com)",
            "rate_limit_delay": rate_limit_delay,
            "include_metadata": include_metadata,
            "errors": errors if errors else None,
            "warnings": warnings if warnings else None,
            "zero_statute_states": zero_statute_states if zero_statute_states else None,
            "low_quality_states": low_quality_states if low_quality_states else None,
            "quality_by_state": quality_by_state if quality_by_state else None,
            "schema_normalized": use_state_specific_scrapers,
            "jsonld_dir": str((_resolve_state_output_dir(output_dir) / "state_laws_jsonld")) if (use_state_specific_scrapers and write_jsonld) else None,
            "jsonld_files": jsonld_paths if jsonld_paths else None,
            "strict_full_text": strict_full_text,
            "min_full_text_chars": int(min_full_text_chars),
            "strict_removed_total": strict_removed_total,
            "hydrate_statute_text": hydrate_statute_text,
        }
        
        logger.info(f"Completed state laws scraping: {statutes_count} statutes in {elapsed_time:.2f}s using {scraper_info}")
        
        return {
            "status": "success" if (not errors and not warnings) else "partial_success",
            "data": scraped_statutes,
            "metadata": metadata,
            "output_format": output_format,
        }
        
    except Exception as e:
        logger.error(f"State laws scraping failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "data": [],
            "metadata": {}
        }


def _get_official_state_url(state_code: str) -> str:
    """Get official state legislature URL for a given state code."""
    # Mapping of state codes to their official legislative websites
    official_urls = {
        "CA": "https://leginfo.legislature.ca.gov/",
        "NY": "https://www.nysenate.gov/",
        "TX": "https://capitol.texas.gov/",
        "FL": "http://www.leg.state.fl.us/",
        "IL": "https://www.ilga.gov/",
        "PA": "https://www.legis.state.pa.us/",
        "OH": "https://www.legislature.ohio.gov/",
        "GA": "http://www.legis.ga.gov/",
        "NC": "https://www.ncleg.gov/",
        "MI": "https://www.legislature.mi.gov/",
    }
    
    return official_urls.get(state_code, f"https://legislature.{state_code.lower()}.gov/")


def _resolve_state_output_dir(output_dir: Optional[str] = None) -> Path:
    if output_dir:
        return Path(output_dir).expanduser().resolve()
    return (Path.home() / ".ipfs_datasets" / "state_laws").resolve()


def _compute_state_quality_metrics(statutes: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(statutes)
    if total <= 0:
        return {
            "total": 0,
            "nav_like_ratio": 0.0,
            "fallback_section_ratio": 0.0,
            "numeric_section_name_ratio": 0.0,
        }

    nav_like = 0
    fallback_section = 0
    numeric_section_name = 0

    for statute in statutes:
        if not isinstance(statute, dict):
            continue

        text = str(statute.get("full_text") or statute.get("text") or "")
        section_number = str(statute.get("section_number") or statute.get("sectionNumber") or "")
        section_name = str(statute.get("section_name") or statute.get("sectionName") or "")

        if _QUALITY_NAV_RE.search(text):
            nav_like += 1
        if _QUALITY_SECTION_FALLBACK_RE.match(section_number):
            fallback_section += 1
        if _QUALITY_SECTION_SIGNAL_RE.search(section_name):
            numeric_section_name += 1

    return {
        "total": total,
        "nav_like_ratio": round(nav_like / total, 3),
        "fallback_section_ratio": round(fallback_section / total, 3),
        "numeric_section_name_ratio": round(numeric_section_name / total, 3),
    }


def _write_state_jsonld_files(scraped_statutes: List[Dict[str, Any]], jsonld_dir: Path) -> List[str]:
    written: List[str] = []
    for state_block in scraped_statutes:
        state_code = str(state_block.get("state_code") or "").strip().upper()
        statutes = state_block.get("statutes") or []
        if not state_code or not isinstance(statutes, list):
            continue

        out_path = jsonld_dir / f"STATE-{state_code}.jsonld"
        lines_written = 0
        with out_path.open("w", encoding="utf-8") as handle:
            for statute in statutes:
                if not isinstance(statute, dict):
                    continue
                structured_data = statute.get("structured_data") or {}
                if not isinstance(structured_data, dict):
                    continue
                payload = structured_data.get("jsonld")
                if not isinstance(payload, dict):
                    continue
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
                lines_written += 1

        if lines_written > 0:
            written.append(str(out_path))
        else:
            out_path.unlink(missing_ok=True)

    return written


def _has_sufficient_full_text(statute: Any, *, min_full_text_chars: int) -> bool:
    if hasattr(statute, "full_text"):
        full_text = str(getattr(statute, "full_text", "") or "")
    elif isinstance(statute, dict):
        full_text = str(statute.get("full_text") or "")
    else:
        full_text = ""

    if len(full_text.strip()) < int(min_full_text_chars):
        return False

    structured_data = getattr(statute, "structured_data", None)
    if structured_data is None and isinstance(statute, dict):
        structured_data = statute.get("structured_data") or {}

    if isinstance(structured_data, dict):
        subsections = structured_data.get("subsections") or []
        citations = structured_data.get("citations") or {}
        if isinstance(subsections, list) and len(subsections) > 0:
            return True
        if isinstance(citations, dict):
            total_cites = sum(
                len(v) for v in citations.values() if isinstance(v, list)
            )
            if total_cites > 0:
                return True

    # If text length threshold passes, allow even without parsed structure.
    return True


def _filter_strict_full_text_statutes(statutes: List[Any], *, min_full_text_chars: int) -> tuple[List[Any], int]:
    kept: List[Any] = []
    removed = 0
    for statute in statutes:
        if _has_sufficient_full_text(statute, min_full_text_chars=min_full_text_chars):
            kept.append(statute)
        else:
            removed += 1
    return kept, removed


def _identify_legal_area(text: str, legal_areas: Optional[List[str]] = None) -> str:
    """Identify the legal area from statute title text."""
    text_lower = text.lower()
    
    # Common legal area keywords
    area_keywords = {
        "criminal": ["criminal", "penal", "crime", "felony", "misdemeanor"],
        "civil": ["civil", "tort", "liability", "damages"],
        "family": ["family", "marriage", "divorce", "custody", "child support"],
        "employment": ["employment", "labor", "worker", "wage", "unemployment"],
        "environmental": ["environmental", "pollution", "conservation", "wildlife"],
        "business": ["business", "corporation", "commercial", "contract", "sales"],
        "property": ["property", "real estate", "land", "conveyance"],
        "tax": ["tax", "taxation", "revenue", "assessment"],
        "health": ["health", "medical", "healthcare", "insurance"],
        "education": ["education", "school", "university", "student"],
    }
    
    # Check if user specified legal areas
    if legal_areas:
        for area in legal_areas:
            if area.lower() in text_lower:
                return area
    
    # Auto-detect legal area
    for area, keywords in area_keywords.items():
        for keyword in keywords:
            if keyword in text_lower:
                return area
    
    return "general"


__all__ = [
    "list_state_jurisdictions",
    "scrape_state_laws",
]
