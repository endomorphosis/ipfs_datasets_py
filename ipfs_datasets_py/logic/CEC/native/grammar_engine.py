"""
Grammar Engine for DCEC Natural Language Processing.

This module provides a Python-native grammar system that replaces the GF
(Grammatical Framework) based Eng-DCEC implementation. It supports compositional
semantics, parse tree construction, and bidirectional NL↔DCEC conversion.
"""

from typing import List, Dict, Optional, Any, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum
import logging

try:
    from beartype import beartype
except ImportError:
    from typing import TypeVar, Callable, Any
    F = TypeVar('F', bound=Callable[..., Any])
    def beartype(func: F) -> F:
        return func

logger = logging.getLogger(__name__)


class Category(Enum):
    """Grammatical categories for parse trees."""
    # Top-level
    UTTERANCE = "Utterance"
    SENTENCE = "Sentence"
    
    # Logic
    BOOLEAN = "Boolean"
    CLAUSE = "Cl"
    
    # DCEC Categories
    AGENT = "Agent"
    ACTION_TYPE = "ActionType"
    EVENT = "Event"
    MOMENT = "Moment"
    FLUENT = "Fluent"
    CLASS = "Class"
    DOMAIN = "Dom"
    ENTITY = "Entity"
    OBJECT = "Object"
    QUERY = "Query"
    
    # Linguistic categories
    NOUN_PHRASE = "NP"
    VERB_PHRASE = "VP"
    NOUN = "N"
    VERB = "V"
    ADJECTIVE = "A"
    ADVERB = "Adv"
    PREPOSITION = "Prep"
    DETERMINER = "Det"
    CONJUNCTION = "Conj"


@dataclass
class GrammarRule:
    """A grammar production rule.
    
    Attributes:
        name: Unique identifier for the rule
        category: Left-hand side category
        constituents: Right-hand side categories
        semantic_fn: Function to compute semantics from constituent semantics
        linearize_fn: Function to generate natural language from semantics
    """
    name: str
    category: Category
    constituents: List[Category]
    semantic_fn: Callable[[List[Any]], Any]
    linearize_fn: Optional[Callable[[Any], str]] = None
    
    def can_apply(self, categories: List[Category]) -> bool:
        """Check if this rule can apply to the given categories."""
        if len(categories) != len(self.constituents):
            return False
        return all(c1 == c2 for c1, c2 in zip(categories, self.constituents))
    
    def apply_semantics(self, semantic_values: List[Any]) -> Any:
        """Apply the semantic function to constituent values."""
        return self.semantic_fn(semantic_values)
    
    def linearize(self, semantic_value: Any) -> str:
        """Generate natural language from semantic value."""
        if self.linearize_fn:
            return self.linearize_fn(semantic_value)
        return str(semantic_value)


@dataclass
class LexicalEntry:
    """A lexical entry in the grammar.
    
    Attributes:
        word: The surface form
        category: Grammatical category
        semantics: Semantic representation
        features: Additional grammatical features (tense, gender, etc.)
    """
    word: str
    category: Category
    semantics: Any
    features: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ParseNode:
    """A node in a parse tree.
    
    Attributes:
        category: Grammatical category
        rule: Grammar rule used (None for lexical nodes)
        children: Child nodes
        semantics: Semantic value
        span: (start, end) position in input
    """
    category: Category
    rule: Optional[GrammarRule]
    children: List['ParseNode']
    semantics: Any
    span: Tuple[int, int]
    
    def is_lexical(self) -> bool:
        """Check if this is a lexical (leaf) node."""
        return self.rule is None and len(self.children) == 0
    
    def linearize(self) -> str:
        """Generate natural language from this subtree."""
        if self.is_lexical():
            return str(self.semantics)
        if self.rule and self.rule.linearize_fn:
            return self.rule.linearize(self.semantics)
        # Default: concatenate children
        return " ".join(child.linearize() for child in self.children)


class GrammarEngine:
    """Core grammar engine for parsing and generation.
    
    This engine supports:
    - Bottom-up chart parsing
    - Compositional semantics
    - Ambiguity detection and resolution
    - Bidirectional NL↔Logic conversion
    """
    
    def __init__(self):
        """Initialize the grammar engine."""
        self.rules: List[GrammarRule] = []
        self.lexicon: Dict[str, List[LexicalEntry]] = {}
        self.start_category = Category.UTTERANCE
        
    @beartype
    def add_rule(self, rule: GrammarRule) -> None:
        """Add a grammar rule to the engine.
        
        Args:
            rule: The grammar rule to add
        """
        self.rules.append(rule)
        logger.debug(f"Added grammar rule: {rule.name}")
    
    @beartype
    def add_lexical_entry(self, entry: LexicalEntry) -> None:
        """Add a lexical entry to the lexicon.
        
        Args:
            entry: The lexical entry to add
        """
        if entry.word not in self.lexicon:
            self.lexicon[entry.word] = []
        self.lexicon[entry.word].append(entry)
        logger.debug(f"Added lexical entry: {entry.word} → {entry.category.value}")
    
    @beartype
    def parse(self, text: str) -> List[ParseNode]:
        """Parse natural language text into parse trees.
        
        Uses bottom-up chart parsing with compositional semantics.
        
        Args:
            text: Input natural language text
            
        Returns:
            List of parse trees (may be multiple due to ambiguity)
        """
        # Tokenize
        tokens = self._tokenize(text)
        n = len(tokens)
        
        # Initialize chart: chart[i][j] contains parses for span [i, j)
        chart: List[List[List[ParseNode]]] = [[[] for _ in range(n + 1)] for _ in range(n + 1)]
        
        # Fill lexical entries
        for i, token in enumerate(tokens):
            if token in self.lexicon:
                for entry in self.lexicon[token]:
                    node = ParseNode(
                        category=entry.category,
                        rule=None,
                        children=[],
                        semantics=entry.semantics,
                        span=(i, i + 1)
                    )
                    chart[i][i + 1].append(node)
        
        # Bottom-up parsing
        for length in range(2, n + 1):  # length of span
            for i in range(n - length + 1):
                j = i + length
                # Try all split points
                for k in range(i + 1, j):
                    left_nodes = chart[i][k]
                    right_nodes = chart[k][j]
                    # Try all rule applications
                    for rule in self.rules:
                        if len(rule.constituents) == 2:
                            for left in left_nodes:
                                for right in right_nodes:
                                    if rule.can_apply([left.category, right.category]):
                                        semantics = rule.apply_semantics([left.semantics, right.semantics])
                                        node = ParseNode(
                                            category=rule.category,
                                            rule=rule,
                                            children=[left, right],
                                            semantics=semantics,
                                            span=(i, j)
                                        )
                                        chart[i][j].append(node)
                        elif len(rule.constituents) == 1:
                            # Unary rules
                            for left in left_nodes:
                                if rule.can_apply([left.category]):
                                    semantics = rule.apply_semantics([left.semantics])
                                    node = ParseNode(
                                        category=rule.category,
                                        rule=rule,
                                        children=[left],
                                        semantics=semantics,
                                        span=(i, j)
                                    )
                                    chart[i][j].append(node)
        
        # Return complete parses
        complete_parses = [node for node in chart[0][n]
                          if node.category == self.start_category]
        
        if not complete_parses:
            logger.warning(f"No complete parse found for: {text}")
        elif len(complete_parses) > 1:
            logger.info(f"Ambiguous parse: {len(complete_parses)} interpretations")
        
        return complete_parses
    
    @beartype
    def linearize(self, semantic_value: Any, category: Category) -> str:
        """Generate natural language from a semantic value.
        
        Args:
            semantic_value: The semantic representation
            category: The grammatical category
            
        Returns:
            Natural language string
        """
        # Find applicable linearization rules
        for rule in self.rules:
            if rule.category == category and rule.linearize_fn:
                try:
                    return rule.linearize_fn(semantic_value)
                except Exception as e:
                    logger.debug(f"Linearization failed for rule {rule.name}: {e}")
        
        # Default: string conversion
        return str(semantic_value)
    
    def _tokenize(self, text: str) -> List[str]:
        """Tokenize input text.
        
        Simple whitespace tokenization for now. Can be enhanced.
        
        Args:
            text: Input text
            
        Returns:
            List of tokens
        """
        # Basic tokenization
        tokens = text.lower().strip().split()
        return tokens
    
    @beartype
    def resolve_ambiguity(self, parses: List[ParseNode], strategy: str = "first") -> Optional[ParseNode]:
        """Resolve ambiguous parses using a strategy.
        
        Args:
            parses: List of parse trees
            strategy: Resolution strategy ("first", "shortest", "most_specific")
            
        Returns:
            Selected parse tree or None
        """
        if not parses:
            return None
        
        if strategy == "first":
            return parses[0]
        elif strategy == "shortest":
            # Prefer parse with fewest nodes
            return min(parses, key=self._count_nodes)
        elif strategy == "most_specific":
            # Prefer parse with most lexical specificity
            return max(parses, key=self._specificity_score)
        else:
            return parses[0]
    
    def _count_nodes(self, node: ParseNode) -> int:
        """Count total nodes in parse tree."""
        if node.is_lexical():
            return 1
        return 1 + sum(self._count_nodes(child) for child in node.children)
    
    def _specificity_score(self, node: ParseNode) -> float:
        """Calculate specificity score for a parse tree."""
        # Higher score for more specific lexical categories
        if node.is_lexical():
            specificity_map = {
                Category.AGENT: 5,
                Category.ACTION_TYPE: 4,
                Category.FLUENT: 3,
                Category.NOUN: 2,
                Category.VERB: 2,
            }
            return specificity_map.get(node.category, 1)
        return sum(self._specificity_score(child) for child in node.children)


@dataclass
class CompositeGrammar:
    """A composite grammar combining multiple grammar engines.
    
    Useful for modular grammar development and testing.
    """
    name: str
    engines: List[GrammarEngine] = field(default_factory=list)
    
    def add_engine(self, engine: GrammarEngine) -> None:
        """Add a grammar engine to this composite."""
        self.engines.append(engine)
    
    def parse(self, text: str) -> List[ParseNode]:
        """Parse using all engines and merge results."""
        all_parses = []
        for engine in self.engines:
            parses = engine.parse(text)
            all_parses.extend(parses)
        return all_parses
    
    def linearize(self, semantic_value: Any, category: Category) -> Optional[str]:
        """Try linearization with each engine until one succeeds."""
        for engine in self.engines:
            result = engine.linearize(semantic_value, category)
            if result and result != str(semantic_value):
                return result
        return None


# Helper functions for creating common grammar rules

@beartype
def make_binary_rule(
    name: str,
    category: Category,
    left_cat: Category,
    right_cat: Category,
    semantic_fn: Callable[[Any, Any], Any],
    linearize_fn: Optional[Callable[[Any], str]] = None
) -> GrammarRule:
    """Create a binary grammar rule.
    
    Args:
        name: Rule name
        category: Result category
        left_cat: Left constituent category
        right_cat: Right constituent category
        semantic_fn: Function combining left and right semantics
        linearize_fn: Optional linearization function
        
    Returns:
        Grammar rule
    """
    def wrapper_semantic_fn(constituents: List[Any]) -> Any:
        return semantic_fn(constituents[0], constituents[1])
    
    return GrammarRule(
        name=name,
        category=category,
        constituents=[left_cat, right_cat],
        semantic_fn=wrapper_semantic_fn,
        linearize_fn=linearize_fn
    )


@beartype
def make_unary_rule(
    name: str,
    category: Category,
    constituent_cat: Category,
    semantic_fn: Callable[[Any], Any],
    linearize_fn: Optional[Callable[[Any], str]] = None
) -> GrammarRule:
    """Create a unary grammar rule.
    
    Args:
        name: Rule name
        category: Result category
        constituent_cat: Constituent category
        semantic_fn: Function transforming constituent semantics
        linearize_fn: Optional linearization function
        
    Returns:
        Grammar rule
    """
    def wrapper_semantic_fn(constituents: List[Any]) -> Any:
        return semantic_fn(constituents[0])
    
    return GrammarRule(
        name=name,
        category=category,
        constituents=[constituent_cat],
        semantic_fn=wrapper_semantic_fn,
        linearize_fn=linearize_fn
    )
