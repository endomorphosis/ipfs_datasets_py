"""
TDFOL Pattern Matcher for Natural Language Processing

This module provides pattern-based matching for legal and deontic language,
enabling conversion from natural language to TDFOL formulas.

Patterns cover:
- Universal quantification (all, every, any)
- Obligations (must, shall, required to)
- Permissions (may, can, allowed to)
- Prohibitions (must not, forbidden to)
- Temporal expressions (always, eventually, until)
- Conditionals (if-then, when, provided that)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Import spaCy from centralized utils
from .spacy_utils import HAVE_SPACY, spacy, Doc, Span, Matcher


class PatternType(Enum):
    """Types of patterns for TDFOL conversion."""
    
    UNIVERSAL_QUANTIFICATION = "universal_quantification"
    OBLIGATION = "obligation"
    PERMISSION = "permission"
    PROHIBITION = "prohibition"
    TEMPORAL = "temporal"
    CONDITIONAL = "conditional"


@dataclass
class Pattern:
    """
    A pattern for matching natural language constructs.
    
    Patterns can be:
    - Text-based (regex patterns)
    - Token-based (spaCy patterns)
    - Hybrid (both)
    """
    
    name: str                           # Pattern identifier
    type: PatternType                   # Pattern category
    text_pattern: Optional[str] = None  # Regex pattern for text
    token_pattern: Optional[List[Dict[str, Any]]] = None  # spaCy token pattern
    description: str = ""               # Human-readable description
    examples: List[str] = field(default_factory=list)  # Example sentences
    metadata: Dict[str, Any] = field(default_factory=dict)  # Additional data
    
    def __hash__(self) -> int:
        return hash((self.name, self.type))


@dataclass
class PatternMatch:
    """
    Result of matching a pattern against text.
    
    Contains:
    - The matched pattern
    - The span of text that matched
    - Extracted entities and slots
    - Confidence score
    """
    
    pattern: Pattern                     # The pattern that matched
    span: Tuple[int, int]               # Character span (start, end)
    text: str                           # Matched text
    entities: Dict[str, str]            # Extracted entities (agent, action, etc.)
    confidence: float                   # Confidence score (0.0-1.0)
    spacy_span: Optional[Any] = None    # Original spaCy Span if available
    metadata: Dict[str, Any] = field(default_factory=dict)


class PatternMatcher:
    """
    Pattern matcher for TDFOL natural language processing.
    
    Provides pattern-based matching using both regex and spaCy token patterns
    to identify legal and deontic constructs in natural language.
    
    Example:
        >>> matcher = PatternMatcher()
        >>> matches = matcher.match("All contractors must pay taxes.")
        >>> for match in matches:
        ...     print(f"{match.pattern.type}: {match.text}")
        universal_quantification: All contractors
        obligation: must pay taxes
    """
    
    def __init__(self, model: str = "en_core_web_sm"):
        """
        Initialize pattern matcher.
        
        Args:
            model: spaCy model name (default: en_core_web_sm)
        
        Raises:
            ImportError: If spaCy is not installed
            OSError: If spaCy model is not downloaded
        """
        if not HAVE_SPACY:
            raise ImportError(
                "spaCy is required for pattern matching. "
                "Install with: pip install ipfs_datasets_py[knowledge_graphs]"
            )
        
        try:
            self.nlp = spacy.load(model)
        except OSError:
            logger.error(f"spaCy model '{model}' not found. Download with: python -m spacy download {model}")
            raise
        
        self.matcher = Matcher(self.nlp.vocab)
        self.patterns: List[Pattern] = []
        self._load_patterns()
        self._register_patterns()
    
    def _load_patterns(self) -> None:
        """Load all predefined patterns."""
        self.patterns = []
        
        # Universal quantification patterns
        self.patterns.extend(self._create_universal_patterns())
        
        # Obligation patterns
        self.patterns.extend(self._create_obligation_patterns())
        
        # Permission patterns
        self.patterns.extend(self._create_permission_patterns())
        
        # Prohibition patterns
        self.patterns.extend(self._create_prohibition_patterns())
        
        # Temporal patterns
        self.patterns.extend(self._create_temporal_patterns())
        
        # Conditional patterns
        self.patterns.extend(self._create_conditional_patterns())
    
    def _create_universal_patterns(self) -> List[Pattern]:
        """Create universal quantification patterns."""
        return [
            Pattern(
                name="all_agent_must_action",
                type=PatternType.UNIVERSAL_QUANTIFICATION,
                token_pattern=[
                    {"LOWER": "all"},
                    {"POS": "NOUN", "OP": "+"},
                    {"LOWER": {"IN": ["must", "shall", "should", "may"]}},
                    {"POS": "VERB"}
                ],
                description="All <agent> must/shall/may <action>",
                examples=["All contractors must pay taxes", "All employees shall comply"]
            ),
            Pattern(
                name="every_agent_verb",
                type=PatternType.UNIVERSAL_QUANTIFICATION,
                token_pattern=[
                    {"LOWER": "every"},
                    {"POS": "NOUN", "OP": "+"},
                    {"POS": "AUX", "OP": "?"},
                    {"POS": "VERB"}
                ],
                description="Every <agent> <verb>",
                examples=["Every contractor pays taxes", "Every employee must comply"]
            ),
            Pattern(
                name="any_agent_verb",
                type=PatternType.UNIVERSAL_QUANTIFICATION,
                token_pattern=[
                    {"LOWER": "any"},
                    {"POS": "NOUN", "OP": "+"},
                    {"LOWER": {"IN": ["must", "shall", "should", "may"]}},
                    {"POS": "VERB"}
                ],
                description="Any <agent> must/shall/may <action>",
                examples=["Any contractor must register", "Any employee may apply"]
            ),
            Pattern(
                name="each_agent_verb",
                type=PatternType.UNIVERSAL_QUANTIFICATION,
                token_pattern=[
                    {"LOWER": "each"},
                    {"POS": "NOUN", "OP": "+"},
                    {"POS": "AUX", "OP": "?"},
                    {"POS": "VERB"}
                ],
                description="Each <agent> <verb>",
                examples=["Each contractor pays", "Each employee must sign"]
            ),
            Pattern(
                name="agents_plural_must",
                type=PatternType.UNIVERSAL_QUANTIFICATION,
                text_pattern=r"(\w+s)\s+(must|shall|should|are required to)\s+(\w+)",
                description="<agents> must/shall <action>",
                examples=["Contractors must pay", "Employees shall comply"]
            ),
            Pattern(
                name="all_agents_are_required",
                type=PatternType.UNIVERSAL_QUANTIFICATION,
                token_pattern=[
                    {"LOWER": "all"},
                    {"POS": "NOUN", "OP": "+"},
                    {"LOWER": "are"},
                    {"LOWER": "required"},
                    {"LOWER": "to"},
                    {"POS": "VERB"}
                ],
                description="All <agents> are required to <action>",
                examples=["All contractors are required to register"]
            ),
            Pattern(
                name="every_agent_is_obligated",
                type=PatternType.UNIVERSAL_QUANTIFICATION,
                token_pattern=[
                    {"LOWER": "every"},
                    {"POS": "NOUN", "OP": "+"},
                    {"LOWER": "is"},
                    {"LOWER": "obligated"},
                    {"LOWER": "to"},
                    {"POS": "VERB"}
                ],
                description="Every <agent> is obligated to <action>",
                examples=["Every contractor is obligated to comply"]
            ),
            Pattern(
                name="any_agent_who",
                type=PatternType.UNIVERSAL_QUANTIFICATION,
                token_pattern=[
                    {"LOWER": "any"},
                    {"POS": "NOUN", "OP": "+"},
                    {"LOWER": "who"},
                    {"POS": "VERB"}
                ],
                description="Any <agent> who <verb>",
                examples=["Any contractor who violates", "Any employee who reports"]
            ),
            Pattern(
                name="all_of_the_agents",
                type=PatternType.UNIVERSAL_QUANTIFICATION,
                token_pattern=[
                    {"LOWER": "all"},
                    {"LOWER": "of"},
                    {"LOWER": "the"},
                    {"POS": "NOUN", "OP": "+"}
                ],
                description="All of the <agents>",
                examples=["All of the contractors", "All of the employees"]
            ),
            Pattern(
                name="for_all_agents",
                type=PatternType.UNIVERSAL_QUANTIFICATION,
                token_pattern=[
                    {"LOWER": "for"},
                    {"LOWER": "all"},
                    {"POS": "NOUN", "OP": "+"}
                ],
                description="For all <agents>",
                examples=["For all contractors", "For all employees"]
            ),
        ]
    
    def _create_obligation_patterns(self) -> List[Pattern]:
        """Create obligation patterns."""
        return [
            Pattern(
                name="agent_must_action",
                type=PatternType.OBLIGATION,
                token_pattern=[
                    {"POS": "NOUN", "OP": "+"},
                    {"LOWER": "must"},
                    {"POS": "VERB"}
                ],
                description="<agent> must <action>",
                examples=["Contractor must pay", "Employee must attend"]
            ),
            Pattern(
                name="agent_shall_action",
                type=PatternType.OBLIGATION,
                token_pattern=[
                    {"POS": "NOUN", "OP": "+"},
                    {"LOWER": "shall"},
                    {"POS": "VERB"}
                ],
                description="<agent> shall <action>",
                examples=["Contractor shall deliver", "Party shall perform"]
            ),
            Pattern(
                name="agent_is_required_to",
                type=PatternType.OBLIGATION,
                token_pattern=[
                    {"POS": "NOUN", "OP": "+"},
                    {"LOWER": "is"},
                    {"LOWER": "required"},
                    {"LOWER": "to"},
                    {"POS": "VERB"}
                ],
                description="<agent> is required to <action>",
                examples=["Contractor is required to submit"]
            ),
            Pattern(
                name="agent_is_obligated_to",
                type=PatternType.OBLIGATION,
                token_pattern=[
                    {"POS": "NOUN", "OP": "+"},
                    {"LOWER": "is"},
                    {"LOWER": "obligated"},
                    {"LOWER": "to"},
                    {"POS": "VERB"}
                ],
                description="<agent> is obligated to <action>",
                examples=["Contractor is obligated to comply"]
            ),
            Pattern(
                name="it_is_obligatory",
                type=PatternType.OBLIGATION,
                token_pattern=[
                    {"LOWER": "it"},
                    {"LOWER": "is"},
                    {"LOWER": "obligatory"},
                    {"LOWER": "that"}
                ],
                description="It is obligatory that...",
                examples=["It is obligatory that contractors pay"]
            ),
            Pattern(
                name="agent_has_obligation_to",
                type=PatternType.OBLIGATION,
                token_pattern=[
                    {"POS": "NOUN", "OP": "+"},
                    {"LOWER": {"IN": ["has", "have"]}},
                    {"LOWER": {"IN": ["an", "the"]}},
                    {"LOWER": "obligation"},
                    {"LOWER": "to"},
                    {"POS": "VERB"}
                ],
                description="<agent> has an obligation to <action>",
                examples=["Contractor has an obligation to deliver"]
            ),
            Pattern(
                name="agent_should_action",
                type=PatternType.OBLIGATION,
                token_pattern=[
                    {"POS": "NOUN", "OP": "+"},
                    {"LOWER": "should"},
                    {"POS": "VERB"}
                ],
                description="<agent> should <action>",
                examples=["Contractor should comply", "Employee should report"]
            ),
        ]
    
    def _create_permission_patterns(self) -> List[Pattern]:
        """Create permission patterns."""
        return [
            Pattern(
                name="agent_may_action",
                type=PatternType.PERMISSION,
                token_pattern=[
                    {"POS": "NOUN", "OP": "+"},
                    {"LOWER": "may"},
                    {"POS": "VERB"}
                ],
                description="<agent> may <action>",
                examples=["Contractor may submit", "Employee may request"]
            ),
            Pattern(
                name="agent_can_action",
                type=PatternType.PERMISSION,
                token_pattern=[
                    {"POS": "NOUN", "OP": "+"},
                    {"LOWER": "can"},
                    {"POS": "VERB"}
                ],
                description="<agent> can <action>",
                examples=["Contractor can apply", "Employee can file"]
            ),
            Pattern(
                name="agent_is_allowed_to",
                type=PatternType.PERMISSION,
                token_pattern=[
                    {"POS": "NOUN", "OP": "+"},
                    {"LOWER": "is"},
                    {"LOWER": "allowed"},
                    {"LOWER": "to"},
                    {"POS": "VERB"}
                ],
                description="<agent> is allowed to <action>",
                examples=["Contractor is allowed to bid"]
            ),
            Pattern(
                name="agent_is_permitted_to",
                type=PatternType.PERMISSION,
                token_pattern=[
                    {"POS": "NOUN", "OP": "+"},
                    {"LOWER": "is"},
                    {"LOWER": "permitted"},
                    {"LOWER": "to"},
                    {"POS": "VERB"}
                ],
                description="<agent> is permitted to <action>",
                examples=["Contractor is permitted to access"]
            ),
            Pattern(
                name="it_is_permitted",
                type=PatternType.PERMISSION,
                token_pattern=[
                    {"LOWER": "it"},
                    {"LOWER": "is"},
                    {"LOWER": "permitted"},
                    {"LOWER": "that"}
                ],
                description="It is permitted that...",
                examples=["It is permitted that contractors bid"]
            ),
            Pattern(
                name="agent_has_permission_to",
                type=PatternType.PERMISSION,
                token_pattern=[
                    {"POS": "NOUN", "OP": "+"},
                    {"LOWER": {"IN": ["has", "have"]}},
                    {"LOWER": "permission"},
                    {"LOWER": "to"},
                    {"POS": "VERB"}
                ],
                description="<agent> has permission to <action>",
                examples=["Contractor has permission to enter"]
            ),
            Pattern(
                name="agent_is_entitled_to",
                type=PatternType.PERMISSION,
                token_pattern=[
                    {"POS": "NOUN", "OP": "+"},
                    {"LOWER": "is"},
                    {"LOWER": "entitled"},
                    {"LOWER": "to"},
                    {"POS": "VERB"}
                ],
                description="<agent> is entitled to <action>",
                examples=["Employee is entitled to vacation"]
            ),
        ]
    
    def _create_prohibition_patterns(self) -> List[Pattern]:
        """Create prohibition patterns."""
        return [
            Pattern(
                name="agent_must_not_action",
                type=PatternType.PROHIBITION,
                token_pattern=[
                    {"POS": "NOUN", "OP": "+"},
                    {"LOWER": "must"},
                    {"LOWER": "not"},
                    {"POS": "VERB"}
                ],
                description="<agent> must not <action>",
                examples=["Contractor must not disclose", "Employee must not violate"]
            ),
            Pattern(
                name="agent_shall_not_action",
                type=PatternType.PROHIBITION,
                token_pattern=[
                    {"POS": "NOUN", "OP": "+"},
                    {"LOWER": "shall"},
                    {"LOWER": "not"},
                    {"POS": "VERB"}
                ],
                description="<agent> shall not <action>",
                examples=["Party shall not terminate", "Contractor shall not assign"]
            ),
            Pattern(
                name="agent_cannot_action",
                type=PatternType.PROHIBITION,
                token_pattern=[
                    {"POS": "NOUN", "OP": "+"},
                    {"LOWER": {"IN": ["cannot", "can't"]}},
                    {"POS": "VERB"}
                ],
                description="<agent> cannot <action>",
                examples=["Contractor cannot subcontract", "Employee cannot resign"]
            ),
            Pattern(
                name="agent_is_forbidden_to",
                type=PatternType.PROHIBITION,
                token_pattern=[
                    {"POS": "NOUN", "OP": "+"},
                    {"LOWER": "is"},
                    {"LOWER": "forbidden"},
                    {"LOWER": "to"},
                    {"POS": "VERB"}
                ],
                description="<agent> is forbidden to <action>",
                examples=["Contractor is forbidden to disclose"]
            ),
            Pattern(
                name="agent_is_prohibited_from",
                type=PatternType.PROHIBITION,
                token_pattern=[
                    {"POS": "NOUN", "OP": "+"},
                    {"LOWER": "is"},
                    {"LOWER": "prohibited"},
                    {"LOWER": "from"},
                    {"POS": "VERB", "OP": "?"}
                ],
                description="<agent> is prohibited from <action>",
                examples=["Contractor is prohibited from bidding"]
            ),
            Pattern(
                name="it_is_forbidden",
                type=PatternType.PROHIBITION,
                token_pattern=[
                    {"LOWER": "it"},
                    {"LOWER": "is"},
                    {"LOWER": "forbidden"},
                    {"LOWER": {"IN": ["to", "that"]}}
                ],
                description="It is forbidden to/that...",
                examples=["It is forbidden to disclose", "It is forbidden that contractors bid"]
            ),
        ]
    
    def _create_temporal_patterns(self) -> List[Pattern]:
        """Create temporal patterns."""
        return [
            Pattern(
                name="always_action",
                type=PatternType.TEMPORAL,
                token_pattern=[
                    {"LOWER": "always"},
                    {"POS": "VERB"}
                ],
                description="always <action>",
                examples=["always comply", "always submit"]
            ),
            Pattern(
                name="agent_must_always",
                type=PatternType.TEMPORAL,
                token_pattern=[
                    {"POS": "NOUN", "OP": "+"},
                    {"LOWER": {"IN": ["must", "shall"]}},
                    {"LOWER": "always"},
                    {"POS": "VERB"}
                ],
                description="<agent> must always <action>",
                examples=["Contractor must always comply"]
            ),
            Pattern(
                name="eventually_action",
                type=PatternType.TEMPORAL,
                token_pattern=[
                    {"LOWER": "eventually"},
                    {"POS": "VERB", "OP": "?"}
                ],
                description="eventually <action>",
                examples=["eventually complete", "eventually deliver"]
            ),
            Pattern(
                name="action_until_condition",
                type=PatternType.TEMPORAL,
                token_pattern=[
                    {"POS": "VERB"},
                    {"LOWER": "until"}
                ],
                description="<action> until <condition>",
                examples=["continue until completion", "work until finished"]
            ),
            Pattern(
                name="within_time_action",
                type=PatternType.TEMPORAL,
                text_pattern=r"within\s+\d+\s+(day|week|month|year)s?",
                description="within <time> <action>",
                examples=["within 30 days", "within 2 weeks"]
            ),
            Pattern(
                name="after_time_action",
                type=PatternType.TEMPORAL,
                text_pattern=r"after\s+\d+\s+(day|week|month|year)s?",
                description="after <time> <action>",
                examples=["after 10 days", "after 1 year"]
            ),
            Pattern(
                name="before_time_action",
                type=PatternType.TEMPORAL,
                text_pattern=r"before\s+\d+\s+(day|week|month|year)s?",
                description="before <time> <action>",
                examples=["before 5 days", "before 3 months"]
            ),
            Pattern(
                name="never_action",
                type=PatternType.TEMPORAL,
                token_pattern=[
                    {"LOWER": "never"},
                    {"POS": "VERB"}
                ],
                description="never <action>",
                examples=["never disclose", "never violate"]
            ),
            Pattern(
                name="immediately_action",
                type=PatternType.TEMPORAL,
                token_pattern=[
                    {"LOWER": "immediately"},
                    {"POS": "VERB"}
                ],
                description="immediately <action>",
                examples=["immediately notify", "immediately cease"]
            ),
            Pattern(
                name="from_time_to_time",
                type=PatternType.TEMPORAL,
                text_pattern=r"from\s+(time|day|week|month|year)\s+to\s+(time|day|week|month|year)",
                description="from <time> to <time>",
                examples=["from time to time", "from day to day"]
            ),
        ]
    
    def _create_conditional_patterns(self) -> List[Pattern]:
        """Create conditional patterns."""
        return [
            Pattern(
                name="if_condition_then",
                type=PatternType.CONDITIONAL,
                token_pattern=[
                    {"LOWER": "if"},
                    {},
                    {"LOWER": {"IN": ["then", ","]}},
                ],
                description="if <condition> then <consequence>",
                examples=["If paid, then deliver", "If completed, then approve"]
            ),
            Pattern(
                name="when_event_action",
                type=PatternType.CONDITIONAL,
                token_pattern=[
                    {"LOWER": "when"},
                    {"POS": "NOUN", "OP": "+"},
                    {"POS": "VERB"}
                ],
                description="when <event> <action>",
                examples=["When contract expires, notify", "When payment received, ship"]
            ),
            Pattern(
                name="provided_that",
                type=PatternType.CONDITIONAL,
                token_pattern=[
                    {"LOWER": "provided"},
                    {"LOWER": "that"}
                ],
                description="provided that <condition>",
                examples=["provided that payment made", "provided that work completed"]
            ),
            Pattern(
                name="unless_condition",
                type=PatternType.CONDITIONAL,
                token_pattern=[
                    {"LOWER": "unless"}
                ],
                description="unless <condition>",
                examples=["unless terminated", "unless notified"]
            ),
            Pattern(
                name="in_case_of",
                type=PatternType.CONDITIONAL,
                token_pattern=[
                    {"LOWER": "in"},
                    {"LOWER": "case"},
                    {"LOWER": "of"}
                ],
                description="in case of <event>",
                examples=["in case of breach", "in case of termination"]
            ),
        ]
    
    def _register_patterns(self) -> None:
        """Register all patterns with spaCy matcher."""
        for pattern in self.patterns:
            if pattern.token_pattern:
                try:
                    self.matcher.add(pattern.name, [pattern.token_pattern])
                except Exception as e:
                    logger.warning(f"Failed to register pattern {pattern.name}: {e}")
    
    def match(self, text: str, min_confidence: float = 0.5) -> List[PatternMatch]:
        """
        Match patterns against text.
        
        Args:
            text: Input text to match
            min_confidence: Minimum confidence threshold (0.0-1.0)
        
        Returns:
            List of PatternMatch objects sorted by confidence
        """
        doc = self.nlp(text)
        matches = []
        
        # Token-based matches (spaCy)
        spacy_matches = self.matcher(doc)
        for match_id, start, end in spacy_matches:
            pattern_name = self.nlp.vocab.strings[match_id]
            pattern = next((p for p in self.patterns if p.name == pattern_name), None)
            if pattern:
                span = doc[start:end]
                entities = self._extract_entities_from_span(span, pattern)
                confidence = self._calculate_confidence(span, pattern)
                
                if confidence >= min_confidence:
                    matches.append(PatternMatch(
                        pattern=pattern,
                        span=(span.start_char, span.end_char),
                        text=span.text,
                        entities=entities,
                        confidence=confidence,
                        spacy_span=span
                    ))
        
        # Text-based matches (regex)
        for pattern in self.patterns:
            if pattern.text_pattern:
                for regex_match in re.finditer(pattern.text_pattern, text, re.IGNORECASE):
                    confidence = 0.8  # Regex matches get slightly lower confidence
                    if confidence >= min_confidence:
                        matches.append(PatternMatch(
                            pattern=pattern,
                            span=(regex_match.start(), regex_match.end()),
                            text=regex_match.group(0),
                            entities={},
                            confidence=confidence
                        ))
        
        # Sort by confidence and remove duplicates
        matches.sort(key=lambda m: m.confidence, reverse=True)
        return self._deduplicate_matches(matches)
    
    def _extract_entities_from_span(self, span: Span, pattern: Pattern) -> Dict[str, str]:
        """Extract entities from matched span based on pattern type."""
        entities = {}
        
        tokens = list(span)
        
        # Extract agent (usually first noun/noun phrase)
        for token in tokens:
            if token.pos_ in ["NOUN", "PROPN"] and "agent" not in entities:
                entities["agent"] = token.text
                break
        
        # Extract action (usually verb)
        for token in tokens:
            if token.pos_ == "VERB":
                entities["action"] = token.lemma_
                break
        
        # Extract modality
        for token in tokens:
            if token.lower_ in ["must", "shall", "may", "can", "should"]:
                entities["modality"] = token.lower_
                break
        
        return entities
    
    def _calculate_confidence(self, span: Span, pattern: Pattern) -> float:
        """
        Calculate confidence score for a match.
        
        Factors:
        - Pattern specificity
        - Token match quality
        - Entity extraction success
        """
        confidence = 0.7  # Base confidence
        
        # Bonus for extracting entities
        tokens = list(span)
        if any(t.pos_ in ["NOUN", "PROPN"] for t in tokens):
            confidence += 0.1
        if any(t.pos_ == "VERB" for t in tokens):
            confidence += 0.1
        if any(t.lower_ in ["must", "shall", "may", "can"] for t in tokens):
            confidence += 0.1
        
        return min(confidence, 1.0)
    
    def _deduplicate_matches(self, matches: List[PatternMatch]) -> List[PatternMatch]:
        """Remove overlapping matches, keeping highest confidence."""
        if not matches:
            return []
        
        # Sort by confidence (already done) and span
        unique_matches = []
        used_spans = set()
        
        for match in matches:
            # Check if this span overlaps with any used span
            overlap = False
            for used_start, used_end in used_spans:
                if not (match.span[1] <= used_start or match.span[0] >= used_end):
                    overlap = True
                    break
            
            if not overlap:
                unique_matches.append(match)
                used_spans.add(match.span)
        
        return unique_matches
    
    def get_patterns_by_type(self, pattern_type: PatternType) -> List[Pattern]:
        """Get all patterns of a specific type."""
        return [p for p in self.patterns if p.type == pattern_type]
    
    def get_pattern_count(self) -> Dict[PatternType, int]:
        """Get count of patterns by type."""
        counts = {}
        for pattern_type in PatternType:
            counts[pattern_type] = len(self.get_patterns_by_type(pattern_type))
        return counts
