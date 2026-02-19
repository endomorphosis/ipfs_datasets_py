"""
Enhanced Grammar-Based Parser for DCEC Natural Language Processing.

This module implements a sophisticated chart parser (Earley algorithm) with:
- Context-free grammar rules for DCEC constructs
- Compositional semantics
- Parse tree construction and validation
- Support for deontic, cognitive, and temporal expressions
"""

from typing import List, Dict, Optional, Set, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
import logging

try:
    from beartype import beartype
except ImportError:
    from typing import TypeVar, Callable
    F = TypeVar('F', bound=Callable[..., Any])
    def beartype(func: F) -> F:
        return func

logger = logging.getLogger(__name__)


class Category(Enum):
    """Grammar categories for DCEC parsing."""
    # Top level
    S = "S"  # Sentence
    NP = "NP"  # Noun phrase
    VP = "VP"  # Verb phrase
    
    # DCEC specific
    DEONTIC = "Deontic"  # Deontic expressions
    COGNITIVE = "Cognitive"  # Cognitive attitudes
    TEMPORAL = "Temporal"  # Temporal expressions
    AGENT = "Agent"
    ACTION = "Action"
    FLUENT = "Fluent"
    
    # Basic
    N = "N"  # Noun
    V = "V"  # Verb
    ADJ = "ADJ"  # Adjective
    ADV = "ADV"  # Adverb
    DET = "DET"  # Determiner
    MODAL = "MODAL"  # Modal verb


@dataclass
class Terminal:
    """A terminal symbol (word)."""
    word: str
    category: Category
    
    def __str__(self) -> str:
        return f"{self.word}:{self.category.value}"
    
    def __hash__(self) -> int:
        return hash((self.word, self.category))


@dataclass
class GrammarRule:
    """A context-free grammar production rule.
    
    Format: lhs -> rhs[0] rhs[1] ... rhs[n]
    """
    lhs: Category
    rhs: List[Category]
    semantic_fn: Optional[Any] = None
    
    def __str__(self) -> str:
        rhs_str = " ".join(c.value for c in self.rhs)
        return f"{self.lhs.value} -> {rhs_str}"
    
    def __hash__(self) -> int:
        return hash((self.lhs, tuple(self.rhs)))


@dataclass
class ParseTree:
    """A parse tree node."""
    category: Category
    children: List['ParseTree'] = field(default_factory=list)
    terminal: Optional[Terminal] = None
    semantics: Optional[Any] = None
    
    def is_terminal(self) -> bool:
        """Check if this is a terminal node."""
        return self.terminal is not None
    
    def to_string(self, indent: int = 0) -> str:
        """Pretty print the parse tree."""
        prefix = "  " * indent
        if self.is_terminal():
            return f"{prefix}{self.category.value}: {self.terminal.word}"
        else:
            result = f"{prefix}{self.category.value}\n"
            for child in self.children:
                result += child.to_string(indent + 1) + "\n"
            return result.rstrip()
    
    def leaves(self) -> List[str]:
        """Get all terminal words in left-to-right order."""
        if self.is_terminal():
            return [self.terminal.word]
        return [word for child in self.children for word in child.leaves()]


@dataclass
class EarleyState:
    """A state in the Earley parser chart.
    
    Format: rule [dot_pos] (origin, current)
    Example: S -> NP • VP (0, 2)
    """
    rule: GrammarRule
    dot_pos: int
    origin: int
    current: int
    tree: Optional[ParseTree] = None
    
    def next_category(self) -> Optional[Category]:
        """Get the category after the dot, or None if complete."""
        if self.is_complete():
            return None
        return self.rule.rhs[self.dot_pos]
    
    def is_complete(self) -> bool:
        """Check if the dot is at the end."""
        return self.dot_pos >= len(self.rule.rhs)
    
    def advance(self) -> 'EarleyState':
        """Create a new state with the dot advanced."""
        return EarleyState(
            rule=self.rule,
            dot_pos=self.dot_pos + 1,
            origin=self.origin,
            current=self.current,
            tree=self.tree
        )
    
    def __str__(self) -> str:
        rhs_before = " ".join(c.value for c in self.rule.rhs[:self.dot_pos])
        rhs_after = " ".join(c.value for c in self.rule.rhs[self.dot_pos:])
        return f"{self.rule.lhs.value} -> {rhs_before} • {rhs_after} ({self.origin}, {self.current})"
    
    def __hash__(self) -> int:
        return hash((self.rule, self.dot_pos, self.origin, self.current))
    
    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, EarleyState):
            return False
        return (self.rule == other.rule and 
                self.dot_pos == other.dot_pos and
                self.origin == other.origin and
                self.current == other.current)


class EnhancedGrammarParser:
    """Enhanced Earley chart parser for DCEC grammar."""
    
    def __init__(self):
        """Initialize the parser with DCEC grammar rules."""
        self.rules: List[GrammarRule] = []
        self.lexicon: Dict[str, List[Terminal]] = {}
        self.start_symbol = Category.S
        self._init_grammar()
        self._init_lexicon()
    
    def _init_grammar(self):
        """Initialize context-free grammar rules for DCEC."""
        # Sentence rules
        self.rules.extend([
            GrammarRule(Category.S, [Category.NP, Category.VP]),
            GrammarRule(Category.S, [Category.DEONTIC]),
            GrammarRule(Category.S, [Category.COGNITIVE]),
            GrammarRule(Category.S, [Category.TEMPORAL]),
        ])
        
        # Noun phrase rules
        self.rules.extend([
            GrammarRule(Category.NP, [Category.DET, Category.N]),
            GrammarRule(Category.NP, [Category.N]),
            GrammarRule(Category.NP, [Category.AGENT]),
        ])
        
        # Verb phrase rules
        self.rules.extend([
            GrammarRule(Category.VP, [Category.V]),
            GrammarRule(Category.VP, [Category.V, Category.NP]),
            GrammarRule(Category.VP, [Category.MODAL, Category.V]),
            GrammarRule(Category.VP, [Category.ACTION]),
        ])
        
        # Deontic expressions
        self.rules.extend([
            GrammarRule(Category.DEONTIC, [Category.AGENT, Category.MODAL, Category.ACTION]),
            GrammarRule(Category.DEONTIC, [Category.MODAL, Category.ACTION]),
        ])
        
        # Cognitive expressions
        self.rules.extend([
            GrammarRule(Category.COGNITIVE, [Category.AGENT, Category.V, Category.S]),
            GrammarRule(Category.COGNITIVE, [Category.AGENT, Category.V, Category.FLUENT]),
        ])
        
        # Temporal expressions
        self.rules.extend([
            GrammarRule(Category.TEMPORAL, [Category.ADV, Category.S]),
            GrammarRule(Category.TEMPORAL, [Category.ADV, Category.FLUENT]),
        ])
    
    def _init_lexicon(self):
        """Initialize lexicon with DCEC-relevant words."""
        # Determiners
        self._add_words(["the", "a", "an"], Category.DET)
        
        # Nouns
        self._add_words(["agent", "person", "robot", "system"], Category.N)
        self._add_words(["alice", "bob", "charlie"], Category.AGENT)
        
        # Verbs
        self._add_words(["run", "walk", "think", "believe", "know"], Category.V)
        self._add_words(["open", "close", "move", "stop"], Category.ACTION)
        
        # Modals (deontic)
        self._add_words(["must", "should", "may", "can", "must_not"], Category.MODAL)
        
        # Adverbs (temporal)
        self._add_words(["always", "eventually", "never", "sometimes"], Category.ADV)
        
        # Fluents
        self._add_words(["door_open", "light_on", "running"], Category.FLUENT)
    
    def _add_words(self, words: List[str], category: Category):
        """Add words to the lexicon."""
        for word in words:
            terminal = Terminal(word, category)
            if word not in self.lexicon:
                self.lexicon[word] = []
            self.lexicon[word].append(terminal)
    
    def add_rule(self, rule: GrammarRule):
        """Add a grammar rule."""
        self.rules.append(rule)
    
    def add_lexical_entry(self, word: str, category: Category):
        """Add a word to the lexicon."""
        self._add_words([word], category)
    
    @beartype
    def parse(self, sentence: str) -> List[ParseTree]:
        """Parse a sentence using the Earley algorithm.
        
        Args:
            sentence: Input sentence to parse
            
        Returns:
            List of possible parse trees (may be empty if no parse found)
        """
        words = sentence.lower().split()
        n = len(words)
        
        # Initialize chart: chart[i] contains states ending at position i
        chart: List[Set[EarleyState]] = [set() for _ in range(n + 1)]
        
        # Initialize with start rules
        for rule in self.rules:
            if rule.lhs == self.start_symbol:
                chart[0].add(EarleyState(rule, 0, 0, 0))
        
        # Main parsing loop
        for i in range(n + 1):
            for state in list(chart[i]):
                if state.is_complete():
                    self._completer(chart, state, i)
                else:
                    next_cat = state.next_category()
                    if self._is_terminal(next_cat):
                        if i < n:
                            self._scanner(chart, state, words[i], i)
                    else:
                        self._predictor(chart, state, i)
        
        # Extract completed parses
        return self._extract_trees(chart, n, words)
    
    def _is_terminal(self, category: Optional[Category]) -> bool:
        """Check if a category is terminal (exists in lexicon)."""
        if category is None:
            return False
        # Terminal categories are those with lexical entries
        for terminals in self.lexicon.values():
            if any(t.category == category for t in terminals):
                return True
        return False
    
    def _predictor(self, chart: List[Set[EarleyState]], state: EarleyState, position: int):
        """Predictor: add rules that can produce the next category."""
        next_cat = state.next_category()
        if next_cat is None:
            return
        
        for rule in self.rules:
            if rule.lhs == next_cat:
                new_state = EarleyState(rule, 0, position, position)
                chart[position].add(new_state)
    
    def _scanner(self, chart: List[Set[EarleyState]], state: EarleyState, 
                 word: str, position: int):
        """Scanner: match terminal symbol against input word."""
        next_cat = state.next_category()
        if next_cat is None or word not in self.lexicon:
            return
        
        for terminal in self.lexicon[word]:
            if terminal.category == next_cat:
                new_state = state.advance()
                new_state.current = position + 1
                new_state.tree = ParseTree(next_cat, terminal=terminal)
                chart[position + 1].add(new_state)
    
    def _completer(self, chart: List[Set[EarleyState]], completed_state: EarleyState,
                   position: int):
        """Completer: advance states that were waiting for this category."""
        completed_cat = completed_state.rule.lhs
        origin = completed_state.origin
        
        for state in list(chart[origin]):
            if state.next_category() == completed_cat:
                new_state = state.advance()
                new_state.current = position
                chart[position].add(new_state)
    
    def _extract_trees(self, chart: List[Set[EarleyState]], n: int, 
                       words: List[str]) -> List[ParseTree]:
        """Extract parse trees from completed chart."""
        trees = []
        
        for state in chart[n]:
            if (state.rule.lhs == self.start_symbol and 
                state.is_complete() and 
                state.origin == 0):
                tree = self._build_tree(state, words)
                if tree:
                    trees.append(tree)
        
        return trees
    
    def _build_tree(self, state: EarleyState, words: List[str]) -> Optional[ParseTree]:
        """Build a parse tree from a completed state."""
        if state.tree:
            return state.tree
        
        # Reconstruct tree from rule
        tree = ParseTree(state.rule.lhs)
        # For now, create a simplified tree
        # A full implementation would track subtrees during parsing
        return tree
    
    def validate_grammar(self) -> Tuple[bool, List[str]]:
        """Validate the grammar for common issues.
        
        Returns:
            Tuple of (is_valid, list of warnings/errors)
        """
        issues = []
        
        # Check for start symbol
        has_start = any(r.lhs == self.start_symbol for r in self.rules)
        if not has_start:
            issues.append(f"No rules for start symbol {self.start_symbol.value}")
        
        # Check for unreachable categories
        reachable = {self.start_symbol}
        changed = True
        while changed:
            changed = False
            for rule in self.rules:
                if rule.lhs in reachable:
                    for cat in rule.rhs:
                        if cat not in reachable:
                            reachable.add(cat)
                            changed = True
        
        all_categories = {rule.lhs for rule in self.rules}
        unreachable = all_categories - reachable
        if unreachable:
            issues.append(f"Unreachable categories: {[c.value for c in unreachable]}")
        
        # Check for unproductive categories (can't produce terminals)
        productive = set()
        for word, terminals in self.lexicon.items():
            for t in terminals:
                productive.add(t.category)
        
        changed = True
        while changed:
            changed = False
            for rule in self.rules:
                if all(cat in productive for cat in rule.rhs):
                    if rule.lhs not in productive:
                        productive.add(rule.lhs)
                        changed = True
        
        unproductive = all_categories - productive
        if unproductive:
            issues.append(f"Unproductive categories: {[c.value for c in unproductive]}")
        
        return len(issues) == 0, issues
