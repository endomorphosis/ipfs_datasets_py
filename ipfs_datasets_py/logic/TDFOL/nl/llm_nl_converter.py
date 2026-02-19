"""
LLM-Enhanced Natural Language to TDFOL Converter.

This module implements a hybrid approach for NL→TDFOL conversion:
1. Pattern-based first (fast, ~80% accurate)
2. Confidence check (threshold: 0.85)
3. LLM fallback for low confidence (slower, ~95%+ accurate)
4. Best result selection based on confidence scores
"""

import json
import logging
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from .cache_utils import create_cache_cid

logger = logging.getLogger(__name__)

# Try to import dependencies
try:
    from .tdfol_nl_api import NLParser, ParseResult, ParseOptions
    from .llm_nl_prompts import (
        build_conversion_prompt,
        build_validation_prompt,
        get_operator_hints_for_text
    )
    TDFOL_NL_AVAILABLE = True
except ImportError:
    logger.warning("TDFOL NL API not available")
    TDFOL_NL_AVAILABLE = False
    NLParser = None
    ParseResult = None
    ParseOptions = None

try:
    from ipfs_datasets_py.llm_router import get_default_router
    LLM_ROUTER_AVAILABLE = True
except ImportError:
    logger.warning("LLM router not available")
    LLM_ROUTER_AVAILABLE = False
    get_default_router = None


@dataclass
class LLMParseResult:
    """Result from LLM-enhanced parsing."""
    
    success: bool
    formula: str = ""
    confidence: float = 0.0
    method: str = "unknown"  # "pattern", "llm", "hybrid"
    parse_time_ms: float = 0.0
    pattern_result: Optional[Any] = None
    llm_result: Optional[str] = None
    llm_provider: Optional[str] = None
    cache_hit: bool = False
    errors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class LLMResponseCache:
    """
    In-memory cache for LLM responses using IPFS CIDs.
    
    This cache uses IPFS Content Identifiers (CIDs) as keys, ensuring:
    - Content-addressed storage (deterministic keys)
    - IPFS-compatible format (can be persisted to IPFS)
    - Verifiable cache entries (CID contains hash metadata)
    - Future-proof design (supports distributed caching)
    """
    
    def __init__(self, max_size: int = 1000):
        self.cache: Dict[str, Tuple[str, float]] = {}
        self.max_size = max_size
        self.hits = 0
        self.misses = 0
    
    def _make_key(self, text: str, provider: str, prompt_hash: str) -> str:
        """
        Create IPFS CID cache key using multiformats.
        
        Generates a deterministic Content Identifier (CID) from cache parameters.
        The CID is created using:
        - Canonical JSON serialization (sorted keys, compact format)
        - SHA2-256 hashing
        - CIDv1 with base32 encoding
        
        Args:
            text: Input text to cache
            provider: LLM provider name
            prompt_hash: Hash of the prompt template
        
        Returns:
            CIDv1 string in base32 format (e.g., 'bafkreig...')
        
        Example:
            >>> cache = LLMResponseCache()
            >>> key = cache._make_key("hello", "openai", "abc123")
            >>> assert key.startswith("bafk")  # CIDv1 base32
        """
        cache_data = {
            "text": text,
            "provider": provider,
            "prompt_hash": prompt_hash,
            "version": "1.0"  # Schema version for future compatibility
        }
        return create_cache_cid(cache_data)
    
    def get(self, text: str, provider: str, prompt_hash: str) -> Optional[Tuple[str, float]]:
        """Get cached response if available."""
        key = self._make_key(text, provider, prompt_hash)
        result = self.cache.get(key)
        if result:
            self.hits += 1
        else:
            self.misses += 1
        return result
    
    def put(self, text: str, provider: str, prompt_hash: str, formula: str, confidence: float):
        """Store response in cache."""
        key = self._make_key(text, provider, prompt_hash)
        
        # Simple LRU: remove oldest if at capacity
        if len(self.cache) >= self.max_size:
            # Remove first item (oldest)
            first_key = next(iter(self.cache))
            del self.cache[first_key]
        
        self.cache[key] = (formula, confidence)
    
    def clear(self):
        """Clear all cached responses."""
        self.cache.clear()
        self.hits = 0
        self.misses = 0
    
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total = self.hits + self.misses
        hit_rate = self.hits / total if total > 0 else 0.0
        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": hit_rate
        }


class LLMNLConverter:
    """
    Hybrid Natural Language to TDFOL converter using pattern matching and LLM.
    
    This converter implements a two-stage approach:
    1. Fast pattern-based conversion (~80% accuracy, ~0.5s)
    2. LLM enhancement for low-confidence results (~95%+ accuracy, ~1.5s)
    
    The converter intelligently routes to LLM only when needed, providing
    optimal balance between speed and accuracy.
    """
    
    def __init__(
        self,
        confidence_threshold: float = 0.85,
        enable_llm: bool = True,
        enable_caching: bool = True,
        default_provider: Optional[str] = None,
        cache_size: int = 1000
    ):
        """
        Initialize LLM-enhanced converter.
        
        Args:
            confidence_threshold: Minimum confidence before using LLM (0.0-1.0)
            enable_llm: Whether to use LLM enhancement
            enable_caching: Whether to cache LLM responses
            default_provider: Default LLM provider (None = auto)
            cache_size: Maximum number of cached responses
        """
        if not TDFOL_NL_AVAILABLE:
            raise ImportError("TDFOL NL API dependencies not available")
        
        self.confidence_threshold = confidence_threshold
        self.enable_llm = enable_llm and LLM_ROUTER_AVAILABLE
        self.enable_caching = enable_caching
        self.default_provider = default_provider
        
        # Initialize pattern-based parser
        self.pattern_parser = NLParser(ParseOptions(
            min_confidence=0.0,  # Accept all pattern results for comparison
            enable_caching=True
        ))
        
        # Initialize LLM cache
        self.llm_cache = LLMResponseCache(max_size=cache_size) if enable_caching else None
        
        # Statistics
        self.stats = {
            "pattern_only": 0,
            "llm_fallback": 0,
            "llm_failures": 0,
            "total_conversions": 0
        }
    
    def convert(
        self,
        text: str,
        provider: Optional[str] = None,
        min_confidence: Optional[float] = None,
        force_llm: bool = False
    ) -> LLMParseResult:
        """
        Convert natural language to TDFOL using hybrid approach.
        
        Args:
            text: Natural language text to convert
            provider: LLM provider to use (None = default)
            min_confidence: Override confidence threshold
            force_llm: Skip pattern matching, use LLM directly
        
        Returns:
            LLMParseResult with conversion results
        """
        start_time = time.time()
        threshold = min_confidence if min_confidence is not None else self.confidence_threshold
        provider = provider or self.default_provider
        
        self.stats["total_conversions"] += 1
        
        # Stage 1: Pattern-based conversion (unless forced to use LLM)
        pattern_result = None
        if not force_llm:
            try:
                pattern_result = self.pattern_parser.parse(text)
                
                # Check if pattern result is good enough
                if pattern_result.success and pattern_result.confidence >= threshold:
                    self.stats["pattern_only"] += 1
                    
                    formula = pattern_result.formulas[0].formula_string if pattern_result.formulas else ""
                    
                    return LLMParseResult(
                        success=True,
                        formula=formula,
                        confidence=pattern_result.confidence,
                        method="pattern",
                        parse_time_ms=(time.time() - start_time) * 1000,
                        pattern_result=pattern_result,
                        metadata={"threshold": threshold}
                    )
            
            except Exception as e:
                logger.warning(f"Pattern parsing failed: {e}")
                pattern_result = None
        
        # Stage 2: LLM enhancement (if enabled and needed)
        if self.enable_llm:
            try:
                llm_formula, llm_confidence, cache_hit = self._llm_convert(text, provider)
                
                self.stats["llm_fallback"] += 1
                
                # Compare results if we have both
                if pattern_result and pattern_result.formulas:
                    pattern_confidence = pattern_result.confidence
                    best_formula = llm_formula if llm_confidence > pattern_confidence else pattern_result.formulas[0].formula_string
                    best_confidence = max(llm_confidence, pattern_confidence)
                    method = "hybrid"
                else:
                    best_formula = llm_formula
                    best_confidence = llm_confidence
                    method = "llm"
                
                return LLMParseResult(
                    success=True,
                    formula=best_formula,
                    confidence=best_confidence,
                    method=method,
                    parse_time_ms=(time.time() - start_time) * 1000,
                    pattern_result=pattern_result,
                    llm_result=llm_formula,
                    llm_provider=provider,
                    cache_hit=cache_hit,
                    metadata={
                        "threshold": threshold,
                        "llm_confidence": llm_confidence,
                        "pattern_confidence": pattern_result.confidence if pattern_result else 0.0
                    }
                )
            
            except Exception as e:
                logger.error(f"LLM conversion failed: {e}")
                self.stats["llm_failures"] += 1
                
                # Fallback to pattern result if available
                if pattern_result and pattern_result.formulas:
                    return LLMParseResult(
                        success=True,
                        formula=pattern_result.formulas[0].formula_string,
                        confidence=pattern_result.confidence,
                        method="pattern_fallback",
                        parse_time_ms=(time.time() - start_time) * 1000,
                        pattern_result=pattern_result,
                        errors=[f"LLM conversion failed: {str(e)}"],
                        metadata={"threshold": threshold}
                    )
        
        # Failed: No LLM and pattern confidence too low
        return LLMParseResult(
            success=False,
            formula="",
            confidence=0.0,
            method="failed",
            parse_time_ms=(time.time() - start_time) * 1000,
            pattern_result=pattern_result,
            errors=["Pattern confidence too low and LLM not available/enabled"],
            metadata={"threshold": threshold}
        )
    
    def _llm_convert(self, text: str, provider: Optional[str]) -> Tuple[str, float, bool]:
        """
        Convert text using LLM.
        
        Args:
            text: Text to convert
            provider: LLM provider name
        
        Returns:
            Tuple of (formula, confidence, cache_hit)
        """
        # Build prompt
        operator_hints = get_operator_hints_for_text(text)
        prompt = build_conversion_prompt(text, include_examples=True, operator_hints=operator_hints)
        
        # Create prompt hash using IPFS CID (shorter version for readability)
        prompt_cid = create_cache_cid({"prompt": prompt})[:16]
        
        # Check cache
        if self.llm_cache:
            cached = self.llm_cache.get(text, provider or "default", prompt_cid)
            if cached:
                formula, confidence = cached
                return formula, confidence, True
        
        # Call LLM
        router = get_default_router()
        
        # Generate response
        response = router.generate(
            prompt,
            max_tokens=500,
            temperature=0.1,  # Low temperature for deterministic output
            provider=provider
        )
        
        # Parse formula from response
        formula = self._extract_formula(response)
        
        # Estimate confidence (simple heuristic based on formula characteristics)
        confidence = self._estimate_confidence(formula, text)
        
        # Cache result
        if self.llm_cache:
            self.llm_cache.put(text, provider or "default", prompt_cid, formula, confidence)
        
        return formula, confidence, False
    
    def _extract_formula(self, llm_response: str) -> str:
        """
        Extract TDFOL formula from LLM response.
        
        Args:
            llm_response: Raw LLM response text
        
        Returns:
            Extracted formula string
        """
        # Try to find formula in response
        lines = llm_response.strip().split('\n')
        
        # Look for lines starting with Output:, Formula:, or containing TDFOL operators
        for line in lines:
            line = line.strip()
            if line.startswith(("Output:", "Formula:", "TDFOL:")):
                formula = line.split(":", 1)[1].strip()
                return formula
            
            # Check if line contains TDFOL operators
            if any(op in line for op in ["∀", "∃", "→", "∧", "∨", "¬", "O(", "P(", "F(", "G(", "K("]):
                return line
        
        # Fallback: return last non-empty line
        for line in reversed(lines):
            if line.strip():
                return line.strip()
        
        return llm_response.strip()
    
    def _estimate_confidence(self, formula: str, original_text: str) -> float:
        """
        Estimate confidence in LLM-generated formula.
        
        This is a simple heuristic based on formula characteristics.
        A more sophisticated approach could use validation or multiple LLM calls.
        
        Args:
            formula: Generated TDFOL formula
            original_text: Original input text
        
        Returns:
            Confidence score (0.0-1.0)
        """
        confidence = 0.5  # Base confidence
        
        # Check for valid TDFOL operators
        if any(op in formula for op in ["∀", "∃", "→", "∧", "∨"]):
            confidence += 0.2
        
        # Check for balanced parentheses
        if formula.count("(") == formula.count(")"):
            confidence += 0.1
        
        # Check for proper quantifier binding
        if "∀" in formula or "∃" in formula:
            if "(" in formula and ")" in formula:
                confidence += 0.1
        
        # Check length (not too short, not too long)
        if 10 < len(formula) < 200:
            confidence += 0.1
        
        return min(confidence, 0.95)  # Cap at 0.95 for LLM results
    
    def get_stats(self) -> Dict[str, Any]:
        """Get conversion statistics."""
        stats = self.stats.copy()
        
        if self.llm_cache:
            stats["cache"] = self.llm_cache.stats()
        
        return stats
    
    def clear_cache(self):
        """Clear LLM response cache."""
        if self.llm_cache:
            self.llm_cache.clear()
