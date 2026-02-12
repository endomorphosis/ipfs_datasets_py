"""
DCEC English Grammar Definition.

This module defines the grammar rules and lexicon for English→DCEC and DCEC→English
conversion. It provides a native Python implementation replacing the GF-based Eng-DCEC.
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass
import logging

from .grammar_engine import (
    GrammarEngine, Category, GrammarRule, LexicalEntry,
    make_binary_rule, make_unary_rule
)
from .dcec_core import (
    Formula, AtomicFormula, ConnectiveFormula, DeonticFormula,
    CognitiveFormula, TemporalFormula, QuantifiedFormula,
    LogicalConnective, Variable, Term, Function
)

try:
    from beartype import beartype
except ImportError:
    def beartype(func):
        return func

logger = logging.getLogger(__name__)


class DCECEnglishGrammar:
    """English grammar for DCEC with bidirectional conversion.
    
    This grammar supports:
    - Deontic operators: must, should, may, forbidden
    - Cognitive operators: believes, knows, intends, desires  
    - Temporal operators: always, eventually, next, until
    - Logical connectives: and, or, not, if-then
    - Quantifiers: all, some, every, any
    """
    
    def __init__(self):
        """Initialize the DCEC English grammar."""
        self.engine = GrammarEngine()
        self._setup_lexicon()
        self._setup_rules()
        
    def _setup_lexicon(self) -> None:
        """Set up the English lexicon for DCEC."""
        
        # === Logical Connectives ===
        self.engine.add_lexical_entry(LexicalEntry(
            word="and",
            category=Category.CONJUNCTION,
            semantics={"type": "and", "connective": LogicalConnective.AND}
        ))
        
        self.engine.add_lexical_entry(LexicalEntry(
            word="or",
            category=Category.CONJUNCTION,
            semantics={"type": "or", "connective": LogicalConnective.OR}
        ))
        
        self.engine.add_lexical_entry(LexicalEntry(
            word="not",
            category=Category.ADVERB,
            semantics={"type": "not", "connective": LogicalConnective.NOT}
        ))
        
        # === Deontic Modals ===
        # Obligated (must)
        self.engine.add_lexical_entry(LexicalEntry(
            word="must",
            category=Category.VERB,
            semantics={"type": "deontic", "operator": "obligated"}
        ))
        
        self.engine.add_lexical_entry(LexicalEntry(
            word="obligated",
            category=Category.VERB,
            semantics={"type": "deontic", "operator": "obligated"}
        ))
        
        # Forbidden
        self.engine.add_lexical_entry(LexicalEntry(
            word="forbidden",
            category=Category.VERB,
            semantics={"type": "deontic", "operator": "forbidden"}
        ))
        
        self.engine.add_lexical_entry(LexicalEntry(
            word="prohibited",
            category=Category.VERB,
            semantics={"type": "deontic", "operator": "forbidden"}
        ))
        
        # Permitted (may)
        self.engine.add_lexical_entry(LexicalEntry(
            word="may",
            category=Category.VERB,
            semantics={"type": "deontic", "operator": "permitted"}
        ))
        
        self.engine.add_lexical_entry(LexicalEntry(
            word="permitted",
            category=Category.VERB,
            semantics={"type": "deontic", "operator": "permitted"}
        ))
        
        # === Cognitive Modals ===
        # Believes
        self.engine.add_lexical_entry(LexicalEntry(
            word="believes",
            category=Category.VERB,
            semantics={"type": "cognitive", "operator": "believes"}
        ))
        
        self.engine.add_lexical_entry(LexicalEntry(
            word="belief",
            category=Category.NOUN,
            semantics={"type": "cognitive", "operator": "believes"}
        ))
        
        # Knows
        self.engine.add_lexical_entry(LexicalEntry(
            word="knows",
            category=Category.VERB,
            semantics={"type": "cognitive", "operator": "knows"}
        ))
        
        self.engine.add_lexical_entry(LexicalEntry(
            word="knowledge",
            category=Category.NOUN,
            semantics={"type": "cognitive", "operator": "knows"}
        ))
        
        # Intends
        self.engine.add_lexical_entry(LexicalEntry(
            word="intends",
            category=Category.VERB,
            semantics={"type": "cognitive", "operator": "intends"}
        ))
        
        self.engine.add_lexical_entry(LexicalEntry(
            word="intention",
            category=Category.NOUN,
            semantics={"type": "cognitive", "operator": "intends"}
        ))
        
        # Desires
        self.engine.add_lexical_entry(LexicalEntry(
            word="desires",
            category=Category.VERB,
            semantics={"type": "cognitive", "operator": "desires"}
        ))
        
        self.engine.add_lexical_entry(LexicalEntry(
            word="desire",
            category=Category.NOUN,
            semantics={"type": "cognitive", "operator": "desires"}
        ))
        
        # === Temporal Operators ===
        # Always (necessarily, globally)
        self.engine.add_lexical_entry(LexicalEntry(
            word="always",
            category=Category.ADVERB,
            semantics={"type": "temporal", "operator": "always"}
        ))
        
        self.engine.add_lexical_entry(LexicalEntry(
            word="necessarily",
            category=Category.ADVERB,
            semantics={"type": "temporal", "operator": "always"}
        ))
        
        # Eventually (finally, someday)
        self.engine.add_lexical_entry(LexicalEntry(
            word="eventually",
            category=Category.ADVERB,
            semantics={"type": "temporal", "operator": "eventually"}
        ))
        
        self.engine.add_lexical_entry(LexicalEntry(
            word="finally",
            category=Category.ADVERB,
            semantics={"type": "temporal", "operator": "eventually"}
        ))
        
        self.engine.add_lexical_entry(LexicalEntry(
            word="someday",
            category=Category.ADVERB,
            semantics={"type": "temporal", "operator": "eventually"}
        ))
        
        # Next
        self.engine.add_lexical_entry(LexicalEntry(
            word="next",
            category=Category.ADVERB,
            semantics={"type": "temporal", "operator": "next"}
        ))
        
        # Until
        self.engine.add_lexical_entry(LexicalEntry(
            word="until",
            category=Category.PREPOSITION,
            semantics={"type": "temporal", "operator": "until"}
        ))
        
        # === Quantifiers ===
        self.engine.add_lexical_entry(LexicalEntry(
            word="all",
            category=Category.DETERMINER,
            semantics={"type": "quantifier", "operator": "forall"}
        ))
        
        self.engine.add_lexical_entry(LexicalEntry(
            word="every",
            category=Category.DETERMINER,
            semantics={"type": "quantifier", "operator": "forall"}
        ))
        
        self.engine.add_lexical_entry(LexicalEntry(
            word="some",
            category=Category.DETERMINER,
            semantics={"type": "quantifier", "operator": "exists"}
        ))
        
        self.engine.add_lexical_entry(LexicalEntry(
            word="any",
            category=Category.DETERMINER,
            semantics={"type": "quantifier", "operator": "exists"}
        ))
        
        # === Common Agents ===
        for agent_name in ["jack", "robot", "alice", "bob", "system"]:
            self.engine.add_lexical_entry(LexicalEntry(
                word=agent_name,
                category=Category.AGENT,
                semantics={"type": "agent", "name": agent_name}
            ))
        
        # === Common Actions ===
        for action in ["laugh", "sleep", "run", "eat", "walk", "talk", "work"]:
            self.engine.add_lexical_entry(LexicalEntry(
                word=action,
                category=Category.ACTION_TYPE,
                semantics={"type": "action", "name": action}
            ))
        
        # === Common Fluents (predicates) ===
        for fluent in ["happy", "sad", "hungry", "tired", "sick", "angry"]:
            self.engine.add_lexical_entry(LexicalEntry(
                word=fluent,
                category=Category.FLUENT,
                semantics={"type": "fluent", "name": fluent}
            ))
        
        # === Auxiliary Words ===
        for word in ["is", "are", "was", "were", "be", "been", "being"]:
            self.engine.add_lexical_entry(LexicalEntry(
                word=word,
                category=Category.VERB,
                semantics={"type": "auxiliary", "word": word}
            ))
        
        for word in ["to", "the", "a", "an"]:
            self.engine.add_lexical_entry(LexicalEntry(
                word=word,
                category=Category.DETERMINER,
                semantics={"type": "determiner", "word": word}
            ))
            
        # === Conditional words ===
        self.engine.add_lexical_entry(LexicalEntry(
            word="if",
            category=Category.CONJUNCTION,
            semantics={"type": "if", "connective": LogicalConnective.IMPLIES}
        ))
        
        self.engine.add_lexical_entry(LexicalEntry(
            word="then",
            category=Category.CONJUNCTION,
            semantics={"type": "then"}
        ))
        
    def _setup_rules(self) -> None:
        """Set up grammar rules for compositional semantics."""
        
        # === Logical Connectives ===
        
        # AND: Boolean AND Boolean → Boolean
        self.engine.add_rule(make_binary_rule(
            name="and_rule",
            category=Category.BOOLEAN,
            left_cat=Category.BOOLEAN,
            right_cat=Category.BOOLEAN,
            semantic_fn=lambda left, right: {
                "type": "connective",
                "operator": LogicalConnective.AND,
                "left": left,
                "right": right
            },
            linearize_fn=lambda sem: f"{self._linearize_boolean(sem['left'])} and {self._linearize_boolean(sem['right'])}"
        ))
        
        # OR: Boolean OR Boolean → Boolean
        self.engine.add_rule(make_binary_rule(
            name="or_rule",
            category=Category.BOOLEAN,
            left_cat=Category.BOOLEAN,
            right_cat=Category.BOOLEAN,
            semantic_fn=lambda left, right: {
                "type": "connective",
                "operator": LogicalConnective.OR,
                "left": left,
                "right": right
            },
            linearize_fn=lambda sem: f"{self._linearize_boolean(sem['left'])} or {self._linearize_boolean(sem['right'])}"
        ))
        
        # NOT: NOT Boolean → Boolean
        self.engine.add_rule(make_unary_rule(
            name="not_rule",
            category=Category.BOOLEAN,
            constituent_cat=Category.BOOLEAN,
            semantic_fn=lambda inner: {
                "type": "connective",
                "operator": LogicalConnective.NOT,
                "formula": inner
            },
            linearize_fn=lambda sem: f"not {self._linearize_boolean(sem['formula'])}"
        ))
        
        # IMPLIES: Boolean IMPLIES Boolean → Boolean
        self.engine.add_rule(make_binary_rule(
            name="implies_rule",
            category=Category.BOOLEAN,
            left_cat=Category.BOOLEAN,
            right_cat=Category.BOOLEAN,
            semantic_fn=lambda left, right: {
                "type": "connective",
                "operator": LogicalConnective.IMPLIES,
                "left": left,
                "right": right
            },
            linearize_fn=lambda sem: f"if {self._linearize_boolean(sem['left'])} then {self._linearize_boolean(sem['right'])}"
        ))
        
        # === Deontic Modalities ===
        
        # OBLIGATED: Agent must Action → Boolean
        self.engine.add_rule(make_binary_rule(
            name="obligated_rule",
            category=Category.BOOLEAN,
            left_cat=Category.AGENT,
            right_cat=Category.ACTION_TYPE,
            semantic_fn=lambda agent, action: {
                "type": "deontic",
                "operator": "obligated",
                "agent": agent,
                "action": action
            },
            linearize_fn=lambda sem: f"{sem['agent']['name']} must {sem['action']['name']}"
        ))
        
        # FORBIDDEN: Agent forbidden Action → Boolean
        self.engine.add_rule(make_binary_rule(
            name="forbidden_rule",
            category=Category.BOOLEAN,
            left_cat=Category.AGENT,
            right_cat=Category.ACTION_TYPE,
            semantic_fn=lambda agent, action: {
                "type": "deontic",
                "operator": "forbidden",
                "agent": agent,
                "action": action
            },
            linearize_fn=lambda sem: f"{sem['agent']['name']} is forbidden to {sem['action']['name']}"
        ))
        
        # === Cognitive Modalities ===
        
        # BELIEVES: Agent believes Boolean → Boolean
        self.engine.add_rule(make_binary_rule(
            name="believes_rule",
            category=Category.BOOLEAN,
            left_cat=Category.AGENT,
            right_cat=Category.BOOLEAN,
            semantic_fn=lambda agent, prop: {
                "type": "cognitive",
                "operator": "believes",
                "agent": agent,
                "proposition": prop
            },
            linearize_fn=lambda sem: f"{sem['agent']['name']} believes {self._linearize_boolean(sem['proposition'])}"
        ))
        
        # KNOWS: Agent knows Boolean → Boolean
        self.engine.add_rule(make_binary_rule(
            name="knows_rule",
            category=Category.BOOLEAN,
            left_cat=Category.AGENT,
            right_cat=Category.BOOLEAN,
            semantic_fn=lambda agent, prop: {
                "type": "cognitive",
                "operator": "knows",
                "agent": agent,
                "proposition": prop
            },
            linearize_fn=lambda sem: f"{sem['agent']['name']} knows {self._linearize_boolean(sem['proposition'])}"
        ))
        
        # === Temporal Modalities ===
        
        # ALWAYS: always Boolean → Boolean
        self.engine.add_rule(make_unary_rule(
            name="always_rule",
            category=Category.BOOLEAN,
            constituent_cat=Category.BOOLEAN,
            semantic_fn=lambda prop: {
                "type": "temporal",
                "operator": "always",
                "proposition": prop
            },
            linearize_fn=lambda sem: f"always {self._linearize_boolean(sem['proposition'])}"
        ))
        
        # EVENTUALLY: eventually Boolean → Boolean
        self.engine.add_rule(make_unary_rule(
            name="eventually_rule",
            category=Category.BOOLEAN,
            constituent_cat=Category.BOOLEAN,
            semantic_fn=lambda prop: {
                "type": "temporal",
                "operator": "eventually",
                "proposition": prop
            },
            linearize_fn=lambda sem: f"eventually {self._linearize_boolean(sem['proposition'])}"
        ))
        
        # === Basic Predicates ===
        
        # Agent is Fluent → Boolean
        self.engine.add_rule(make_binary_rule(
            name="agent_fluent_rule",
            category=Category.BOOLEAN,
            left_cat=Category.AGENT,
            right_cat=Category.FLUENT,
            semantic_fn=lambda agent, fluent: {
                "type": "atomic",
                "predicate": fluent["name"],
                "arguments": [agent]
            },
            linearize_fn=lambda sem: f"{sem['arguments'][0]['name']} is {sem['predicate']}"
        ))
        
        # Agent ActionType → Boolean
        self.engine.add_rule(make_binary_rule(
            name="agent_action_rule",
            category=Category.BOOLEAN,
            left_cat=Category.AGENT,
            right_cat=Category.ACTION_TYPE,
            semantic_fn=lambda agent, action: {
                "type": "atomic",
                "predicate": action["name"],
                "arguments": [agent]
            },
            linearize_fn=lambda sem: f"{sem['arguments'][0]['name']} {sem['predicate']}s"
        ))
    
    def _linearize_boolean(self, semantic_value: Any) -> str:
        """Helper to linearize boolean semantic values."""
        if not isinstance(semantic_value, dict):
            return str(semantic_value)
        
        sem_type = semantic_value.get("type", "unknown")
        
        if sem_type == "connective":
            op = semantic_value["operator"]
            if op == LogicalConnective.AND:
                left = self._linearize_boolean(semantic_value["left"])
                right = self._linearize_boolean(semantic_value["right"])
                return f"({left} and {right})"
            elif op == LogicalConnective.OR:
                left = self._linearize_boolean(semantic_value["left"])
                right = self._linearize_boolean(semantic_value["right"])
                return f"({left} or {right})"
            elif op == LogicalConnective.NOT:
                inner = self._linearize_boolean(semantic_value["formula"])
                return f"not {inner}"
            elif op == LogicalConnective.IMPLIES:
                left = self._linearize_boolean(semantic_value["left"])
                right = self._linearize_boolean(semantic_value["right"])
                return f"if {left} then {right}"
        
        elif sem_type == "deontic":
            op = semantic_value["operator"]
            agent = semantic_value["agent"]["name"]
            action = semantic_value["action"]["name"]
            if op == "obligated":
                return f"{agent} must {action}"
            elif op == "forbidden":
                return f"{agent} is forbidden to {action}"
            elif op == "permitted":
                return f"{agent} may {action}"
        
        elif sem_type == "cognitive":
            op = semantic_value["operator"]
            agent = semantic_value["agent"]["name"]
            prop = self._linearize_boolean(semantic_value["proposition"])
            return f"{agent} {op} {prop}"
        
        elif sem_type == "temporal":
            op = semantic_value["operator"]
            prop = self._linearize_boolean(semantic_value["proposition"])
            return f"{op} {prop}"
        
        elif sem_type == "atomic":
            pred = semantic_value["predicate"]
            args = semantic_value.get("arguments", [])
            if args:
                agent_name = args[0].get("name", "?")
                return f"{agent_name} {pred}"
            return pred
        
        return str(semantic_value)
    
    @beartype
    def parse_to_dcec(self, text: str) -> Optional[Formula]:
        """Parse English text to DCEC formula.
        
        Args:
            text: English text
            
        Returns:
            DCEC Formula object or None
        """
        parses = self.engine.parse(text)
        if not parses:
            logger.warning(f"No parse found for: {text}")
            return None
        
        # Resolve ambiguity if multiple parses
        parse = self.engine.resolve_ambiguity(parses, strategy="first")
        
        # Convert semantic value to Formula
        return self._semantic_to_formula(parse.semantics)
    
    @beartype
    def formula_to_english(self, formula: Formula) -> str:
        """Convert DCEC formula to English.
        
        Args:
            formula: DCEC Formula object
            
        Returns:
            English text
        """
        # Convert formula to semantic representation
        semantic_value = self._formula_to_semantic(formula)
        
        # Linearize to English
        return self._linearize_boolean(semantic_value)
    
    def _semantic_to_formula(self, semantic_value: Any) -> Optional[Formula]:
        """Convert semantic representation to Formula object."""
        if not isinstance(semantic_value, dict):
            return None
        
        sem_type = semantic_value.get("type", "unknown")
        
        if sem_type == "connective":
            op = semantic_value["operator"]
            if op in [LogicalConnective.AND, LogicalConnective.OR, LogicalConnective.IMPLIES]:
                left = self._semantic_to_formula(semantic_value["left"])
                right = self._semantic_to_formula(semantic_value["right"])
                if left and right:
                    return ConnectiveFormula(op, [left, right])
            elif op == LogicalConnective.NOT:
                inner = self._semantic_to_formula(semantic_value["formula"])
                if inner:
                    return ConnectiveFormula(op, [inner])
        
        elif sem_type == "atomic":
            # Create atomic formula
            predicate = semantic_value["predicate"]
            return AtomicFormula(predicate, [])
        
        # Add more conversions for deontic, cognitive, temporal...
        # This is simplified for now
        
        return None
    
    def _formula_to_semantic(self, formula: Formula) -> Dict[str, Any]:
        """Convert Formula object to semantic representation."""
        if isinstance(formula, AtomicFormula):
            return {
                "type": "atomic",
                "predicate": formula.predicate,
                "arguments": []
            }
        elif isinstance(formula, ConnectiveFormula):
            if formula.connective in [LogicalConnective.AND, LogicalConnective.OR, LogicalConnective.IMPLIES]:
                return {
                    "type": "connective",
                    "operator": formula.connective,
                    "left": self._formula_to_semantic(formula.formulas[0]),
                    "right": self._formula_to_semantic(formula.formulas[1])
                }
            elif formula.connective == LogicalConnective.NOT:
                return {
                    "type": "connective",
                    "operator": formula.connective,
                    "formula": self._formula_to_semantic(formula.formulas[0])
                }
        
        # Add more conversions...
        return {"type": "unknown", "formula": str(formula)}


def create_dcec_grammar() -> DCECEnglishGrammar:
    """Factory function to create a configured DCEC English grammar.
    
    Returns:
        Initialized DCEC English grammar
    """
    grammar = DCECEnglishGrammar()
    logger.info("DCEC English grammar initialized")
    return grammar
