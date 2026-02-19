"""
Ambiguity Resolution Module for DCEC Natural Language Processing.

This module provides disambiguation strategies for resolving ambiguous parses:
- Scoring functions for parse quality
- Preference rules based on linguistic principles
- Statistical and heuristic disambiguation
- Support for multiple parse ranking
"""

from typing import List, Dict, Optional, Callable, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
import logging

try:
    from beartype import beartype
except ImportError:
    from typing import TypeVar, Callable as CallableType
    F = TypeVar('F', bound=CallableType[..., Any])
    def beartype(func: F) -> F:
        return func

from .syntax_tree import SyntaxTree, SyntaxNode

logger = logging.getLogger(__name__)


class DisambiguationStrategy(Enum):
    """Strategies for disambiguation."""
    MINIMAL_ATTACHMENT = "minimal_attachment"  # Prefer simpler structures
    RIGHT_ASSOCIATION = "right_association"  # Prefer right-branching
    RECENCY_PREFERENCE = "recency_preference"  # Prefer recent attachments
    SEMANTIC_COHERENCE = "semantic_coherence"  # Prefer semantically coherent
    STATISTICAL = "statistical"  # Use frequency data


@dataclass
class ParseScore:
    """Score for a parse tree.
    
    Attributes:
        tree: The parse tree
        total_score: Overall score (higher is better)
        component_scores: Breakdown of scoring components
    """
    tree: SyntaxTree
    total_score: float
    component_scores: Dict[str, float] = field(default_factory=dict)
    
    def __lt__(self, other: 'ParseScore') -> bool:
        """Compare scores for sorting."""
        return self.total_score < other.total_score


class AmbiguityResolver:
    """Resolves ambiguous parses using multiple strategies."""
    
    def __init__(self):
        """Initialize the ambiguity resolver."""
        self.strategies: Dict[DisambiguationStrategy, float] = {
            DisambiguationStrategy.MINIMAL_ATTACHMENT: 1.0,
            DisambiguationStrategy.RIGHT_ASSOCIATION: 0.8,
            DisambiguationStrategy.SEMANTIC_COHERENCE: 1.2,
        }
        self.preference_rules: List[Callable[[SyntaxTree], float]] = []
        self._init_default_rules()
    
    def _init_default_rules(self):
        """Initialize default preference rules."""
        self.preference_rules.extend([
            self._minimal_attachment_score,
            self._right_association_score,
            self._tree_balance_score,
        ])
    
    @beartype
    def resolve(self, parses: List[SyntaxTree]) -> List[ParseScore]:
        """Resolve ambiguity by scoring and ranking parses.
        
        Args:
            parses: List of possible parse trees
            
        Returns:
            List of ParseScore objects, sorted by score (best first)
        """
        if not parses:
            return []
        
        if len(parses) == 1:
            return [ParseScore(parses[0], 1.0)]
        
        scores = []
        for tree in parses:
            score = self._score_parse(tree)
            scores.append(score)
        
        # Sort by score (highest first)
        scores.sort(reverse=True)
        return scores
    
    def _score_parse(self, tree: SyntaxTree) -> ParseScore:
        """Calculate overall score for a parse tree.
        
        Args:
            tree: Parse tree to score
            
        Returns:
            ParseScore object with total and component scores
        """
        component_scores = {}
        total = 0.0
        
        for rule in self.preference_rules:
            rule_name = rule.__name__
            rule_score = rule(tree)
            component_scores[rule_name] = rule_score
            total += rule_score
        
        return ParseScore(tree, total, component_scores)
    
    def _minimal_attachment_score(self, tree: SyntaxTree) -> float:
        """Score based on minimal attachment principle.
        
        Prefer trees with fewer nodes and simpler structure.
        """
        size = tree.size()
        height = tree.height()
        
        # Penalize larger/deeper trees
        size_score = 1.0 / (1.0 + size * 0.1)
        height_score = 1.0 / (1.0 + height * 0.2)
        
        return (size_score + height_score) / 2.0
    
    def _right_association_score(self, tree: SyntaxTree) -> float:
        """Score based on right association preference.
        
        Prefer right-branching structures.
        """
        def right_branching_ratio(node: SyntaxNode) -> float:
            if node.is_leaf() or not node.children:
                return 0.5
            
            # Check if rightmost child has more descendants
            if len(node.children) < 2:
                return 0.5
            
            right_child = node.children[-1]
            other_children = node.children[:-1]
            
            right_size = right_child.size()
            other_size = sum(child.size() for child in other_children)
            
            total = right_size + other_size
            if total == 0:
                return 0.5
            
            return right_size / total
        
        # Average right-branching across all non-leaf nodes
        non_leaf_nodes = [n for n in tree.preorder() if not n.is_leaf()]
        if not non_leaf_nodes:
            return 0.5
        
        ratios = [right_branching_ratio(node) for node in non_leaf_nodes]
        return sum(ratios) / len(ratios)
    
    def _tree_balance_score(self, tree: SyntaxTree) -> float:
        """Score based on tree balance.
        
        Prefer more balanced trees.
        """
        def balance_factor(node: SyntaxNode) -> float:
            if node.is_leaf():
                return 1.0
            
            if not node.children:
                return 1.0
            
            # Calculate heights of children
            child_heights = [child.height() for child in node.children]
            if not child_heights:
                return 1.0
            
            max_height = max(child_heights)
            min_height = min(child_heights)
            
            if max_height == 0:
                return 1.0
            
            # Balance is better when heights are similar
            return 1.0 - (max_height - min_height) / (max_height + 1)
        
        # Average balance across all nodes
        nodes = list(tree.preorder())
        if not nodes:
            return 0.5
        
        balances = [balance_factor(node) for node in nodes]
        return sum(balances) / len(balances)
    
    def add_preference_rule(self, rule: Callable[[SyntaxTree], float]):
        """Add a custom preference rule.
        
        Args:
            rule: Function that takes a tree and returns a score [0, 1]
        """
        self.preference_rules.append(rule)
    
    def set_strategy_weight(self, strategy: DisambiguationStrategy, weight: float):
        """Set weight for a disambiguation strategy.
        
        Args:
            strategy: Strategy to set weight for
            weight: Weight value (typically 0-2)
        """
        self.strategies[strategy] = weight
    
    @beartype
    def explain_ranking(self, scores: List[ParseScore]) -> str:
        """Generate explanation for parse ranking.
        
        Args:
            scores: Ranked parse scores
            
        Returns:
            Human-readable explanation
        """
        if not scores:
            return "No parses to rank."
        
        explanation = "Parse Ranking Explanation:\n\n"
        
        for i, score in enumerate(scores, 1):
            explanation += f"Rank {i}: Total Score = {score.total_score:.3f}\n"
            explanation += "  Component Scores:\n"
            for component, value in score.component_scores.items():
                explanation += f"    {component}: {value:.3f}\n"
            explanation += f"  Tree size: {score.tree.size()} nodes\n"
            explanation += f"  Tree height: {score.tree.height()}\n\n"
        
        return explanation


class SemanticDisambiguator:
    """Disambiguate based on semantic coherence."""
    
    def __init__(self):
        """Initialize semantic disambiguator."""
        self.semantic_scores: Dict[str, float] = {}
    
    def add_semantic_score(self, pattern: str, score: float):
        """Add semantic score for a pattern.
        
        Args:
            pattern: Semantic pattern
            score: Coherence score
        """
        self.semantic_scores[pattern] = score
    
    @beartype
    def score_semantics(self, tree: SyntaxTree) -> float:
        """Score semantic coherence of a parse tree.
        
        Args:
            tree: Parse tree to score
            
        Returns:
            Semantic coherence score [0, 1]
        """
        # Placeholder: would check for known semantic patterns
        # For now, return neutral score
        return 0.5


class StatisticalDisambiguator:
    """Disambiguate using statistical information."""
    
    def __init__(self):
        """Initialize statistical disambiguator."""
        self.ngram_counts: Dict[Tuple[str, ...], int] = {}
        self.total_count = 0
    
    def add_ngram(self, ngram: Tuple[str, ...], count: int = 1):
        """Add n-gram frequency data.
        
        Args:
            ngram: Tuple of symbols
            count: Frequency count
        """
        if ngram not in self.ngram_counts:
            self.ngram_counts[ngram] = 0
        self.ngram_counts[ngram] += count
        self.total_count += count
    
    @beartype
    def score_probability(self, tree: SyntaxTree) -> float:
        """Score based on n-gram probabilities.
        
        Args:
            tree: Parse tree to score
            
        Returns:
            Probability score [0, 1]
        """
        if self.total_count == 0:
            return 0.5
        
        # Extract bigrams from tree
        leaves = tree.leaves()
        if len(leaves) < 2:
            return 0.5
        
        total_prob = 1.0
        for i in range(len(leaves) - 1):
            bigram = (str(leaves[i].value), str(leaves[i+1].value))
            count = self.ngram_counts.get(bigram, 0)
            prob = (count + 1) / (self.total_count + len(self.ngram_counts))
            total_prob *= prob
        
        # Normalize to [0, 1]
        return min(1.0, total_prob * 10)
