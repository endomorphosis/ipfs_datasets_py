"""
Lemma Generation for DCEC (Phase 4 Weeks 2-3, Task 2.3)

This module provides automatic lemma discovery, caching, and proof reuse
for DCEC theorem proving. Lemmas are intermediate results that can be
reused across multiple proofs to improve efficiency.

Features:
- Automatic lemma discovery from successful proof steps
- LRU cache for frequently used lemmas
- Pattern matching for lemma application
- Proof reuse via lemma library
- Statistics tracking for lemma effectiveness

Examples:
    >>> from ipfs_datasets_py.logic.CEC.native.lemma_generation import LemmaGenerator
    >>> generator = LemmaGenerator(max_lemmas=100)
    >>> 
    >>> # Discover lemmas from a proof
    >>> lemmas = generator.discover_lemmas(proof_tree)
    >>> 
    >>> # Use lemmas in subsequent proofs
    >>> result = generator.prove_with_lemmas(goal, axioms, rules)
"""

from typing import List, Set, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
from collections import OrderedDict
from enum import Enum
import logging
import time
import hashlib

from .prover_core import (
    InferenceRule,
    ProofResult,
    ProofState,
    ProofTree,
    ProofStep,
)
from .dcec_core import Formula

try:
    from beartype import beartype
except ImportError:
    from typing import TypeVar, Callable, Any as AnyType
    F = TypeVar('F', bound=Callable[..., AnyType])
    def beartype(func: F) -> F:
        return func

logger = logging.getLogger(__name__)


class LemmaType(Enum):
    """Types of lemmas."""
    DERIVED = "derived"  # Derived during proof
    REUSABLE = "reusable"  # Applicable to multiple contexts
    PATTERN = "pattern"  # Matches a common pattern


@dataclass
class Lemma:
    """
    A lemma is an intermediate result that can be reused.
    
    Attributes:
        formula: The formula that was proved
        premises: Formulas used to derive this lemma
        rule: Inference rule that produced this lemma
        lemma_type: Type of lemma
        usage_count: Number of times this lemma has been used
        pattern_hash: Hash for pattern matching
    """
    formula: Formula
    premises: List[Formula]
    rule: str
    lemma_type: LemmaType = LemmaType.DERIVED
    usage_count: int = 0
    pattern_hash: Optional[str] = None
    
    def __post_init__(self):
        """Compute pattern hash for matching."""
        if self.pattern_hash is None:
            # Create a hash based on formula structure
            formula_str = self.formula.to_string()
            self.pattern_hash = hashlib.sha256(formula_str.encode()).hexdigest()[:16]
    
    def matches_pattern(self, other_formula: Formula) -> bool:
        """Check if this lemma's pattern matches another formula."""
        # Simple string matching for now
        # Could be extended to structural matching
        return self.formula.to_string() == other_formula.to_string()
    
    def increment_usage(self):
        """Increment usage counter."""
        self.usage_count += 1


class LemmaCache:
    """
    LRU cache for lemmas with pattern-based lookup.
    
    Features:
    - Fixed capacity with LRU eviction
    - Pattern-based retrieval
    - Usage statistics
    """
    
    def __init__(self, max_size: int = 100):
        """
        Initialize lemma cache.
        
        Args:
            max_size: Maximum number of lemmas to cache
        """
        self.max_size = max_size
        self._cache: OrderedDict[str, Lemma] = OrderedDict()
        self._pattern_index: Dict[str, Set[str]] = {}
        self.hits = 0
        self.misses = 0
    
    def add(self, lemma: Lemma):
        """
        Add a lemma to the cache.
        
        Args:
            lemma: Lemma to add
        """
        key = lemma.pattern_hash or lemma.formula.to_string()
        
        # If already exists, move to end (most recently used)
        if key in self._cache:
            self._cache.move_to_end(key)
            return
        
        # Add new lemma
        self._cache[key] = lemma
        
        # Add to pattern index
        pattern = self._extract_pattern(lemma.formula)
        if pattern not in self._pattern_index:
            self._pattern_index[pattern] = set()
        self._pattern_index[pattern].add(key)
        
        # Evict LRU if over capacity
        if len(self._cache) > self.max_size:
            evicted_key, evicted_lemma = self._cache.popitem(last=False)
            # Remove from pattern index
            evicted_pattern = self._extract_pattern(evicted_lemma.formula)
            if evicted_pattern in self._pattern_index:
                self._pattern_index[evicted_pattern].discard(evicted_key)
                if not self._pattern_index[evicted_pattern]:
                    del self._pattern_index[evicted_pattern]
            logger.debug(f"Evicted lemma (LRU): {evicted_lemma.formula.to_string()}")
    
    def get(self, formula: Formula) -> Optional[Lemma]:
        """
        Retrieve a lemma for a formula.
        
        Args:
            formula: Formula to look up
            
        Returns:
            Matching lemma if found, None otherwise
        """
        key = hashlib.sha256(formula.to_string().encode()).hexdigest()[:16]
        
        if key in self._cache:
            self.hits += 1
            lemma = self._cache[key]
            lemma.increment_usage()
            self._cache.move_to_end(key)  # Mark as recently used
            return lemma
        
        self.misses += 1
        return None
    
    def find_by_pattern(self, formula: Formula) -> List[Lemma]:
        """
        Find lemmas matching a formula's pattern.
        
        Args:
            formula: Formula pattern to match
            
        Returns:
            List of matching lemmas
        """
        pattern = self._extract_pattern(formula)
        if pattern not in self._pattern_index:
            return []
        
        matching_lemmas = []
        for key in self._pattern_index[pattern]:
            if key in self._cache:
                lemma = self._cache[key]
                if lemma.matches_pattern(formula):
                    matching_lemmas.append(lemma)
        
        return matching_lemmas
    
    def _extract_pattern(self, formula: Formula) -> str:
        """Extract a pattern signature from a formula."""
        # Simplified pattern extraction
        # In practice, this could extract structural patterns
        return formula.to_string()[:50]  # First 50 chars as pattern
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total_requests = self.hits + self.misses
        hit_rate = self.hits / total_requests if total_requests > 0 else 0.0
        
        return {
            'size': len(self._cache),
            'max_size': self.max_size,
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate': hit_rate,
            'total_requests': total_requests,
        }
    
    def clear(self):
        """Clear the cache."""
        self._cache.clear()
        self._pattern_index.clear()
        self.hits = 0
        self.misses = 0


class LemmaGenerator:
    """
    Automatic lemma discovery and proof reuse system.
    
    This class discovers useful lemmas from successful proofs,
    caches them, and reuses them in subsequent proofs.
    
    Examples:
        >>> generator = LemmaGenerator(max_lemmas=100)
        >>> lemmas = generator.discover_lemmas(proof_tree)
        >>> result = generator.prove_with_lemmas(goal, axioms, rules)
    """
    
    def __init__(self, max_lemmas: int = 100):
        """
        Initialize lemma generator.
        
        Args:
            max_lemmas: Maximum number of lemmas to cache
        """
        self.cache = LemmaCache(max_size=max_lemmas)
        self.discovery_count = 0
        self.reuse_count = 0
    
    def discover_lemmas(
        self,
        proof_tree: ProofTree,
        min_complexity: int = 2
    ) -> List[Lemma]:
        """
        Discover lemmas from a successful proof.
        
        Extracts intermediate steps that could be useful
        for future proofs.
        
        Args:
            proof_tree: Completed proof tree
            min_complexity: Minimum number of premises for lemma candidacy
            
        Returns:
            List of discovered lemmas
        """
        if proof_tree.result != ProofResult.PROVED:
            logger.debug("No lemmas from unsuccessful proof")
            return []
        
        lemmas = []
        
        # Extract lemmas from proof steps
        for step in proof_tree.steps:
            # Only consider steps with multiple premises (non-trivial)
            # Note: step.premises is a list of indices, not formulas
            if len(step.premises) >= min_complexity:
                # Get the actual formula premises from axioms/previous steps
                premise_formulas = []
                for premise_idx in step.premises:
                    if premise_idx < len(proof_tree.axioms):
                        premise_formulas.append(proof_tree.axioms[premise_idx])
                    else:
                        # It's from a previous step
                        step_idx = premise_idx - len(proof_tree.axioms)
                        if 0 <= step_idx < len(proof_tree.steps):
                            premise_formulas.append(proof_tree.steps[step_idx].formula)
                
                lemma = Lemma(
                    formula=step.formula,
                    premises=premise_formulas,
                    rule=step.rule,
                    lemma_type=LemmaType.DERIVED
                )
                lemmas.append(lemma)
                self.cache.add(lemma)
                self.discovery_count += 1
                logger.debug(f"Discovered lemma: {lemma.formula.to_string()}")
        
        # Identify reusable lemmas (appear in multiple contexts)
        self._identify_reusable_lemmas(lemmas)
        
        return lemmas
    
    def _identify_reusable_lemmas(self, lemmas: List[Lemma]):
        """
        Identify lemmas that are likely reusable.
        
        Updates lemma types based on patterns.
        """
        # Group lemmas by pattern
        pattern_groups: Dict[str, List[Lemma]] = {}
        for lemma in lemmas:
            pattern = self._get_lemma_pattern(lemma)
            if pattern not in pattern_groups:
                pattern_groups[pattern] = []
            pattern_groups[pattern].append(lemma)
        
        # Mark lemmas with common patterns as reusable
        for pattern, group in pattern_groups.items():
            if len(group) > 1:  # Appears multiple times
                for lemma in group:
                    lemma.lemma_type = LemmaType.REUSABLE
                    logger.debug(f"Marked as reusable: {lemma.formula.to_string()}")
    
    def _get_lemma_pattern(self, lemma: Lemma) -> str:
        """Extract a pattern from a lemma."""
        # Simplified: use first 30 chars
        return lemma.formula.to_string()[:30]
    
    def get_applicable_lemmas(
        self,
        goal: Formula,
        derived: List[Formula]
    ) -> List[Lemma]:
        """
        Find lemmas applicable to current proof state.
        
        Args:
            goal: Current proof goal
            derived: Currently derived formulas
            
        Returns:
            List of applicable lemmas
        """
        applicable = []
        
        # Check exact matches first
        for formula in derived:
            lemma = self.cache.get(formula)
            if lemma:
                applicable.append(lemma)
        
        # Check pattern matches
        for formula in derived:
            pattern_matches = self.cache.find_by_pattern(formula)
            applicable.extend(pattern_matches)
        
        # Remove duplicates
        seen = set()
        unique_applicable = []
        for lemma in applicable:
            key = lemma.pattern_hash
            if key not in seen:
                seen.add(key)
                unique_applicable.append(lemma)
        
        return unique_applicable
    
    def prove_with_lemmas(
        self,
        goal: Formula,
        axioms: List[Formula],
        rules: List[InferenceRule],
        max_steps: int = 100,
        timeout: Optional[float] = None
    ) -> ProofTree:
        """
        Attempt to prove a goal using lemmas.
        
        This extends standard proof search by trying to apply
        cached lemmas at each step.
        
        Args:
            goal: Formula to prove
            axioms: List of axioms
            rules: Inference rules to use
            max_steps: Maximum proof steps
            timeout: Optional timeout in seconds
            
        Returns:
            ProofTree with result
        """
        logger.info(f"Proving with lemmas: {goal.to_string()}")
        
        start_time = time.time()
        state = ProofState(goal, axioms)
        
        # Check if goal is already in axioms
        if state.has_goal():
            logger.info("Goal is an axiom!")
            return state.get_proof_tree(ProofResult.PROVED)
        
        # Proof search with lemma application
        for step_num in range(max_steps):
            # Check timeout
            if timeout and (time.time() - start_time) > timeout:
                logger.info(f"Timeout after {step_num} steps")
                return state.get_proof_tree(ProofResult.TIMEOUT)
            
            # Try to apply lemmas first (faster)
            applicable_lemmas = self.get_applicable_lemmas(goal, state.derived)
            for lemma in applicable_lemmas:
                # Check if lemma's conclusions help
                if lemma.formula.to_string() not in [f.to_string() for f in state.derived]:
                    state.add_formula(lemma.formula, f"Lemma: {lemma.rule}", lemma.premises)
                    lemma.increment_usage()
                    self.reuse_count += 1
                    logger.debug(f"Applied lemma: {lemma.formula.to_string()}")
                    
                    # Check if goal reached
                    if state.has_goal():
                        logger.info(f"Proof found (via lemma) in {step_num+1} steps!")
                        return state.get_proof_tree(ProofResult.PROVED)
            
            # Apply regular inference rules
            new_formulas = []
            for rule in rules:
                if rule.can_apply(state.derived):
                    try:
                        results = rule.apply(state.derived)
                        for result in results:
                            result_str = result.to_string()
                            if not any(f.to_string() == result_str for f in state.derived):
                                new_formulas.append((result, rule.name()))
                    except Exception as e:
                        logger.warning(f"Error applying {rule.name()}: {e}")
            
            if not new_formulas:
                logger.info(f"No new formulas after {step_num+1} steps")
                break
            
            for formula, rule_name in new_formulas:
                state.add_formula(formula, rule_name, [])
                
                if state.has_goal():
                    logger.info(f"Proof found in {step_num+1} steps!")
                    # Discover lemmas from this proof
                    proof_tree = state.get_proof_tree(ProofResult.PROVED)
                    self.discover_lemmas(proof_tree)
                    return proof_tree
        
        logger.info(f"Could not prove goal in {max_steps} steps")
        return state.get_proof_tree(ProofResult.UNKNOWN)
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get lemma generation statistics.
        
        Returns:
            Dictionary with statistics
        """
        cache_stats = self.cache.get_statistics()
        
        return {
            'discovery_count': self.discovery_count,
            'reuse_count': self.reuse_count,
            'cache_size': cache_stats['size'],
            'cache_hit_rate': cache_stats['hit_rate'],
            'cache_hits': cache_stats['hits'],
            'cache_misses': cache_stats['misses'],
        }
    
    def clear(self):
        """Clear all lemmas and statistics."""
        self.cache.clear()
        self.discovery_count = 0
        self.reuse_count = 0


# Convenience functions

def create_lemma_generator(max_lemmas: int = 100) -> LemmaGenerator:
    """
    Create a lemma generator with default settings.
    
    Args:
        max_lemmas: Maximum number of lemmas to cache
        
    Returns:
        Configured LemmaGenerator instance
    
    Examples:
        >>> generator = create_lemma_generator(max_lemmas=50)
        >>> result = generator.prove_with_lemmas(goal, axioms, rules)
    """
    return LemmaGenerator(max_lemmas=max_lemmas)
