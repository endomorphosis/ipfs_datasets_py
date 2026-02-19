"""
Unit tests for CEC Proof Optimization

Tests cover:
- Proof tree pruning (depth limit, early termination)
- Redundancy elimination (duplicates, subsumption)
- Parallel proof search
- Performance metrics

Author: CEC Development Team
Date: 2026-02-19
"""

import pytest
import time
from ipfs_datasets_py.logic.CEC.native.proof_optimization import (
    ProofNode,
    ProofTreePruner,
    RedundancyEliminator,
    ParallelProofSearch,
    ProofOptimizer,
    PruningStrategy,
    OptimizationMetrics
)


class TestProofNode:
    """Tests for ProofNode."""
    
    def test_proof_node_creation(self):
        """Test basic proof node creation."""
        # GIVEN: Node parameters
        formula = "P -> Q"
        depth = 1
        
        # WHEN: Creating a node
        node = ProofNode(formula=formula, depth=depth)
        
        # THEN: Node should be created correctly
        assert node.formula == formula
        assert node.depth == depth
        assert node.parent is None
        assert len(node.children) == 0
        assert not node.is_goal
        assert not node.is_redundant
    
    def test_proof_node_equality(self):
        """Test proof node equality based on formula."""
        # GIVEN: Two nodes with same formula
        node1 = ProofNode(formula="P -> Q", depth=1)
        node2 = ProofNode(formula="P -> Q", depth=2)
        node3 = ProofNode(formula="Q -> R", depth=1)
        
        # THEN: Equality should be based on formula
        assert node1 == node2
        assert node1 != node3
        assert hash(node1) == hash(node2)
        assert hash(node1) != hash(node3)


class TestProofTreePruner:
    """Tests for ProofTreePruner."""
    
    def test_depth_limit_pruning(self):
        """Test pruning based on depth limit."""
        # GIVEN: Pruner with max depth 2
        pruner = ProofTreePruner(max_depth=2)
        
        # WHEN: Checking nodes at different depths
        node1 = ProofNode(formula="P", depth=1)
        node2 = ProofNode(formula="Q", depth=2)
        node3 = ProofNode(formula="R", depth=3)
        
        visited = set()
        
        # THEN: Only deep node should be pruned
        should_prune1, reason1 = pruner.should_prune(node1, visited)
        should_prune2, reason2 = pruner.should_prune(node2, visited)
        should_prune3, reason3 = pruner.should_prune(node3, visited)
        
        assert not should_prune1
        assert not should_prune2
        assert should_prune3
        assert reason3 == "depth_limit"
    
    def test_redundancy_pruning(self):
        """Test pruning of redundant nodes."""
        # GIVEN: Pruner and visited set
        pruner = ProofTreePruner(max_depth=10)
        visited = {"P", "Q"}
        
        # WHEN: Checking duplicate node
        node = ProofNode(formula="P", depth=1)
        should_prune, reason = pruner.should_prune(node, visited)
        
        # THEN: Node should be pruned as redundant
        assert should_prune
        assert reason == "redundancy"
    
    def test_prune_tree(self):
        """Test full tree pruning."""
        # GIVEN: Tree with redundant branches
        root = ProofNode(formula="Root", depth=0)
        child1 = ProofNode(formula="Child1", depth=1)
        child2 = ProofNode(formula="Child1", depth=1)  # Duplicate
        child3 = ProofNode(formula="Child3", depth=1)
        
        root.children = [child1, child2, child3]
        
        pruner = ProofTreePruner(max_depth=10)
        
        # WHEN: Pruning the tree
        pruned_root, metrics = pruner.prune_tree(root)
        
        # THEN: Duplicate should be removed
        assert metrics.duplicates_eliminated >= 1
        assert metrics.nodes_explored >= 1
        assert metrics.pruning_ratio() > 0


class TestRedundancyEliminator:
    """Tests for RedundancyEliminator."""
    
    def test_duplicate_detection(self):
        """Test duplicate formula detection."""
        # GIVEN: Redundancy eliminator
        eliminator = RedundancyEliminator()
        
        # WHEN: Checking for duplicates
        is_dup1 = eliminator.is_duplicate("P -> Q")
        is_dup2 = eliminator.is_duplicate("P -> Q")
        is_dup3 = eliminator.is_duplicate("Q -> R")
        
        # THEN: Second occurrence should be marked duplicate
        assert not is_dup1
        assert is_dup2
        assert not is_dup3
        assert eliminator.metrics.duplicates_eliminated == 1
    
    def test_subsumption_check(self):
        """Test subsumption checking."""
        # GIVEN: Redundancy eliminator
        eliminator = RedundancyEliminator()
        
        # WHEN: Checking subsumption
        # Formula1 subsumes itself
        assert eliminator.subsumes("P", "P")
        
        # More specific formula is subsumed
        assert eliminator.subsumes("P", "P & Q")
        
        # Unrelated formulas don't subsume
        assert not eliminator.subsumes("P", "Q")
    
    def test_eliminate_redundancy(self):
        """Test redundancy elimination from formula list."""
        # GIVEN: List with duplicates and subsumptions
        formulas = ["P", "P", "Q", "P & Q", "R", "Q"]
        eliminator = RedundancyEliminator()
        
        # WHEN: Eliminating redundancy
        result = eliminator.eliminate_redundancy(formulas)
        
        # THEN: Duplicates and subsumed formulas should be removed
        assert len(result) < len(formulas)
        assert eliminator.metrics.duplicates_eliminated > 0
        assert "P" in result
        assert "Q" in result
        assert "R" in result


class TestParallelProofSearch:
    """Tests for ParallelProofSearch."""
    
    def test_parallel_search_success(self):
        """Test successful parallel search."""
        # GIVEN: Parallel searcher and search function
        searcher = ParallelProofSearch(max_workers=2)
        
        def search_fn(space):
            """Simulate search that succeeds on specific space."""
            time.sleep(0.01)
            return "result" if space == 2 else None
        
        # WHEN: Searching multiple spaces
        result = searcher.search_parallel(search_fn, [1, 2, 3])
        
        # THEN: Should find result
        assert result == "result"
        assert searcher.metrics.parallel_speedup >= 1.0
    
    def test_parallel_search_no_result(self):
        """Test parallel search with no result."""
        # GIVEN: Parallel searcher
        searcher = ParallelProofSearch(max_workers=2)
        
        def search_fn(space):
            """Simulate search that never succeeds."""
            time.sleep(0.01)
            return None
        
        # WHEN: Searching multiple spaces
        result = searcher.search_parallel(search_fn, [1, 2, 3])
        
        # THEN: Should return None
        assert result is None
    
    def test_parallel_speedup(self):
        """Test that parallel search provides speedup."""
        # GIVEN: Parallel searcher
        searcher = ParallelProofSearch(max_workers=4)
        
        def search_fn(space):
            """Simulate work."""
            time.sleep(0.01)
            return "result" if space == 3 else None
        
        # WHEN: Searching with parallelism
        start = time.time()
        result = searcher.search_parallel(search_fn, [1, 2, 3, 4])
        elapsed = time.time() - start
        
        # THEN: Should complete faster than sequential
        # (4 tasks * 0.01s = 0.04s sequential, should be < 0.03s parallel)
        assert result == "result"
        assert elapsed < 0.03  # Should be faster than sequential


class TestProofOptimizer:
    """Tests for ProofOptimizer."""
    
    def test_optimizer_creation(self):
        """Test proof optimizer creation."""
        # GIVEN: Optimizer parameters
        max_depth = 5
        
        # WHEN: Creating optimizer
        optimizer = ProofOptimizer(
            max_depth=max_depth,
            enable_pruning=True,
            enable_redundancy_elimination=True
        )
        
        # THEN: Should be configured correctly
        assert optimizer.max_depth == max_depth
        assert optimizer.enable_pruning
        assert optimizer.enable_redundancy_elimination
    
    def test_optimize_proof_tree_with_pruning(self):
        """Test tree optimization with pruning enabled."""
        # GIVEN: Tree and optimizer with pruning
        root = ProofNode(formula="Root", depth=0)
        child1 = ProofNode(formula="Child1", depth=1)
        child2 = ProofNode(formula="Child2", depth=1)
        deep_child = ProofNode(formula="DeepChild", depth=20)
        
        root.children = [child1, child2]
        child1.children = [deep_child]
        
        optimizer = ProofOptimizer(max_depth=5, enable_pruning=True)
        
        # WHEN: Optimizing the tree
        optimized, metrics = optimizer.optimize_proof_tree(root)
        
        # THEN: Deep nodes should be pruned
        assert metrics.nodes_pruned > 0
        assert metrics.total_time >= 0
    
    def test_optimize_with_redundancy_elimination(self):
        """Test optimization with redundancy elimination."""
        # GIVEN: Tree with redundant formulas
        root = ProofNode(formula="P", depth=0)
        child1 = ProofNode(formula="Q", depth=1)
        child2 = ProofNode(formula="Q", depth=1)  # Duplicate
        
        root.children = [child1, child2]
        
        optimizer = ProofOptimizer(
            enable_pruning=True,
            enable_redundancy_elimination=True
        )
        
        # WHEN: Optimizing
        optimized, metrics = optimizer.optimize_proof_tree(root)
        
        # THEN: Should eliminate redundancy
        assert metrics.duplicates_eliminated > 0 or metrics.nodes_pruned > 0
    
    def test_combined_metrics(self):
        """Test combined metrics collection."""
        # GIVEN: Optimizer
        optimizer = ProofOptimizer()
        
        # WHEN: Getting metrics
        metrics = optimizer.get_combined_metrics()
        
        # THEN: Should have all metric fields
        assert hasattr(metrics, 'nodes_explored')
        assert hasattr(metrics, 'nodes_pruned')
        assert hasattr(metrics, 'duplicates_eliminated')
        assert hasattr(metrics, 'subsumptions_found')


class TestOptimizationMetrics:
    """Tests for OptimizationMetrics."""
    
    def test_metrics_creation(self):
        """Test metrics object creation."""
        # WHEN: Creating metrics
        metrics = OptimizationMetrics(
            nodes_explored=10,
            nodes_pruned=5,
            duplicates_eliminated=2
        )
        
        # THEN: Values should be set correctly
        assert metrics.nodes_explored == 10
        assert metrics.nodes_pruned == 5
        assert metrics.duplicates_eliminated == 2
    
    def test_pruning_ratio(self):
        """Test pruning ratio calculation."""
        # GIVEN: Metrics with pruning
        metrics = OptimizationMetrics(
            nodes_explored=15,
            nodes_pruned=5
        )
        
        # WHEN: Calculating ratio
        ratio = metrics.pruning_ratio()
        
        # THEN: Should be correct (5/20 = 0.25)
        assert ratio == 0.25
    
    def test_metrics_to_dict(self):
        """Test metrics conversion to dictionary."""
        # GIVEN: Metrics
        metrics = OptimizationMetrics(
            nodes_explored=10,
            nodes_pruned=5,
            total_time=1.5
        )
        
        # WHEN: Converting to dict
        result = metrics.to_dict()
        
        # THEN: Should contain all fields
        assert 'nodes_explored' in result
        assert 'nodes_pruned' in result
        assert 'total_time' in result
        assert 'pruning_ratio' in result
        assert result['nodes_explored'] == 10
        assert result['nodes_pruned'] == 5
