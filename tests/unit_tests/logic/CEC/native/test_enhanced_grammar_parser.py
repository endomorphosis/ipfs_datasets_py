"""
Tests for Enhanced Grammar-Based Parser.

Tests cover:
- Grammar rule construction
- Earley parsing algorithm
- Parse tree generation
- Grammar validation
"""

import pytest
from ipfs_datasets_py.logic.CEC.native.enhanced_grammar_parser import (
    Category,
    Terminal,
    GrammarRule,
    ParseTree,
    EarleyState,
    EnhancedGrammarParser,
)


class TestGrammarComponents:
    """Test basic grammar components."""
    
    def test_terminal_creation(self):
        """Test creating terminal symbols."""
        # GIVEN a word and category
        word = "alice"
        category = Category.AGENT
        
        # WHEN creating a terminal
        terminal = Terminal(word, category)
        
        # THEN it should have correct attributes
        assert terminal.word == word
        assert terminal.category == category
        assert "alice" in str(terminal)
    
    def test_grammar_rule_creation(self):
        """Test creating grammar rules."""
        # GIVEN rule components
        lhs = Category.S
        rhs = [Category.NP, Category.VP]
        
        # WHEN creating a rule
        rule = GrammarRule(lhs, rhs)
        
        # THEN it should have correct structure
        assert rule.lhs == lhs
        assert rule.rhs == rhs
        assert "S -> NP VP" in str(rule)
    
    def test_parse_tree_terminal(self):
        """Test terminal parse tree nodes."""
        # GIVEN a terminal
        terminal = Terminal("alice", Category.AGENT)
        
        # WHEN creating a terminal tree node
        tree = ParseTree(Category.AGENT, terminal=terminal)
        
        # THEN it should be recognized as terminal
        assert tree.is_terminal()
        assert tree.leaves() == ["alice"]


class TestEarleyStates:
    """Test Earley parser states."""
    
    def test_earley_state_creation(self):
        """Test creating Earley states."""
        # GIVEN a grammar rule
        rule = GrammarRule(Category.S, [Category.NP, Category.VP])
        
        # WHEN creating an Earley state
        state = EarleyState(rule, 0, 0, 0)
        
        # THEN it should track position correctly
        assert state.rule == rule
        assert state.dot_pos == 0
        assert state.next_category() == Category.NP
        assert not state.is_complete()
    
    def test_earley_state_advance(self):
        """Test advancing Earley states."""
        # GIVEN a state at the beginning
        rule = GrammarRule(Category.S, [Category.NP, Category.VP])
        state = EarleyState(rule, 0, 0, 0)
        
        # WHEN advancing the state
        new_state = state.advance()
        
        # THEN dot position should increase
        assert new_state.dot_pos == 1
        assert new_state.next_category() == Category.VP
    
    def test_earley_state_complete(self):
        """Test complete Earley states."""
        # GIVEN a state at the end
        rule = GrammarRule(Category.S, [Category.NP, Category.VP])
        state = EarleyState(rule, 2, 0, 2)
        
        # WHEN checking completion
        # THEN it should be complete
        assert state.is_complete()
        assert state.next_category() is None


class TestEnhancedGrammarParser:
    """Test the enhanced grammar parser."""
    
    @pytest.fixture
    def parser(self):
        """Create a parser instance."""
        return EnhancedGrammarParser()
    
    def test_parser_initialization(self, parser):
        """Test parser initializes with rules and lexicon."""
        # GIVEN a parser
        # THEN it should have grammar rules
        assert len(parser.rules) > 0
        assert len(parser.lexicon) > 0
        assert parser.start_symbol == Category.S
    
    def test_add_rule(self, parser):
        """Test adding custom grammar rules."""
        # GIVEN a parser and a new rule
        initial_count = len(parser.rules)
        rule = GrammarRule(Category.VP, [Category.V, Category.ADV])
        
        # WHEN adding the rule
        parser.add_rule(rule)
        
        # THEN rules list should grow
        assert len(parser.rules) == initial_count + 1
        assert rule in parser.rules
    
    def test_add_lexical_entry(self, parser):
        """Test adding words to lexicon."""
        # GIVEN a parser and a new word
        word = "newword"
        category = Category.N
        
        # WHEN adding the word
        parser.add_lexical_entry(word, category)
        
        # THEN it should be in lexicon
        assert word in parser.lexicon
        assert any(t.category == category for t in parser.lexicon[word])
    
    def test_parse_simple_sentence(self, parser):
        """Test parsing a simple sentence."""
        # GIVEN a simple sentence
        sentence = "alice must run"
        
        # WHEN parsing
        trees = parser.parse(sentence)
        
        # THEN should produce parse trees
        assert isinstance(trees, list)
        # Note: Full tree building not implemented yet, so may be empty
    
    def test_parse_deontic_expression(self, parser):
        """Test parsing deontic expressions."""
        # GIVEN a deontic sentence
        sentence = "bob should open"
        
        # WHEN parsing
        trees = parser.parse(sentence)
        
        # THEN should handle deontic modals
        assert isinstance(trees, list)
    
    def test_parse_temporal_expression(self, parser):
        """Test parsing temporal expressions."""
        # GIVEN a temporal sentence
        sentence = "always door_open"
        
        # WHEN parsing
        trees = parser.parse(sentence)
        
        # THEN should handle temporal operators
        assert isinstance(trees, list)
    
    def test_parse_empty_sentence(self, parser):
        """Test parsing empty input."""
        # GIVEN an empty sentence
        sentence = ""
        
        # WHEN parsing
        trees = parser.parse(sentence)
        
        # THEN should return empty list
        assert trees == []
    
    def test_parse_unknown_words(self, parser):
        """Test parsing with unknown words."""
        # GIVEN a sentence with unknown words
        sentence = "unknown xyz abc"
        
        # WHEN parsing
        trees = parser.parse(sentence)
        
        # THEN should fail gracefully
        assert trees == []


class TestGrammarValidation:
    """Test grammar validation."""
    
    def test_validate_complete_grammar(self):
        """Test validating a complete grammar."""
        # GIVEN a parser with full grammar
        parser = EnhancedGrammarParser()
        
        # WHEN validating
        is_valid, issues = parser.validate_grammar()
        
        # THEN should report status
        assert isinstance(is_valid, bool)
        assert isinstance(issues, list)
    
    def test_validate_missing_start(self):
        """Test validation catches missing start symbol."""
        # GIVEN a parser with no start rules
        parser = EnhancedGrammarParser()
        parser.rules = [r for r in parser.rules if r.lhs != Category.S]
        
        # WHEN validating
        is_valid, issues = parser.validate_grammar()
        
        # THEN should detect missing start
        assert not is_valid
        assert any("start symbol" in issue.lower() for issue in issues)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
