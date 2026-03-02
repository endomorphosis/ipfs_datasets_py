"""State laws scraper for building state statutory law datasets.

This tool scrapes state statutes and regulations from various state
legislative websites and legal databases.
"""
import logging
import asyncio
import time
from typing import Dict, List, Optional, Any
from datetime import datetime
import json
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_QUALITY_NAV_RE = re.compile(
    r"skip navigation|skip to content|all rights reserved|bill status|meeting schedule|calendar|login|contact us|docs options help|home documents",
    re.IGNORECASE,
)
_QUALITY_SECTION_FALLBACK_RE = re.compile(r"^Section-\d+$", re.IGNORECASE)
_QUALITY_SECTION_SIGNAL_RE = re.compile(
    r"(?:\b\d{1,4}[A-Za-z]?(?:[.\-]\d+[A-Za-z]*)+\b|§\s*\d+[A-Za-z]?(?:[.\-]\d+[A-Za-z]*)+|\b(?:section|sec\.?|s\.)\s*\d+[A-Za-z]?(?:[.\-]\d+[A-Za-z]*)*\b)",
    re.IGNORECASE,
)
_QUALITY_SECTION_NUMBER_RE = re.compile(
    r"^\d+[A-Za-z]?(?:[.\-]\d+[A-Za-z]*)*$",
    re.IGNORECASE,
)
_QUALITY_SCAFFOLD_TEXT_RE = re.compile(r"^\s*Section\s+Section-\d+\s*:", re.IGNORECASE)
_QUALITY_NAV_URL_RE = re.compile(
    r"/(?:calendar|meeting|roster|blog|news|jobs|photo|links?|home|bulletin|live|staff|contact|interim|committee|reports?|member|media)\b",
    re.IGNORECASE,
)


def _extract_statute_quality_fields(statute: Any) -> Dict[str, str]:
    if isinstance(statute, dict):
        return {
            "full_text": str(statute.get("full_text") or statute.get("text") or ""),
            "section_number": str(statute.get("section_number") or statute.get("sectionNumber") or ""),
            "section_name": str(statute.get("section_name") or statute.get("sectionName") or ""),
            "source_url": str(statute.get("source_url") or statute.get("sourceUrl") or ""),
        }

    return {
        "full_text": str(getattr(statute, "full_text", "") or ""),
        "section_number": str(getattr(statute, "section_number", "") or ""),
        "section_name": str(getattr(statute, "section_name", "") or ""),
        "source_url": str(getattr(statute, "source_url", "") or ""),
    }


def _is_scaffold_or_navigation_record(statute: Any) -> bool:
    fields = _extract_statute_quality_fields(statute)
    text = fields["full_text"].strip()
    section_number = fields["section_number"].strip()
    section_name = fields["section_name"].strip()
    source_url = fields["source_url"].strip().lower()

    fallback_section = bool(_QUALITY_SECTION_FALLBACK_RE.match(section_number))
    has_statute_signal = bool(
        _QUALITY_SECTION_SIGNAL_RE.search(text)
        or _QUALITY_SECTION_SIGNAL_RE.search(section_name)
        or _QUALITY_SECTION_NUMBER_RE.match(section_number)
    )
    nav_like_text = bool(_QUALITY_NAV_RE.search(text) or _QUALITY_NAV_RE.search(section_name))
    nav_like_url = bool(_QUALITY_NAV_URL_RE.search(source_url))

    if _QUALITY_SCAFFOLD_TEXT_RE.match(text):
        return True

    if fallback_section and nav_like_text and not has_statute_signal:
        return True

    if nav_like_url and not has_statute_signal:
        return True

    if nav_like_text and not has_statute_signal and len(text) < 1200:
        return True

    return False

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
    parallel_workers: int = 6,
    per_state_retry_attempts: int = 1,
    retry_zero_statute_states: bool = True,
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
        fetch_analytics_by_state: Dict[str, Dict[str, Any]] = {}

        parallel_workers = max(1, int(parallel_workers or 1))
        per_state_retry_attempts = max(0, int(per_state_retry_attempts or 0))
        
        # Try to use state-specific scrapers if enabled
        if use_state_specific_scrapers:
            try:
                async def _run_state(state_code: str) -> Dict[str, Any]:
                    return await _scrape_state_with_retries(
                        state_code=state_code,
                        legal_areas=legal_areas,
                        rate_limit_delay=rate_limit_delay,
                        max_statutes=max_statutes,
                        strict_full_text=strict_full_text,
                        min_full_text_chars=min_full_text_chars,
                        hydrate_statute_text=hydrate_statute_text,
                        retry_attempts=per_state_retry_attempts,
                        retry_zero_statute_states=retry_zero_statute_states,
                    )

                if parallel_workers <= 1:
                    state_results = []
                    for state_code in selected_states:
                        state_results.append(await _run_state(state_code))
                        if rate_limit_delay > 0:
                            await asyncio.sleep(rate_limit_delay)
                else:
                    semaphore = asyncio.Semaphore(parallel_workers)

                    async def _guarded_run(state_code: str) -> Dict[str, Any]:
                        async with semaphore:
                            return await _run_state(state_code)

                    state_results = await asyncio.gather(*[_guarded_run(code) for code in selected_states])

                result_by_state = {str(item.get("state_code") or ""): item for item in state_results}
                for state_code in selected_states:
                    item = result_by_state.get(state_code) or {
                        "state_code": state_code,
                        "state_name": US_STATES[state_code],
                        "error": "missing-state-result",
                        "statute_data": {
                            "state_code": state_code,
                            "state_name": US_STATES[state_code],
                            "title": f"{US_STATES[state_code]} Laws",
                            "source": "Official State Legislative Website",
                            "error": "missing-state-result",
                            "scraped_at": datetime.now().isoformat(),
                            "statutes": [],
                        },
                    }

                    statute_data = item.get("statute_data") or {}
                    scraped_statutes.append(statute_data)
                    statutes_count += int(item.get("statutes_count") or 0)

                    state_error = item.get("error")
                    if state_error:
                        errors.append(str(state_error))

                    quality = item.get("quality_metrics") or {}
                    if quality:
                        quality_by_state[state_code] = quality

                    fetch_analytics = item.get("fetch_analytics") or {}
                    if fetch_analytics:
                        fetch_analytics_by_state[state_code] = fetch_analytics

                    for warning in item.get("warnings") or []:
                        warnings.append(str(warning))

                    if bool(item.get("zero_statute")):
                        zero_statute_states.append(state_code)
                    if bool(item.get("low_quality")):
                        low_quality_states.append(state_code)

                if max_statutes and max_statutes > 0:
                    scraped_statutes, statutes_count = _trim_scraped_statutes_to_max(
                        scraped_statutes,
                        int(max_statutes),
                    )
                    quality_by_state = {
                        str(block.get("state_code") or ""): block.get("quality_metrics") or {}
                        for block in scraped_statutes
                        if isinstance(block, dict)
                    }
                    zero_statute_states = [
                        str(block.get("state_code") or "")
                        for block in scraped_statutes
                        if isinstance(block, dict) and len(block.get("statutes") or []) == 0
                    ]
                    low_quality_states = [
                        str(block.get("state_code") or "")
                        for block in scraped_statutes
                        if isinstance(block, dict) and bool(block.get("quality_flag"))
                    ]
                
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
            "parallel_workers": parallel_workers,
            "per_state_retry_attempts": per_state_retry_attempts,
            "retry_zero_statute_states": retry_zero_statute_states,
            "include_metadata": include_metadata,
            "errors": errors if errors else None,
            "warnings": warnings if warnings else None,
            "zero_statute_states": zero_statute_states if zero_statute_states else None,
            "low_quality_states": low_quality_states if low_quality_states else None,
            "quality_by_state": quality_by_state if quality_by_state else None,
            "coverage_summary": _compute_coverage_summary(
                selected_states=selected_states,
                scraped_statutes=scraped_statutes,
                errors=errors,
            ),
            "fetch_analytics": _aggregate_fetch_analytics(fetch_analytics_by_state),
            "fetch_analytics_by_state": fetch_analytics_by_state if fetch_analytics_by_state else None,
            "etl_readiness": _compute_etl_readiness_summary(scraped_statutes),
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
            "scaffold_ratio": 0.0,
        }

    nav_like = 0
    fallback_section = 0
    numeric_section_name = 0
    scaffold = 0

    for statute in statutes:
        if not isinstance(statute, dict):
            continue

        text = str(statute.get("full_text") or statute.get("text") or "")
        section_number = str(statute.get("section_number") or statute.get("sectionNumber") or "")
        section_name = str(statute.get("section_name") or statute.get("sectionName") or "")

        # Treat nav markers as quality failures only when the text is mostly chrome/boilerplate.
        if _QUALITY_NAV_RE.search(text) and len(text) < 2000:
            nav_like += 1
        if _QUALITY_SECTION_FALLBACK_RE.match(section_number):
            fallback_section += 1
        if _QUALITY_SECTION_SIGNAL_RE.search(section_name) or _QUALITY_SECTION_NUMBER_RE.match(section_number):
            numeric_section_name += 1
        if _is_scaffold_or_navigation_record(statute):
            scaffold += 1

    return {
        "total": total,
        "nav_like_ratio": round(nav_like / total, 3),
        "fallback_section_ratio": round(fallback_section / total, 3),
        "numeric_section_name_ratio": round(numeric_section_name / total, 3),
        "scaffold_ratio": round(scaffold / total, 3),
    }


def _should_flag_quality(quality_metrics: Dict[str, Any]) -> bool:
    total_q = int(quality_metrics.get("total", 0) or 0)
    nav_q = float(quality_metrics.get("nav_like_ratio", 0.0) or 0.0)
    fallback_q = float(quality_metrics.get("fallback_section_ratio", 0.0) or 0.0)
    numeric_q = float(quality_metrics.get("numeric_section_name_ratio", 0.0) or 0.0)
    scaffold_q = float(quality_metrics.get("scaffold_ratio", 0.0) or 0.0)

    fallback_problem = (total_q >= 10 and fallback_q >= 0.7 and numeric_q <= 0.2)
    if total_q >= 10 and (nav_q >= 0.2 or fallback_problem or numeric_q <= 0.2 or scaffold_q >= 0.2):
        return True
    if 1 <= total_q < 10 and nav_q >= 0.5:
        return True
    return False


def _format_quality_warning(state_code: str, quality_metrics: Dict[str, Any]) -> str:
    total_q = int(quality_metrics.get("total", 0) or 0)
    nav_q = float(quality_metrics.get("nav_like_ratio", 0.0) or 0.0)
    fallback_q = float(quality_metrics.get("fallback_section_ratio", 0.0) or 0.0)
    numeric_q = float(quality_metrics.get("numeric_section_name_ratio", 0.0) or 0.0)
    scaffold_q = float(quality_metrics.get("scaffold_ratio", 0.0) or 0.0)
    return (
        f"{state_code} quality gate triggered "
        f"(total={total_q}, nav={nav_q}, fallback={fallback_q}, numeric={numeric_q}, scaffold={scaffold_q})"
    )


def _scrape_state_once_sync(
    *,
    state_code: str,
    legal_areas: Optional[List[str]],
    rate_limit_delay: float,
    max_statutes: Optional[int],
    strict_full_text: bool,
    min_full_text_chars: int,
    hydrate_statute_text: bool,
) -> Dict[str, Any]:
    from .state_scrapers import get_scraper_for_state, GenericStateScraper

    state_name = US_STATES[state_code]
    scraper = get_scraper_for_state(state_code, state_name)
    if not scraper:
        logger.info(f"No specific scraper for {state_code}, using generic scraper")
        scraper = GenericStateScraper(state_code, state_name)

    normalized_statutes = asyncio.run(
        scraper.scrape_all(
            legal_areas=legal_areas,
            max_statutes=max_statutes,
            rate_limit_delay=rate_limit_delay,
            hydrate_statute_text=hydrate_statute_text,
        )
    )

    strict_removed_count = 0
    if strict_full_text:
        normalized_statutes, strict_removed_count = _filter_strict_full_text_statutes(
            normalized_statutes,
            min_full_text_chars=min_full_text_chars,
        )

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
    quality_flag = _should_flag_quality(quality_metrics)
    fetch_analytics = {}
    if hasattr(scraper, "get_fetch_analytics_snapshot"):
        try:
            fetch_analytics = scraper.get_fetch_analytics_snapshot()
        except Exception:
            fetch_analytics = {}
    statute_data["quality_metrics"] = quality_metrics
    statute_data["quality_flag"] = quality_flag
    if fetch_analytics:
        statute_data["fetch_analytics"] = fetch_analytics

    warnings: List[str] = []
    if quality_flag:
        warnings.append(_format_quality_warning(state_code, quality_metrics))
    if len(normalized_statutes) == 0:
        warnings.append(f"{state_code} returned zero statutes")

    return {
        "state_code": state_code,
        "state_name": state_name,
        "error": None,
        "statutes_count": len(normalized_statutes),
        "zero_statute": len(normalized_statutes) == 0,
        "low_quality": quality_flag,
        "quality_metrics": quality_metrics,
        "fetch_analytics": fetch_analytics,
        "warnings": warnings,
        "statute_data": statute_data,
    }


async def _scrape_state_with_retries(
    *,
    state_code: str,
    legal_areas: Optional[List[str]],
    rate_limit_delay: float,
    max_statutes: Optional[int],
    strict_full_text: bool,
    min_full_text_chars: int,
    hydrate_statute_text: bool,
    retry_attempts: int,
    retry_zero_statute_states: bool,
) -> Dict[str, Any]:
    attempts = 1 + max(0, int(retry_attempts or 0))
    best: Optional[Dict[str, Any]] = None

    for attempt_idx in range(attempts):
        try:
            result = await asyncio.to_thread(
                _scrape_state_once_sync,
                state_code=state_code,
                legal_areas=legal_areas,
                rate_limit_delay=rate_limit_delay,
                max_statutes=max_statutes,
                strict_full_text=strict_full_text,
                min_full_text_chars=min_full_text_chars,
                hydrate_statute_text=hydrate_statute_text,
            )
        except Exception as e:
            state_name = US_STATES[state_code]
            error_msg = f"Failed to scrape {state_name} using state-specific scraper: {str(e)}"
            logger.error(error_msg)
            result = {
                "state_code": state_code,
                "state_name": state_name,
                "error": error_msg,
                "statutes_count": 0,
                "zero_statute": True,
                "low_quality": False,
                "quality_metrics": {"total": 0, "nav_like_ratio": 0.0, "fallback_section_ratio": 0.0, "numeric_section_name_ratio": 0.0, "scaffold_ratio": 0.0},
                "warnings": [f"{state_code} returned zero statutes"],
                "statute_data": {
                    "state_code": state_code,
                    "state_name": state_name,
                    "title": f"{state_name} Laws",
                    "source": "Official State Legislative Website",
                    "error": str(e),
                    "scraped_at": datetime.now().isoformat(),
                    "statutes": [],
                },
            }

        if best is None:
            best = result
        else:
            prior_count = int(best.get("statutes_count") or 0)
            current_count = int(result.get("statutes_count") or 0)
            if current_count > prior_count:
                best = result
            elif current_count == prior_count and best.get("error") and not result.get("error"):
                best = result

        if attempt_idx >= attempts - 1:
            break

        should_retry = bool(result.get("error"))
        if retry_zero_statute_states and int(result.get("statutes_count") or 0) == 0:
            should_retry = True
        if not should_retry:
            break

        await asyncio.sleep(max(0.0, rate_limit_delay) + (attempt_idx + 1) * 0.5)

    return best or {
        "state_code": state_code,
        "state_name": US_STATES[state_code],
        "error": "missing-state-result",
        "statutes_count": 0,
        "zero_statute": True,
        "low_quality": False,
        "quality_metrics": {"total": 0, "nav_like_ratio": 0.0, "fallback_section_ratio": 0.0, "numeric_section_name_ratio": 0.0, "scaffold_ratio": 0.0},
        "warnings": [f"{state_code} returned zero statutes"],
        "statute_data": {
            "state_code": state_code,
            "state_name": US_STATES[state_code],
            "title": f"{US_STATES[state_code]} Laws",
            "source": "Official State Legislative Website",
            "error": "missing-state-result",
            "scraped_at": datetime.now().isoformat(),
            "statutes": [],
        },
    }


def _trim_scraped_statutes_to_max(
    scraped_statutes: List[Dict[str, Any]],
    max_statutes: int,
) -> tuple[List[Dict[str, Any]], int]:
    if max_statutes <= 0:
        return scraped_statutes, sum(len((block or {}).get("statutes") or []) for block in scraped_statutes)

    trimmed: List[Dict[str, Any]] = []
    remaining = max_statutes
    for block in scraped_statutes:
        if remaining <= 0:
            break
        if not isinstance(block, dict):
            continue

        statutes = list(block.get("statutes") or [])
        kept = statutes[:remaining]
        remaining -= len(kept)

        out_block = dict(block)
        out_block["statutes"] = kept
        out_block["quality_metrics"] = _compute_state_quality_metrics(kept)
        out_block["quality_flag"] = _should_flag_quality(out_block["quality_metrics"])
        trimmed.append(out_block)

    total = sum(len((block or {}).get("statutes") or []) for block in trimmed)
    return trimmed, total


def _compute_coverage_summary(
    *,
    selected_states: List[str],
    scraped_statutes: List[Dict[str, Any]],
    errors: List[str],
) -> Dict[str, Any]:
    states_targeted = len(selected_states)
    present_states = set()
    zero_states: List[str] = []
    error_states: List[str] = []

    for block in scraped_statutes:
        if not isinstance(block, dict):
            continue
        state_code = str(block.get("state_code") or "").upper()
        if not state_code:
            continue
        present_states.add(state_code)
        statutes = block.get("statutes") or []
        if len(statutes) == 0:
            zero_states.append(state_code)
        if block.get("error"):
            error_states.append(state_code)

    missing_states = [code for code in selected_states if code not in present_states]
    coverage_gap_states = sorted(set(zero_states + error_states + missing_states))

    return {
        "states_targeted": states_targeted,
        "states_returned": len(present_states),
        "states_with_nonzero_statutes": max(0, len(present_states) - len(set(zero_states))),
        "zero_statute_states": sorted(set(zero_states)),
        "error_states": sorted(set(error_states)),
        "missing_states": missing_states,
        "coverage_gap_states": coverage_gap_states,
        "full_coverage": len(coverage_gap_states) == 0 and not errors,
    }


def _aggregate_fetch_analytics(fetch_analytics_by_state: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    if not fetch_analytics_by_state:
        return {
            "states_with_fetch_analytics": 0,
            "attempted": 0,
            "success": 0,
            "success_ratio": 0.0,
            "fallback_count": 0,
            "providers": {},
        }

    attempted = 0
    success = 0
    fallback_count = 0
    providers: Dict[str, int] = {}

    for state_metrics in fetch_analytics_by_state.values():
        if not isinstance(state_metrics, dict):
            continue
        attempted += int(state_metrics.get("attempted", 0) or 0)
        success += int(state_metrics.get("success", 0) or 0)
        fallback_count += int(state_metrics.get("fallback_count", 0) or 0)

        provider_counts = state_metrics.get("providers") or {}
        if isinstance(provider_counts, dict):
            for provider, count in provider_counts.items():
                providers[str(provider)] = int(providers.get(str(provider), 0) or 0) + int(count or 0)

    return {
        "states_with_fetch_analytics": len(fetch_analytics_by_state),
        "attempted": attempted,
        "success": success,
        "success_ratio": round((success / attempted), 3) if attempted > 0 else 0.0,
        "fallback_count": fallback_count,
        "providers": providers,
    }


def _compute_etl_readiness_summary(scraped_statutes: List[Dict[str, Any]]) -> Dict[str, Any]:
    state_count = 0
    total_statutes = 0
    statutes_with_text = 0
    statutes_with_jsonld = 0
    statutes_with_citations = 0
    states_with_zero = 0
    states_with_jsonld = 0

    for state_block in scraped_statutes:
        if not isinstance(state_block, dict):
            continue
        state_count += 1
        statutes = state_block.get("statutes") or []
        if not statutes:
            states_with_zero += 1

        state_jsonld_hits = 0
        for statute in statutes:
            if not isinstance(statute, dict):
                continue
            total_statutes += 1

            full_text = str(statute.get("full_text") or statute.get("text") or "").strip()
            if len(full_text) >= 120:
                statutes_with_text += 1

            structured_data = statute.get("structured_data") or {}
            if isinstance(structured_data, dict):
                jsonld = structured_data.get("jsonld")
                if isinstance(jsonld, dict):
                    statutes_with_jsonld += 1
                    state_jsonld_hits += 1

                citations = structured_data.get("citations") or {}
                if isinstance(citations, dict):
                    citation_items = 0
                    for value in citations.values():
                        if isinstance(value, list):
                            citation_items += len(value)
                    if citation_items > 0:
                        statutes_with_citations += 1

        if state_jsonld_hits > 0:
            states_with_jsonld += 1

    full_text_ratio = round((statutes_with_text / total_statutes), 3) if total_statutes > 0 else 0.0
    jsonld_ratio = round((statutes_with_jsonld / total_statutes), 3) if total_statutes > 0 else 0.0
    citation_ratio = round((statutes_with_citations / total_statutes), 3) if total_statutes > 0 else 0.0

    return {
        "states_processed": state_count,
        "states_with_zero_statutes": states_with_zero,
        "states_with_jsonld": states_with_jsonld,
        "total_statutes": total_statutes,
        "full_text_ratio": full_text_ratio,
        "jsonld_ratio": jsonld_ratio,
        "citation_ratio": citation_ratio,
        "ready_for_kg_etl": bool(
            total_statutes > 0
            and full_text_ratio >= 0.85
            and jsonld_ratio >= 0.75
        ),
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
    if _is_scaffold_or_navigation_record(statute):
        return False

    fields = _extract_statute_quality_fields(statute)
    full_text = fields["full_text"]

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

    # If text length threshold passes and it is not navigation/scaffold content, allow it.
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
