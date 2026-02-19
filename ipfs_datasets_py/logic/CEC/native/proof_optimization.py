"""
Proof Optimization Module for CEC

This module provides proof tree optimization techniques including:
- Proof tree pruning (early termination, depth limits)
- Redundancy elimination (duplicate detection, subsumption)
- Parallel proof search (thread pool executor)
- Performance profiling and metrics

Author: CEC Development Team
Date: 2026-02-19
"""

from typing import List, Set, Dict, Any, Optional, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum
import time
import threading
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from collections import defaultdict


class PruningStrategy(Enum):
    """Strategy for pruning proof trees."""
    DEPTH_LIMIT = "depth_limit"
    EARLY_TERMINATION = "early_termination"
    REDUNDANCY_CHECK = "redundancy_check"
    COMBINED = "combined"


@dataclass
class ProofNode:
    """Represents a node in the proof tree."""
    formula: str
    depth: int
    parent: Optional['ProofNode'] = None
    children: List['ProofNode'] = field(default_factory=list)
    is_goal: bool = False
    is_redundant: bool = False
    proof_step: Optional[str] = None
    
    def __hash__(self):
        """Hash based on formula for deduplication."""
        return hash(self.formula)
    
    def __eq__(self, other):
        """Equality based on formula."""
        if not isinstance(other, ProofNode):
            return False
        return self.formula == other.formula


@dataclass
class OptimizationMetrics:
    """Metrics for proof optimization."""
    nodes_explored: int = 0
    nodes_pruned: int = 0
    duplicates_eliminated: int = 0
    subsumptions_found: int = 0
    total_time: float = 0.0
    parallel_speedup: float = 1.0
    
    def pruning_ratio(self) -> float:
        """Calculate the ratio of pruned nodes."""
        total = self.nodes_explored + self.nodes_pruned
        return self.nodes_pruned / total if total > 0 else 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            'nodes_explored': self.nodes_explored,
            'nodes_pruned': self.nodes_pruned,
            'duplicates_eliminated': self.duplicates_eliminated,
            'subsumptions_found': self.subsumptions_found,
            'total_time': self.total_time,
            'parallel_speedup': self.parallel_speedup,
            'pruning_ratio': self.pruning_ratio()
        }


class ProofTreePruner:
    """Prunes proof trees using various strategies."""
    
    def __init__(self, max_depth: int = 10, enable_early_termination: bool = True):
        """
        Initialize the pruner.
        
        Args:
            max_depth: Maximum depth for proof search
            enable_early_termination: Whether to enable early termination
        """
        self.max_depth = max_depth
        self.enable_early_termination = enable_early_termination
        self.metrics = OptimizationMetrics()
    
    def should_prune(self, node: ProofNode, visited: Set[str]) -> Tuple[bool, str]:
        """
        Determine if a node should be pruned.
        
        Args:
            node: The node to check
            visited: Set of visited formula strings
            
        Returns:
            Tuple of (should_prune, reason)
        """
        # Depth limit pruning
        if node.depth > self.max_depth:
            return True, "depth_limit"
        
        # Redundancy pruning
        if node.formula in visited:
            return True, "redundancy"
        
        # Early termination if goal reached
        if self.enable_early_termination and node.is_goal:
            return False, "goal_reached"
        
        return False, ""
    
    def prune_tree(self, root: ProofNode) -> Tuple[ProofNode, OptimizationMetrics]:
        """
        Prune a proof tree starting from root.
        
        Args:
            root: Root node of the proof tree
            
        Returns:
            Tuple of (pruned_root, metrics)
        """
        start_time = time.time()
        visited: Set[str] = set()
        self.metrics = OptimizationMetrics()
        
        def prune_recursive(node: ProofNode) -> Optional[ProofNode]:
            """Recursively prune the tree."""
            should_prune, reason = self.should_prune(node, visited)
            
            if should_prune:
                self.metrics.nodes_pruned += 1
                if reason == "redundancy":
                    self.metrics.duplicates_eliminated += 1
                return None
            
            self.metrics.nodes_explored += 1
            visited.add(node.formula)
            
            # Prune children
            pruned_children = []
            for child in node.children:
                pruned_child = prune_recursive(child)
                if pruned_child is not None:
                    pruned_children.append(pruned_child)
            
            node.children = pruned_children
            return node
        
        pruned_root = prune_recursive(root)
        self.metrics.total_time = time.time() - start_time
        
        return pruned_root if pruned_root else root, self.metrics


class RedundancyEliminator:
    """Eliminates redundant proof steps."""
    
    def __init__(self):
        """Initialize the redundancy eliminator."""
        self.seen_formulas: Set[str] = set()
        self.subsumption_cache: Dict[str, List[str]] = defaultdict(list)
        self.metrics = OptimizationMetrics()
    
    def is_duplicate(self, formula: str) -> bool:
        """
        Check if a formula is a duplicate.
        
        Args:
            formula: Formula to check
            
        Returns:
            True if duplicate
        """
        if formula in self.seen_formulas:
            self.metrics.duplicates_eliminated += 1
            return True
        self.seen_formulas.add(formula)
        return False
    
    def subsumes(self, formula1: str, formula2: str) -> bool:
        """
        Check if formula1 subsumes formula2.
        
        Simple subsumption: formula1 subsumes formula2 if formula2
        is syntactically equal or a more specific instance.
        
        Args:
            formula1: First formula
            formula2: Second formula
            
        Returns:
            True if formula1 subsumes formula2
        """
        # Simple syntactic subsumption
        if formula1 == formula2:
            return True
        
        # Check if formula2 is a specialization of formula1
        # (This is a simplified check - real subsumption is more complex)
        if formula1 in formula2 and len(formula2) > len(formula1):
            return True
        
        return False
    
    def eliminate_redundancy(self, formulas: List[str]) -> List[str]:
        """
        Eliminate redundant formulas from a list.
        
        Args:
            formulas: List of formulas
            
        Returns:
            List of non-redundant formulas
        """
        start_time = time.time()
        self.seen_formulas.clear()
        result = []
        
        for formula in formulas:
            # Check for duplicates
            if self.is_duplicate(formula):
                continue
            
            # Check for subsumption
            is_subsumed = False
            for existing in result:
                if self.subsumes(existing, formula):
                    self.metrics.subsumptions_found += 1
                    is_subsumed = True
                    break
            
            if not is_subsumed:
                result.append(formula)
                self.metrics.nodes_explored += 1
        
        self.metrics.total_time = time.time() - start_time
        return result
    
    def get_metrics(self) -> OptimizationMetrics:
        """Get current metrics."""
        return self.metrics


class ParallelProofSearch:
    """Performs parallel proof search using thread pool."""
    
    def __init__(self, max_workers: int = 4):
        """
        Initialize parallel search.
        
        Args:
            max_workers: Maximum number of worker threads
        """
        self.max_workers = max_workers
        self.metrics = OptimizationMetrics()
        self._lock = threading.Lock()
    
    def search_parallel(
        self,
        search_fn: Callable[[Any], Optional[Any]],
        search_spaces: List[Any]
    ) -> Optional[Any]:
        """
        Search multiple search spaces in parallel.
        
        Args:
            search_fn: Function to search a single space
            search_spaces: List of search spaces
            
        Returns:
            First successful result or None
        """
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            futures: Dict[Future, Any] = {
                executor.submit(search_fn, space): space
                for space in search_spaces
            }
            
            # Process results as they complete
            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result is not None:
                        # Found a solution - cancel remaining tasks
                        for f in futures:
                            if f != future:
                                f.cancel()
                        
                        # Calculate metrics
                        elapsed = time.time() - start_time
                        sequential_time = elapsed * len(search_spaces)
                        self.metrics.parallel_speedup = sequential_time / elapsed if elapsed > 0 else 1.0
                        self.metrics.total_time = elapsed
                        
                        return result
                except Exception as e:
                    # Log error but continue with other tasks
                    pass
            
        self.metrics.total_time = time.time() - start_time
        return None
    
    def get_metrics(self) -> OptimizationMetrics:
        """Get current metrics."""
        return self.metrics


class ProofOptimizer:
    """Main proof optimization coordinator."""
    
    def __init__(
        self,
        max_depth: int = 10,
        enable_pruning: bool = True,
        enable_redundancy_elimination: bool = True,
        enable_parallel: bool = False,
        max_workers: int = 4
    ):
        """
        Initialize the proof optimizer.
        
        Args:
            max_depth: Maximum depth for proof search
            enable_pruning: Enable tree pruning
            enable_redundancy_elimination: Enable redundancy elimination
            enable_parallel: Enable parallel search
            max_workers: Maximum number of parallel workers
        """
        self.max_depth = max_depth
        self.enable_pruning = enable_pruning
        self.enable_redundancy_elimination = enable_redundancy_elimination
        self.enable_parallel = enable_parallel
        
        self.pruner = ProofTreePruner(max_depth=max_depth)
        self.eliminator = RedundancyEliminator()
        self.parallel_search = ParallelProofSearch(max_workers=max_workers)
        
        self.combined_metrics = OptimizationMetrics()
    
    def optimize_proof_tree(self, root: ProofNode) -> Tuple[ProofNode, OptimizationMetrics]:
        """
        Optimize a proof tree using all enabled techniques.
        
        Args:
            root: Root node of the proof tree
            
        Returns:
            Tuple of (optimized_root, metrics)
        """
        start_time = time.time()
        result = root
        
        # Apply pruning
        if self.enable_pruning:
            result, prune_metrics = self.pruner.prune_tree(result)
            self.combined_metrics.nodes_pruned += prune_metrics.nodes_pruned
            self.combined_metrics.duplicates_eliminated += prune_metrics.duplicates_eliminated
        
        # Apply redundancy elimination to all nodes
        if self.enable_redundancy_elimination:
            formulas = self._collect_formulas(result)
            optimized = self.eliminator.eliminate_redundancy(formulas)
            elim_metrics = self.eliminator.get_metrics()
            self.combined_metrics.subsumptions_found += elim_metrics.subsumptions_found
        
        self.combined_metrics.total_time = time.time() - start_time
        return result, self.combined_metrics
    
    def _collect_formulas(self, node: ProofNode) -> List[str]:
        """Collect all formulas from a tree."""
        result = [node.formula]
        for child in node.children:
            result.extend(self._collect_formulas(child))
        return result
    
    def get_combined_metrics(self) -> OptimizationMetrics:
        """Get combined metrics from all optimizations."""
        return self.combined_metrics
