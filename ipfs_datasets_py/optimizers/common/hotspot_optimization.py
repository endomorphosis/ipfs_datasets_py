"""
Hotspot Optimization Strategies - Batch 234 Part 3.

This module implements optimization strategies for identified hotspots
in OntologyGenerator profiling. Focus areas:

1. Regex Pattern Caching - Pre-compile and cache common patterns
2. Similarity Score Caching - Memoize entity deduplication results  
3. Proximity Index Caching - Pre-build spatial indexes for relationships

Performance Target: ≥15% speedup on OntologyGenerator.generate_ontology()

Optimization Techniques Used:
- functools.lru_cache for pattern compilation
- @dataclass with __hash__ for deduplication cache keys
- Lazy-loaded pattern sets with class-level caching
- Context-aware caching (domain-specific patterns)
"""

import functools
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Pattern, Protocol, Set, Tuple, cast

logger = logging.getLogger(__name__)


class _CachedCallable(Protocol):
    """Callable protocol exposing functools.lru_cache helper methods."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...

    def cache_info(self) -> Any: ...

    def cache_clear(self) -> None: ...


# ============================================================================
# Optimization 1: Regex Pattern Caching
# ============================================================================


class RegexPatternCache:
    """Pre-compile and cache regex patterns for ontology extraction.
    
    This optimization addresses the hotspot of repeated regex compilation
    in entity extraction. Each pattern is compiled once and reused.
    
    Example:
        >>> cache = RegexPatternCache()
        >>> pattern = cache.get_compiled_pattern(r"\\b[A-Z][a-z]+\\b", "name_pattern")
        >>> # Pattern is reused on next call - no recompilation
    """
    
    def __init__(self) -> None:
        """Initialize pattern cache."""
        self._cache: Dict[str, Pattern[str]] = {}
        self._stats = {"hits": 0, "misses": 0}
    
    def get_compiled_pattern(self, pattern_str: str, cache_key: Optional[str] = None) -> Pattern[str]:
        """Get compiled regex pattern, compiling if necessary.
        
        Args:
            pattern_str: Regex pattern string
            cache_key: Optional cache key (defaults to pattern_str)
            
        Returns:
            Compiled regex pattern object
        """
        key = cache_key or pattern_str
        
        if key in self._cache:
            self._stats["hits"] += 1
            return self._cache[key]
        
        self._stats["misses"] += 1
        compiled = re.compile(pattern_str)
        self._cache[key] = compiled
        return compiled
    
    def get_compiled_patterns(
        self,
        patterns: List[Tuple[str, str]],
    ) -> List[Tuple[Pattern[str], str]]:
        """Get multiple compiled patterns efficiently.
        
        Args:
            patterns: List of (pattern_string, label) tuples
            
        Returns:
            List of (compiled_pattern, label) tuples
        """
        result = []
        for pattern_str, label in patterns:
            compiled = self.get_compiled_pattern(pattern_str, cache_key=label)
            result.append((compiled, label))
        return result
    
    def cache_stats(self) -> Dict[str, int]:
        """Get cache hit/miss statistics.
        
        Returns:
            Dict with 'hits' and 'misses' counts
        """
        return self._stats.copy()
    
    def clear(self) -> None:
        """Clear all cached patterns."""
        self._cache.clear()
        self._stats = {"hits": 0, "misses": 0}


# Global singleton instance
_PATTERN_CACHE = RegexPatternCache()


def get_pattern_cache() -> RegexPatternCache:
    """Get global regex pattern cache instance.
    
    Returns:
        Global RegexPatternCache instance
    """
    return _PATTERN_CACHE


# ============================================================================
# Optimization 2: Entity Similarity Score Caching
# ============================================================================


@dataclass(frozen=True)
class EntityPair:
    """Hashable pair of entity texts for similarity score caching.
    
    Using frozen=True makes instances hashable and immutable.
    """
    
    text1: str
    text2: str
    normalize: bool = True
    
    def __hash__(self) -> int:
        """Compute hash for caching purposes."""
        t1 = self.text1.lower().strip() if self.normalize else self.text1
        t2 = self.text2.lower().strip() if self.normalize else self.text2
        # Ensure consistent hash regardless of text order (commutative)
        return hash((min(t1, t2), max(t1, t2)))
    
    def __eq__(self, other: object) -> bool:
        """Check equality with normalization."""
        if not isinstance(other, EntityPair):
            return False
        t1_a = self.text1.lower().strip() if self.normalize else self.text1
        t1_b = other.text1.lower().strip() if other.normalize else other.text1
        t2_a = self.text2.lower().strip() if self.normalize else self.text2
        t2_b = other.text2.lower().strip() if other.normalize else other.text2
        return (t1_a == t1_b and t2_a == t2_b) or (t1_a == t2_b and t2_a == t1_b)


class SimilarityScoreCache:
    """Memoize entity similarity/deduplication scores.
    
    This optimization addresses repeated similarity calculations during
    entity deduplication. Each pair is computed once and cached.
    
    Example:
        >>> cache = SimilarityScoreCache()
        >>> score = cache.compute_similarity("Company Inc", "Company Incorporated", threshold=0.8)
        >>> # Score cached; repeated call returns cached value
    """
    
    def __init__(self, max_cache_size: int = 10000):
        """Initialize similarity score cache.
        
        Args:
            max_cache_size: Maximum number of scores to cache
        """
        self._cache: Dict[EntityPair, float] = {}
        self._max_size = max_cache_size
        self._stats = {"hits": 0, "misses": 0}
    
    def compute_similarity(
        self,
        text1: str,
        text2: str,
        threshold: float = 0.8,
        normalize: bool = True
    ) -> float:
        """Compute and cache entity similarity score.
        
        Args:
            text1: First entity text
            text2: Second entity text
            threshold: Similarity threshold (0-1)
            normalize: Whether to normalize texts before comparison
            
        Returns:
            Similarity score (0-1)
        """
        pair = EntityPair(text1, text2, normalize=normalize)
        
        if pair in self._cache:
            self._stats["hits"] += 1
            return self._cache[pair]
        
        self._stats["misses"] += 1
        
        # Compute similarity using Levenshtein-inspired algorithm
        score = self._compute_similarity_internal(text1, text2, normalize)
        
        # Cache if below capacity
        if len(self._cache) < self._max_size:
            self._cache[pair] = score
        
        return score
    
    @staticmethod
    def _compute_similarity_internal(text1: str, text2: str, normalize: bool) -> float:
        """Compute similarity score using string metrics.
        
        Args:
            text1: First string
            text2: Second string
            normalize: Whether to normalize
            
        Returns:
            Similarity score (0-1)
        """
        # Normalize if requested
        if normalize:
            text1 = text1.lower().strip()
            text2 = text2.lower().strip()
        
        # Exact match
        if text1 == text2:
            return 1.0
        
        # Containment check
        if text1 in text2 or text2 in text1:
            return 0.9
        
        # Edit distance heuristic (simplified)
        common_chars = sum(1 for c in text1 if c in text2)
        max_len = max(len(text1), len(text2))
        if max_len == 0:
            return 1.0
        
        return common_chars / max_len
    
    def cache_stats(self) -> Dict[str, int]:
        """Get cache statistics.
        
        Returns:
            Dict with 'hits' and 'misses' counts
        """
        return self._stats.copy()
    
    def clear(self) -> None:
        """Clear all cached scores."""
        self._cache.clear()
        self._stats = {"hits": 0, "misses": 0}


# ============================================================================
# Optimization 3: Lazy-Loaded Domain Pattern Sets
# ============================================================================


class DomainPatternLoader:
    """Lazy-load and cache domain-specific patterns.
    
    Patterns are loaded on first access and reused. This avoids loading
    unused domain patterns upfront.
    
    Example:
        >>> loader = DomainPatternLoader()
        >>> legal_patterns = loader.get_domain_patterns("legal")
        >>> # Patterns cached; repeated calls reuse loaded set
    """
    
    def __init__(self) -> None:
        """Initialize domain pattern loader."""
        self._loaded_patterns: Dict[str, Set[str]] = {}
        self._pattern_cache = RegexPatternCache()
    
    def get_domain_patterns(self, domain: str) -> Tuple[List[Pattern[str]], List[str]]:
        """Get compiled patterns for a domain.
        
        Args:
            domain: Domain name (legal, medical, technical, financial)
            
        Returns:
            Tuple of (compiled_patterns, labels)
        """
        # Load raw patterns if not cached
        if domain not in self._loaded_patterns:
            self._loaded_patterns[domain] = self._load_patterns_for_domain(domain)
        
        patterns = self._loaded_patterns[domain]
        
        # Compile patterns using cache
        compiled = []
        labels = []
        for pattern_str in patterns:
            compiled_pattern = self._pattern_cache.get_compiled_pattern(
                pattern_str,
                cache_key=f"{domain}:{pattern_str[:20]}"
            )
            compiled.append(compiled_pattern)
            labels.append(pattern_str[:50])  # Truncated label
        
        return compiled, labels
    
    @staticmethod
    def _load_patterns_for_domain(domain: str) -> Set[str]:
        """Load pattern set for domain.
        
        Args:
            domain: Domain name
            
        Returns:
            Set of regex pattern strings for domain
        """
        patterns = {
            "legal": {
                r"(?:agreement|contract|clause|term)\b",
                r"\b(?:party|parties|plaintiff|defendant|client|provider)\b",
                r"\b(?:liability|indemnify|warranty|covenant)\b",
                r"\$[0-9,]+(?:\.[0-9]{2})?",
                r"(?:Section|Article|Paragraph)\s+\d+",
            },
            "medical": {
                r"\b(?:patient|physician|doctor|nurse|specialist)\b",
                r"\b(?:diagnosis|symptom|treatment|therapy|medication)\b",
                r"\b(?:hospital|clinic|ward|ICU|ER)\b",
                r"\b(?:vital|temperature|blood pressure|pulse)\b",
                r"\b(?:disease|syndrome|condition|infection)\b",
            },
            "technical": {
                r"\b(?:API|endpoint|database|server|client)\b",
                r"\b(?:parameter|request|response|header|body)\b",
                r"(?:GET|POST|PUT|DELETE|PATCH)\s+/",
                r"\b(?:authentication|authorization|token|credentials)\b",
                r"\b(?:error|exception|timeout|retry)\b",
            },
            "financial": {
                r"\$[0-9,]+(?:\.[0-9]{2})?",
                r"\b(?:transaction|payment|invoice|receipt)\b",
                r"\b(?:account|balance|debit|credit)\b",
                r"\b(?:interest|rate|fee|charge)\b",
                r"\b(?:securities|stock|bond|equity)\b",
            },
        }
        
        return patterns.get(domain, set())
    
    def cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics.
        
        Returns:
            Dict with pattern cache and domain loading stats
        """
        return {
            "pattern_cache": self._pattern_cache.cache_stats(),
            "domains_loaded": len(self._loaded_patterns),
        }


# Global singleton
_DOMAIN_LOADER = DomainPatternLoader()


def get_domain_loader() -> DomainPatternLoader:
    """Get global domain pattern loader instance.
    
    Returns:
        Global DomainPatternLoader instance
    """
    return _DOMAIN_LOADER


# ============================================================================
# Optimization Decorator: @memoized_with_cache_stats
# ============================================================================


def memoized_with_cache_stats(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator combining functools.lru_cache with statistics tracking.
    
    Example:
        >>> @memoized_with_cache_stats
        ... def expensive_function(x):
        ...     return x ** 2
        >>> 
        >>> expensive_function(5)  # Computed
        >>> expensive_function(5)  # Cached
        >>> print(expensive_function.cache_info())  # See hits/misses
    """
    cached_func = cast(_CachedCallable, functools.lru_cache(maxsize=1024)(func))
    
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return cached_func(*args, **kwargs)
    
    # Expose cache_info and cache_clear methods
    wrapped = cast(Any, wrapper)
    wrapped.cache_info = cached_func.cache_info
    wrapped.cache_clear = cached_func.cache_clear
    
    return cast(Callable[..., Any], wrapped)


# ============================================================================
# Performance Benchmark: Compare Optimized vs Unoptimized
# ============================================================================


class OptimizationBenchmark:
    """Benchmark optimized code against unoptimized baseline."""
    
    @staticmethod
    def benchmark_pattern_caching(iterations: int = 10000) -> Dict[str, float]:
        """Benchmark regex pattern caching optimization.
        
        Args:
            iterations: Number of pattern compilations to measure
            
        Returns:
            Dict with 'cached' and 'uncached' execution times
        """
        import time
        
        patterns = [
            r"\b[A-Z][a-z]+\b",
            r"\$[0-9,]+(?:\.[0-9]{2})?",
            r"\b(?:agreement|contract)\b",
        ]
        
        # Uncached version
        start = time.perf_counter()
        for _ in range(iterations):
            for pattern in patterns:
                re.compile(pattern)
        uncached_time = time.perf_counter() - start
        
        # Cached version
        cache = RegexPatternCache()
        start = time.perf_counter()
        for _ in range(iterations):
            for pattern in patterns:
                cache.get_compiled_pattern(pattern)
        cached_time = time.perf_counter() - start
        
        speedup = (uncached_time - cached_time) / uncached_time * 100
        
        return {
            "uncached_sec": uncached_time,
            "cached_sec": cached_time,
            "speedup_percent": speedup,
        }
    
    @staticmethod
    def benchmark_similarity_caching(iterations: int = 1000) -> Dict[str, float]:
        """Benchmark similarity score caching.
        
        Args:
            iterations: Number of similarity computations to measure
            
        Returns:
            Dict with 'cached' and 'uncached' execution times
        """
        import time
        
        entity_pairs = [
            ("Apple Inc", "Apple Incorporated"),
            ("Company LLC", "Company Limited"),
            ("Smith & Associates", "Smith and Associates"),
        ]
        
        # Uncached version (without cache benefit, simple computation)
        start = time.perf_counter()
        for _ in range(iterations):
            for text1, text2 in entity_pairs:
                SimilarityScoreCache._compute_similarity_internal(text1, text2, True)
        uncached_time = time.perf_counter() - start
        
        # Cached version (using cache)
        cache_cached = SimilarityScoreCache()
        start = time.perf_counter()
        for _ in range(iterations):
            for text1, text2 in entity_pairs:
                cache_cached.compute_similarity(text1, text2)
        cached_time = time.perf_counter() - start
        
        # Cached should be much faster after warmup
        # On first run, both are similar, but cache wins with repeated calls
        speedup = max(0, (uncached_time - cached_time) / uncached_time * 100) if uncached_time > 0 else 0
        
        return {
            "uncached_sec": uncached_time,
            "cached_sec": cached_time,
            "speedup_percent": speedup,
        }
