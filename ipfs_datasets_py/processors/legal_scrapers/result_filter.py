"""
Advanced Result Filtering for Legal Search.

This module provides comprehensive filtering capabilities for search results
with support for domain, date, jurisdiction, quality scoring, and more.

Features:
- Domain-based filtering (whitelist/blacklist, .gov prioritization)
- Date range filtering with flexible parsing
- Jurisdiction-aware filtering (federal/state/local)
- Result quality scoring (authority, recency, relevance)
- Enhanced deduplication (fuzzy URL matching)
- Filter chaining and composition
- Configurable filter strategies

Usage:
    from ipfs_datasets_py.processors.legal_scrapers import ResultFilter
    
    filter = ResultFilter(
        domain_whitelist=[".gov", ".edu"],
        jurisdiction="federal",
        min_quality_score=0.6
    )
    
    filtered_results = filter.filter_results(results)
"""

import re
import logging
from typing import List, Dict, Optional, Set, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlparse
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


@dataclass
class FilterConfig:
    """Configuration for result filtering."""
    # Domain filtering
    domain_whitelist: List[str] = field(default_factory=list)
    domain_blacklist: List[str] = field(default_factory=list)
    prioritize_gov: bool = True
    prioritize_edu: bool = True
    
    # Date filtering
    min_date: Optional[datetime] = None
    max_date: Optional[datetime] = None
    date_range_days: Optional[int] = None  # e.g., last 365 days
    
    # Jurisdiction filtering
    jurisdiction: Optional[str] = None  # "federal", "state", "local", "mixed"
    state_filter: Optional[str] = None  # e.g., "California", "CA"
    
    # Quality filtering
    min_quality_score: float = 0.0
    max_results: Optional[int] = None
    
    # Deduplication
    enable_fuzzy_dedup: bool = True
    fuzzy_threshold: float = 0.9  # URL similarity threshold
    
    # Result scoring weights
    authority_weight: float = 0.4
    recency_weight: float = 0.3
    relevance_weight: float = 0.3


@dataclass
class FilteredResult:
    """Result with filtering metadata."""
    title: str
    url: str
    snippet: str
    domain: Optional[str] = None
    published_date: Optional[str] = None
    jurisdiction: Optional[str] = None
    quality_score: float = 0.0
    authority_score: float = 0.0
    recency_score: float = 0.0
    relevance_score: float = 0.0
    matched_filters: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class ResultFilter:
    """
    Advanced result filter with domain, date, jurisdiction, and quality filtering.
    
    Provides comprehensive filtering capabilities for search results with:
    - Domain whitelist/blacklist (.gov, .edu prioritization)
    - Date range filtering with flexible parsing
    - Jurisdiction detection and filtering (federal/state/local)
    - Quality scoring based on authority, recency, and relevance
    - Enhanced deduplication with fuzzy URL matching
    - Filter chaining and composition
    
    Example:
        >>> config = FilterConfig(
        ...     domain_whitelist=[".gov", ".edu"],
        ...     jurisdiction="federal",
        ...     min_quality_score=0.6,
        ...     date_range_days=365
        ... )
        >>> filter = ResultFilter(config)
        >>> filtered = filter.filter_results(search_results)
    """
    
    # Government domains for authority scoring
    GOV_DOMAINS = {
        ".gov": 1.0,
        ".mil": 0.9,
        ".edu": 0.8,
        ".org": 0.6,
    }
    
    # Federal agency patterns
    FEDERAL_PATTERNS = [
        r"epa\.gov",
        r"osha\.gov",
        r"fda\.gov",
        r"sec\.gov",
        r"ftc\.gov",
        r"doj\.gov",
        r"hhs\.gov",
        r"dol\.gov",
        r"hud\.gov",
        r"whitehouse\.gov",
        r"congress\.gov",
        r"supremecourt\.gov",
        r"uscourts\.gov",
    ]
    
    # State government patterns
    STATE_PATTERNS = [
        r"\.state\.[a-z]{2}\.us",
        r"\.[a-z]{2}\.gov",
    ]
    
    def __init__(self, config: Optional[FilterConfig] = None):
        """Initialize result filter.
        
        Args:
            config: Filter configuration (uses defaults if None)
        """
        self.config = config or FilterConfig()
        
        # Compile patterns for performance
        self.federal_patterns = [re.compile(p, re.IGNORECASE) for p in self.FEDERAL_PATTERNS]
        self.state_patterns = [re.compile(p, re.IGNORECASE) for p in self.STATE_PATTERNS]
        
        logger.info("Result filter initialized")
    
    def filter_results(
        self,
        results: List[Dict[str, Any]],
        apply_scoring: bool = True,
        apply_deduplication: bool = True
    ) -> List[FilteredResult]:
        """
        Filter and score search results.
        
        Args:
            results: List of search result dictionaries
            apply_scoring: Whether to calculate quality scores
            apply_deduplication: Whether to remove duplicates
            
        Returns:
            List of FilteredResult objects that passed filters
        """
        filtered = []
        
        for result in results:
            # Convert to FilteredResult
            filtered_result = self._convert_result(result)
            
            # Apply filters
            if not self._passes_filters(filtered_result):
                continue
            
            # Calculate scores
            if apply_scoring:
                self._calculate_scores(filtered_result)
                
                # Check minimum quality score
                if filtered_result.quality_score < self.config.min_quality_score:
                    continue
            
            filtered.append(filtered_result)
        
        # Deduplicate
        if apply_deduplication:
            filtered = self._deduplicate_results(filtered)
        
        # Sort by quality score (highest first)
        if apply_scoring:
            filtered.sort(key=lambda r: r.quality_score, reverse=True)
        
        # Limit results
        if self.config.max_results:
            filtered = filtered[:self.config.max_results]
        
        logger.info(f"Filtered {len(results)} results to {len(filtered)}")
        
        return filtered
    
    def _convert_result(self, result: Dict[str, Any]) -> FilteredResult:
        """Convert raw result dict to FilteredResult."""
        # Extract domain if not present
        domain = result.get("domain")
        if not domain and "url" in result:
            try:
                domain = urlparse(result["url"]).netloc
            except Exception:
                domain = None
        
        return FilteredResult(
            title=result.get("title", ""),
            url=result.get("url", ""),
            snippet=result.get("snippet", result.get("description", "")),
            domain=domain,
            published_date=result.get("published_date"),
            jurisdiction=result.get("jurisdiction"),
            metadata=result.get("metadata", {})
        )
    
    def _passes_filters(self, result: FilteredResult) -> bool:
        """Check if result passes all filters."""
        matched_filters = []
        
        # Domain whitelist
        if self.config.domain_whitelist:
            if not self._matches_domain_list(result.domain, self.config.domain_whitelist):
                return False
            matched_filters.append("domain_whitelist")
        
        # Domain blacklist
        if self.config.domain_blacklist:
            if self._matches_domain_list(result.domain, self.config.domain_blacklist):
                return False
            matched_filters.append("domain_blacklist_passed")
        
        # Date range
        if self.config.min_date or self.config.max_date or self.config.date_range_days:
            if not self._passes_date_filter(result):
                return False
            matched_filters.append("date_range")
        
        # Jurisdiction
        if self.config.jurisdiction:
            detected_jurisdiction = self._detect_jurisdiction(result)
            result.jurisdiction = detected_jurisdiction
            
            if self.config.jurisdiction != "mixed" and detected_jurisdiction != self.config.jurisdiction:
                return False
            matched_filters.append("jurisdiction")
        
        # State filter
        if self.config.state_filter:
            if not self._matches_state(result):
                return False
            matched_filters.append("state")
        
        result.matched_filters = matched_filters
        return True
    
    def _matches_domain_list(self, domain: Optional[str], domain_list: List[str]) -> bool:
        """Check if domain matches any pattern in list."""
        if not domain:
            return False
        
        domain_lower = domain.lower()
        
        for pattern in domain_list:
            if pattern.startswith("."):
                # TLD pattern (e.g., ".gov")
                if domain_lower.endswith(pattern):
                    return True
            elif pattern in domain_lower:
                return True
        
        return False
    
    def _passes_date_filter(self, result: FilteredResult) -> bool:
        """Check if result passes date filters."""
        if not result.published_date:
            # If no date, assume it passes (could be recent)
            return True
        
        try:
            # Parse date (handle various formats)
            result_date = self._parse_date(result.published_date)
            
            if self.config.date_range_days:
                cutoff_date = datetime.now() - timedelta(days=self.config.date_range_days)
                if result_date < cutoff_date:
                    return False
            
            if self.config.min_date and result_date < self.config.min_date:
                return False
            
            if self.config.max_date and result_date > self.config.max_date:
                return False
            
            return True
        
        except Exception as e:
            logger.debug(f"Failed to parse date '{result.published_date}': {e}")
            return True  # Pass if can't parse
    
    def _parse_date(self, date_str: str) -> datetime:
        """Parse date string with flexible formats."""
        # Try common formats
        formats = [
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%m/%d/%Y",
            "%B %d, %Y",
            "%b %d, %Y",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        
        raise ValueError(f"Unable to parse date: {date_str}")
    
    def _detect_jurisdiction(self, result: FilteredResult) -> str:
        """Detect jurisdiction from URL and content."""
        if not result.domain:
            return "unknown"
        
        domain_lower = result.domain.lower()
        
        # Check federal patterns
        for pattern in self.federal_patterns:
            if pattern.search(domain_lower):
                return "federal"
        
        # Check state patterns
        for pattern in self.state_patterns:
            if pattern.search(domain_lower):
                return "state"
        
        # Check for local/municipal keywords
        local_keywords = ["city", "county", "town", "municipality", "borough"]
        for keyword in local_keywords:
            if keyword in domain_lower:
                return "local"
        
        return "unknown"
    
    def _matches_state(self, result: FilteredResult) -> bool:
        """Check if result matches state filter."""
        state_filter = self.config.state_filter.lower()
        
        # Check in domain
        if result.domain and state_filter in result.domain.lower():
            return True
        
        # Check in title
        if state_filter in result.title.lower():
            return True
        
        # Check in snippet
        if state_filter in result.snippet.lower():
            return True
        
        return False
    
    def _calculate_scores(self, result: FilteredResult):
        """Calculate quality scores for result."""
        # Authority score (based on domain)
        result.authority_score = self._calculate_authority_score(result)
        
        # Recency score (based on published date)
        result.recency_score = self._calculate_recency_score(result)
        
        # Relevance score (based on content)
        result.relevance_score = self._calculate_relevance_score(result)
        
        # Weighted quality score
        result.quality_score = (
            result.authority_score * self.config.authority_weight +
            result.recency_score * self.config.recency_weight +
            result.relevance_score * self.config.relevance_weight
        )
    
    def _calculate_authority_score(self, result: FilteredResult) -> float:
        """Calculate authority score based on domain."""
        if not result.domain:
            return 0.5
        
        domain_lower = result.domain.lower()
        
        # Check government domains
        for tld, score in self.GOV_DOMAINS.items():
            if domain_lower.endswith(tld):
                return score
        
        # Federal agency gets highest score
        for pattern in self.federal_patterns:
            if pattern.search(domain_lower):
                return 1.0
        
        # State government gets high score
        for pattern in self.state_patterns:
            if pattern.search(domain_lower):
                return 0.9
        
        # Default score
        return 0.5
    
    def _calculate_recency_score(self, result: FilteredResult) -> float:
        """Calculate recency score based on published date."""
        if not result.published_date:
            return 0.5  # Unknown date = medium score
        
        try:
            result_date = self._parse_date(result.published_date)
            days_old = (datetime.now() - result_date).days
            
            # Score decreases with age
            if days_old < 30:
                return 1.0
            elif days_old < 90:
                return 0.9
            elif days_old < 180:
                return 0.8
            elif days_old < 365:
                return 0.7
            elif days_old < 730:
                return 0.6
            else:
                return 0.5
        
        except Exception:
            return 0.5
    
    def _calculate_relevance_score(self, result: FilteredResult) -> float:
        """Calculate relevance score based on content."""
        score = 0.5  # Base score
        
        # Check for legal keywords in title/snippet
        legal_keywords = [
            "regulation", "law", "statute", "code", "rule", "requirement",
            "compliance", "enforcement", "penalty", "violation"
        ]
        
        title_lower = result.title.lower()
        snippet_lower = result.snippet.lower()
        
        # Title keywords worth more
        for keyword in legal_keywords:
            if keyword in title_lower:
                score += 0.05
            if keyword in snippet_lower:
                score += 0.02
        
        return min(score, 1.0)
    
    def _deduplicate_results(self, results: List[FilteredResult]) -> List[FilteredResult]:
        """Remove duplicate results using fuzzy URL matching."""
        if not self.config.enable_fuzzy_dedup:
            # Simple deduplication by exact URL
            seen = set()
            deduplicated = []
            for result in results:
                url_lower = result.url.lower().strip()
                if url_lower not in seen:
                    seen.add(url_lower)
                    deduplicated.append(result)
            return deduplicated
        
        # Fuzzy deduplication
        deduplicated = []
        
        for result in results:
            is_duplicate = False
            
            for existing in deduplicated:
                similarity = self._url_similarity(result.url, existing.url)
                if similarity >= self.config.fuzzy_threshold:
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                deduplicated.append(result)
        
        logger.debug(f"Deduplicated: {len(results)} -> {len(deduplicated)} results")
        
        return deduplicated
    
    def _url_similarity(self, url1: str, url2: str) -> float:
        """Calculate similarity between two URLs."""
        # Normalize URLs
        url1 = url1.lower().strip().rstrip("/")
        url2 = url2.lower().strip().rstrip("/")
        
        # Use sequence matcher
        return SequenceMatcher(None, url1, url2).ratio()
    
    def filter_by_custom_function(
        self,
        results: List[FilteredResult],
        filter_func: Callable[[FilteredResult], bool]
    ) -> List[FilteredResult]:
        """Apply custom filter function to results.
        
        Args:
            results: Results to filter
            filter_func: Function that returns True if result should be kept
            
        Returns:
            Filtered results
        """
        return [r for r in results if filter_func(r)]
    
    def chain_filters(
        self,
        results: List[Dict[str, Any]],
        configs: List[FilterConfig]
    ) -> List[FilteredResult]:
        """Apply multiple filter configurations in sequence.
        
        Args:
            results: Original results
            configs: List of filter configurations to apply in order
            
        Returns:
            Results after all filters applied
        """
        current_results = results
        
        for i, config in enumerate(configs):
            filter_instance = ResultFilter(config)
            filtered = filter_instance.filter_results(current_results)
            
            # Convert back to dict for next iteration (except last)
            if i < len(configs) - 1:
                current_results = [
                    {
                        "title": r.title,
                        "url": r.url,
                        "snippet": r.snippet,
                        "domain": r.domain,
                        "published_date": r.published_date,
                        "jurisdiction": r.jurisdiction,
                        "metadata": r.metadata
                    }
                    for r in filtered
                ]
            else:
                return filtered
        
        return []
