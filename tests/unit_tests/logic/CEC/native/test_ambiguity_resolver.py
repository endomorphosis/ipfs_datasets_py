"""
Tests for Ambiguity Resolution Module.

Tests cover:
- Parse scoring
- Disambiguation strategies
- Preference rules
- Statistical disambiguation
"""

import pytest
from ipfs_datasets_py.logic.CEC.native.ambiguity_resolver import (
    DisambiguationStrategy,
    ParseScore,
    AmbiguityResolver,
    SemanticDisambiguator,
    StatisticalDisambiguator,
)
from ipfs_datasets_py.logic.CEC.native.syntax_tree import (
    NodeType,
    SyntaxNode,
    SyntaxTree,
)


class TestParseScore:
    """Test parse scoring."""
    
    def test_parse_score_creation(self):
        """Test creating parse scores."""
        # GIVEN a tree
        tree = SyntaxTree()
        
        # WHEN creating a parse score
        score = ParseScore(tree, 0.8)
        
        # THEN it should have correct attributes
        assert score.tree == tree
        assert score.total_score == 0.8
        assert isinstance(score.component_scores, dict)
    
    def test_parse_score_comparison(self):
        """Test comparing parse scores."""
        # GIVEN two scores
        tree = SyntaxTree()
        score1 = ParseScore(tree, 0.5)
        score2 = ParseScore(tree, 0.8)
        
        # WHEN comparing
        # THEN should order by total score
        assert score1 < score2
        assert not (score2 < score1)


class TestAmbiguityResolver:
    """Test ambiguity resolver."""
    
    @pytest.fixture
    def resolver(self):
        """Create resolver instance."""
        return AmbiguityResolver()
    
    @pytest.fixture
    def simple_tree(self):
        """Create a simple tree."""
        root = SyntaxNode(NodeType.ROOT)
        root.add_child(SyntaxNode(NodeType.WORD, "test"))
        return SyntaxTree(root)
    
    @pytest.fixture
    def complex_tree(self):
        """Create a more complex tree."""
        root = SyntaxNode(NodeType.ROOT)
        phrase = SyntaxNode(NodeType.PHRASE)
        phrase.add_child(SyntaxNode(NodeType.WORD, "a"))
        phrase.add_child(SyntaxNode(NodeType.WORD, "b"))
        root.add_child(phrase)
        root.add_child(SyntaxNode(NodeType.WORD, "c"))
        return SyntaxTree(root)
    
    def test_resolver_initialization(self, resolver):
        """Test resolver initializes correctly."""
        # GIVEN a resolver
        # THEN it should have strategies and rules
        assert len(resolver.strategies) > 0
        assert len(resolver.preference_rules) > 0
    
    def test_resolve_single_parse(self, resolver, simple_tree):
        """Test resolving with single parse."""
        # GIVEN one parse
        parses = [simple_tree]
        
        # WHEN resolving
        scores = resolver.resolve(parses)
        
        # THEN should return one score
        assert len(scores) == 1
        assert scores[0].tree == simple_tree
    
    def test_resolve_multiple_parses(self, resolver, simple_tree, complex_tree):
        """Test resolving multiple parses."""
        # GIVEN multiple parses
        parses = [simple_tree, complex_tree]
        
        # WHEN resolving
        scores = resolver.resolve(parses)
        
        # THEN should return ranked scores
        assert len(scores) == 2
        assert scores[0].total_score >= scores[1].total_score
    
    def test_minimal_attachment_preference(self, resolver):
        """Test minimal attachment scoring."""
        # GIVEN a simple and complex tree
        simple = SyntaxTree()
        simple.root.add_child(SyntaxNode(NodeType.WORD, "a"))
        
        complex_root = SyntaxNode(NodeType.ROOT)
        for i in range(5):
            complex_root.add_child(SyntaxNode(NodeType.WORD, str(i)))
        complex = SyntaxTree(complex_root)
        
        # WHEN scoring
        simple_score = resolver._minimal_attachment_score(simple)
        complex_score = resolver._minimal_attachment_score(complex)
        
        # THEN simpler should score higher
        assert simple_score > complex_score
    
    def test_add_preference_rule(self, resolver):
        """Test adding custom preference rules."""
        # GIVEN a custom rule
        def custom_rule(tree):
            return 0.9
        
        initial_count = len(resolver.preference_rules)
        
        # WHEN adding the rule
        resolver.add_preference_rule(custom_rule)
        
        # THEN should be added
        assert len(resolver.preference_rules) == initial_count + 1
    
    def test_set_strategy_weight(self, resolver):
        """Test setting strategy weights."""
        # GIVEN a strategy
        strategy = DisambiguationStrategy.MINIMAL_ATTACHMENT
        weight = 1.5
        
        # WHEN setting weight
        resolver.set_strategy_weight(strategy, weight)
        
        # THEN should be updated
        assert resolver.strategies[strategy] == weight
    
    def test_explain_ranking(self, resolver, simple_tree):
        """Test generating ranking explanation."""
        # GIVEN scored parses
        scores = resolver.resolve([simple_tree])
        
        # WHEN explaining
        explanation = resolver.explain_ranking(scores)
        
        # THEN should produce readable text
        assert isinstance(explanation, str)
        assert "Rank" in explanation
        assert "Score" in explanation


class TestSemanticDisambiguator:
    """Test semantic disambiguator."""
    
    def test_semantic_disambiguator_creation(self):
        """Test creating semantic disambiguator."""
        # WHEN creating disambiguator
        disambiguator = SemanticDisambiguator()
        
        # THEN should initialize correctly
        assert isinstance(disambiguator.semantic_scores, dict)
    
    def test_add_semantic_score(self):
        """Test adding semantic scores."""
        # GIVEN a disambiguator
        disambiguator = SemanticDisambiguator()
        
        # WHEN adding a score
        disambiguator.add_semantic_score("pattern1", 0.8)
        
        # THEN should be stored
        assert "pattern1" in disambiguator.semantic_scores
        assert disambiguator.semantic_scores["pattern1"] == 0.8


class TestStatisticalDisambiguator:
    """Test statistical disambiguator."""
    
    def test_statistical_disambiguator_creation(self):
        """Test creating statistical disambiguator."""
        # WHEN creating disambiguator
        disambiguator = StatisticalDisambiguator()
        
        # THEN should initialize correctly
        assert isinstance(disambiguator.ngram_counts, dict)
        assert disambiguator.total_count == 0
    
    def test_add_ngram(self):
        """Test adding n-gram data."""
        # GIVEN a disambiguator
        disambiguator = StatisticalDisambiguator()
        
        # WHEN adding n-grams
        disambiguator.add_ngram(("the", "cat"), 5)
        disambiguator.add_ngram(("cat", "sat"), 3)
        
        # THEN should track counts
        assert disambiguator.ngram_counts[("the", "cat")] == 5
        assert disambiguator.total_count == 8


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
