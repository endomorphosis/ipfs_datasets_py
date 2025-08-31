"""
Legal Domain Knowledge Module

This module provides a comprehensive knowledge base of legal concepts, patterns,
and domain-specific understanding required for extracting deontic logic formulas
from legal documents.
"""

import logging
import re
from typing import Dict, List, Optional, Set, Tuple, Pattern, Union, Any
from dataclasses import dataclass, field
from enum import Enum
import json

from .deontic_logic_core import DeonticOperator, LegalAgent, LegalContext

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LegalDomain(Enum):
    """Different domains of law."""
    CONTRACT = "contract"
    TORT = "tort"
    CRIMINAL = "criminal"
    CONSTITUTIONAL = "constitutional"
    CORPORATE = "corporate"
    EMPLOYMENT = "employment"
    INTELLECTUAL_PROPERTY = "intellectual_property"
    REAL_ESTATE = "real_estate"
    FAMILY = "family"
    TAX = "tax"
    IMMIGRATION = "immigration"
    ENVIRONMENTAL = "environmental"


class LegalConceptType(Enum):
    """Types of legal concepts."""
    OBLIGATION = "obligation"
    PERMISSION = "permission"
    PROHIBITION = "prohibition"
    RIGHT = "right"
    DUTY = "duty"
    LIABILITY = "liability"
    PENALTY = "penalty"
    CONDITION = "condition"
    EXCEPTION = "exception"
    DEFINITION = "definition"


@dataclass
class LegalPattern:
    """Represents a pattern for identifying legal concepts."""
    pattern: str                    # Regex pattern
    concept_type: LegalConceptType
    deontic_operator: DeonticOperator
    confidence: float = 1.0
    domain_specific: Optional[LegalDomain] = None
    description: str = ""
    examples: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        self.compiled_pattern = re.compile(self.pattern, re.IGNORECASE | re.MULTILINE)


@dataclass
class AgentPattern:
    """Pattern for identifying legal agents."""
    pattern: str
    agent_type: str  # "person", "organization", "role", "government"
    description: str = ""
    examples: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        self.compiled_pattern = re.compile(self.pattern, re.IGNORECASE)


class LegalDomainKnowledge:
    """
    Comprehensive knowledge base of legal concepts and patterns for 
    extracting deontic logic from legal documents.
    """
    
    def __init__(self):
        """Initialize the legal domain knowledge base."""
        self._initialize_obligation_patterns()
        self._initialize_permission_patterns()
        self._initialize_prohibition_patterns()
        self._initialize_agent_patterns()
        self._initialize_condition_patterns()
        self._initialize_temporal_patterns()
        self._initialize_legal_domains()
        self._initialize_modal_verbs()
        
    def _initialize_obligation_patterns(self):
        """Initialize patterns for identifying obligations."""
        self.obligation_patterns = [
            LegalPattern(
                pattern=r"\b(?:shall|must|is required to|is obligated to|has a duty to|is bound to)\b",
                concept_type=LegalConceptType.OBLIGATION,
                deontic_operator=DeonticOperator.OBLIGATION,
                confidence=0.95,
                description="Strong obligation indicators",
                examples=["The contractor shall complete", "Party must provide", "Tenant is required to pay"]
            ),
            LegalPattern(
                pattern=r"\b(?:will|agrees to|undertakes to|commits to|promises to)\b",
                concept_type=LegalConceptType.OBLIGATION,
                deontic_operator=DeonticOperator.OBLIGATION,
                confidence=0.85,
                description="Commitment-based obligations",
                examples=["The seller will deliver", "Buyer agrees to pay", "Party undertakes to perform"]
            ),
            LegalPattern(
                pattern=r"\b(?:responsible for|liable for|accountable for|in charge of)\b",
                concept_type=LegalConceptType.OBLIGATION,
                deontic_operator=DeonticOperator.OBLIGATION,
                confidence=0.80,
                description="Responsibility-based obligations",
                examples=["Company responsible for damages", "Tenant liable for repairs"]
            ),
            LegalPattern(
                pattern=r"\b(?:duty|obligation|responsibility|requirement)\s+(?:to|of)\b",
                concept_type=LegalConceptType.OBLIGATION,
                deontic_operator=DeonticOperator.OBLIGATION,
                confidence=0.90,
                description="Noun-based obligation expressions",
                examples=["duty to disclose", "obligation of care", "responsibility to maintain"]
            )
        ]
    
    def _initialize_permission_patterns(self):
        """Initialize patterns for identifying permissions."""
        self.permission_patterns = [
            LegalPattern(
                pattern=r"\b(?:may|can|is permitted to|is allowed to|is authorized to|has the right to)\b",
                concept_type=LegalConceptType.PERMISSION,
                deontic_operator=DeonticOperator.PERMISSION,
                confidence=0.95,
                description="Direct permission indicators",
                examples=["Tenant may terminate", "Party can inspect", "Buyer is permitted to examine"]
            ),
            LegalPattern(
                pattern=r"\b(?:entitled to|eligible for|qualified for|empowered to)\b",
                concept_type=LegalConceptType.PERMISSION,
                deontic_operator=DeonticOperator.PERMISSION,
                confidence=0.90,
                description="Entitlement-based permissions",
                examples=["Employee entitled to benefits", "Shareholder eligible for dividends"]
            ),
            LegalPattern(
                pattern=r"\b(?:right|privilege|liberty|freedom|discretion)\s+(?:to|of)\b",
                concept_type=LegalConceptType.PERMISSION,
                deontic_operator=DeonticOperator.PERMISSION,
                confidence=0.85,
                description="Rights-based permissions",
                examples=["right to privacy", "privilege of counsel", "freedom of speech"]
            ),
            LegalPattern(
                pattern=r"\b(?:option|choice|alternative)\s+(?:to|of)\b",
                concept_type=LegalConceptType.PERMISSION,
                deontic_operator=DeonticOperator.PERMISSION,
                confidence=0.75,
                description="Optional permissions",
                examples=["option to renew", "choice of law", "alternative of arbitration"]
            )
        ]
    
    def _initialize_prohibition_patterns(self):
        """Initialize patterns for identifying prohibitions."""
        self.prohibition_patterns = [
            LegalPattern(
                pattern=r"\b(?:shall not|must not|may not|cannot|is prohibited from|is forbidden to|is barred from)\b",
                concept_type=LegalConceptType.PROHIBITION,
                deontic_operator=DeonticOperator.PROHIBITION,
                confidence=0.95,
                description="Direct prohibition indicators",
                examples=["shall not disclose", "must not interfere", "may not assign"]
            ),
            LegalPattern(
                pattern=r"\b(?:prohibited|forbidden|banned|barred|restricted|prevented)\b",
                concept_type=LegalConceptType.PROHIBITION,
                deontic_operator=DeonticOperator.PROHIBITION,
                confidence=0.90,
                description="Prohibition adjectives/verbs",
                examples=["prohibited from entering", "forbidden to compete", "restricted from access"]
            ),
            LegalPattern(
                pattern=r"\b(?:unlawful|illegal|invalid|void|null and void|unenforceable)\b",
                concept_type=LegalConceptType.PROHIBITION,
                deontic_operator=DeonticOperator.PROHIBITION,
                confidence=0.85,
                description="Legal invalidity indicators",
                examples=["unlawful to discriminate", "illegal to interfere", "void if violated"]
            ),
            LegalPattern(
                pattern=r"\b(?:violation|breach|infringement|non-compliance)\s+(?:of|with)\b",
                concept_type=LegalConceptType.PROHIBITION,
                deontic_operator=DeonticOperator.PROHIBITION,
                confidence=0.80,
                description="Violation-based prohibitions",
                examples=["violation of privacy", "breach of contract", "infringement of rights"]
            )
        ]
    
    def _initialize_agent_patterns(self):
        """Initialize patterns for identifying legal agents."""
        self.agent_patterns = [
            AgentPattern(
                pattern=r"\b(?:party|parties|signatory|signatories|contracting party|contracting parties)\b",
                agent_type="party",
                description="General contract parties",
                examples=["the parties agree", "each party shall", "contracting parties"]
            ),
            AgentPattern(
                pattern=r"\b(?:buyer|purchaser|vendee|acquirer)\b",
                agent_type="person",
                description="Purchasing party in transactions",
                examples=["the buyer shall pay", "purchaser agrees to"]
            ),
            AgentPattern(
                pattern=r"\b(?:seller|vendor|grantor|transferor)\b",
                agent_type="person", 
                description="Selling party in transactions",
                examples=["the seller warrants", "vendor represents"]
            ),
            AgentPattern(
                pattern=r"\b(?:landlord|lessor|owner)\b",
                agent_type="person",
                description="Property owner/lessor",
                examples=["landlord shall maintain", "lessor agrees to"]
            ),
            AgentPattern(
                pattern=r"\b(?:tenant|lessee|renter|occupant)\b",
                agent_type="person",
                description="Property tenant/lessee",
                examples=["tenant must pay", "lessee shall not"]
            ),
            AgentPattern(
                pattern=r"\b(?:employer|company|corporation|business|enterprise)\b",
                agent_type="organization",
                description="Business entities",
                examples=["employer shall provide", "company agrees to"]
            ),
            AgentPattern(
                pattern=r"\b(?:employee|worker|staff|personnel)\b",
                agent_type="person",
                description="Workers/employees",
                examples=["employee must comply", "worker shall follow"]
            ),
            AgentPattern(
                pattern=r"\b(?:government|state|federal|municipal|county|city)\b",
                agent_type="government",
                description="Government entities",
                examples=["government shall ensure", "state must provide"]
            ),
            AgentPattern(
                pattern=r"\b(?:contractor|subcontractor|service provider)\b",
                agent_type="organization",
                description="Service contractors",
                examples=["contractor shall complete", "service provider must"]
            ),
            AgentPattern(
                pattern=r"\b(?:client|customer|consumer|beneficiary)\b",
                agent_type="person",
                description="Service recipients",
                examples=["client may request", "customer has right to"]
            )
        ]
    
    def _initialize_condition_patterns(self):
        """Initialize patterns for identifying conditions."""
        self.condition_patterns = [
            r"\b(?:if|when|where|unless|except|provided that|subject to|conditional upon)\b",
            r"\b(?:in the event|in case of|in the circumstance|under the condition)\b",
            r"\b(?:only if|if and only if|so long as|as long as)\b",
            r"\b(?:upon|after|before|during|within|by|no later than)\b"
        ]
        
        # Compile condition patterns
        self.compiled_condition_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.condition_patterns
        ]
    
    def _initialize_temporal_patterns(self):
        """Initialize patterns for identifying temporal expressions."""
        self.temporal_patterns = {
            "deadline": [
                r"\b(?:by|before|no later than|on or before|deadline of)\s+([^,\.]+)",
                r"\b(?:within|in)\s+(\d+\s+(?:days?|weeks?|months?|years?))",
                r"\b(?:expires?|terminates?|ends?)\s+(?:on|at|by)\s+([^,\.]+)"
            ],
            "duration": [
                r"\b(?:for\s+a\s+period\s+of|for)\s+(\d+\s+(?:days?|weeks?|months?|years?))",
                r"\b(?:during|throughout)\s+([^,\.]+)",
                r"\b(?:term\s+of)\s+(\d+\s+(?:days?|weeks?|months?|years?))"
            ],
            "start_time": [
                r"\b(?:commencing|beginning|starting|effective)\s+(?:on|from|as of)\s+([^,\.]+)",
                r"\b(?:from\s+and\s+after|on\s+and\s+after)\s+([^,\.]+)"
            ],
            "frequency": [
                r"\b(?:annually|yearly|monthly|weekly|daily|quarterly)",
                r"\b(?:every|each)\s+(\d+\s+(?:days?|weeks?|months?|years?))",
                r"\b(?:on\s+a\s+(?:regular|periodic|recurring)\s+basis)"
            ]
        }
        
        # Compile temporal patterns
        self.compiled_temporal_patterns = {}
        for category, patterns in self.temporal_patterns.items():
            self.compiled_temporal_patterns[category] = [
                re.compile(pattern, re.IGNORECASE) for pattern in patterns
            ]
    
    def _initialize_legal_domains(self):
        """Initialize domain-specific keywords."""
        self.domain_keywords = {
            LegalDomain.CONTRACT: [
                "agreement", "contract", "covenant", "undertaking", "warranty", "representation",
                "breach", "performance", "consideration", "offer", "acceptance", "terms"
            ],
            LegalDomain.TORT: [
                "negligence", "liability", "damages", "injury", "harm", "fault", "causation",
                "duty of care", "standard of care", "reasonable person"
            ],
            LegalDomain.CRIMINAL: [
                "crime", "offense", "prosecution", "defendant", "guilty", "innocent",
                "sentence", "penalty", "fine", "imprisonment", "probation"
            ],
            LegalDomain.EMPLOYMENT: [
                "employment", "employee", "employer", "wages", "benefits", "termination",
                "discrimination", "harassment", "workplace", "labor"
            ],
            LegalDomain.REAL_ESTATE: [
                "property", "real estate", "land", "deed", "title", "mortgage", "lease",
                "zoning", "easement", "covenant"
            ],
            LegalDomain.CORPORATE: [
                "corporation", "shareholder", "director", "officer", "board", "merger",
                "acquisition", "securities", "fiduciary", "governance"
            ]
        }
    
    def _initialize_modal_verbs(self):
        """Initialize modal verb patterns and their strengths."""
        self.modal_verbs = {
            # Strong obligation
            "shall": {"strength": 0.95, "type": "obligation"},
            "must": {"strength": 0.95, "type": "obligation"},
            "will": {"strength": 0.85, "type": "obligation"},
            
            # Permission
            "may": {"strength": 0.90, "type": "permission"},
            "can": {"strength": 0.85, "type": "permission"},
            "might": {"strength": 0.70, "type": "permission"},
            
            # Prohibition (when negated)
            "shall not": {"strength": 0.95, "type": "prohibition"},
            "must not": {"strength": 0.95, "type": "prohibition"},
            "may not": {"strength": 0.90, "type": "prohibition"},
            "cannot": {"strength": 0.90, "type": "prohibition"},
            
            # Conditional
            "should": {"strength": 0.75, "type": "recommendation"},
            "ought": {"strength": 0.70, "type": "recommendation"},
            "would": {"strength": 0.60, "type": "conditional"}
        }
    
    def classify_legal_statement(self, text: str) -> Tuple[DeonticOperator, float]:
        """
        Classify a legal statement and return the most likely deontic operator
        with confidence score.
        """
        text_clean = text.strip().lower()
        best_operator = None
        best_confidence = 0.0
        
        # Check prohibition patterns FIRST (must check negations before positive patterns)
        for pattern in self.prohibition_patterns:
            if pattern.compiled_pattern.search(text_clean):
                if pattern.confidence > best_confidence:
                    best_operator = pattern.deontic_operator
                    best_confidence = pattern.confidence
        
        # Check obligation patterns
        for pattern in self.obligation_patterns:
            if pattern.compiled_pattern.search(text_clean):
                if pattern.confidence > best_confidence:
                    best_operator = pattern.deontic_operator
                    best_confidence = pattern.confidence
        
        # Check permission patterns  
        for pattern in self.permission_patterns:
            if pattern.compiled_pattern.search(text_clean):
                if pattern.confidence > best_confidence:
                    best_operator = pattern.deontic_operator
                    best_confidence = pattern.confidence
        
        # Fallback to modal verb analysis
        if best_operator is None:
            for modal, info in self.modal_verbs.items():
                if modal in text_clean:
                    if info["strength"] > best_confidence:
                        if info["type"] == "obligation":
                            best_operator = DeonticOperator.OBLIGATION
                        elif info["type"] == "permission":
                            best_operator = DeonticOperator.PERMISSION
                        elif info["type"] == "prohibition":
                            best_operator = DeonticOperator.PROHIBITION
                        best_confidence = info["strength"]
        
        return best_operator or DeonticOperator.PERMISSION, best_confidence
    
    def extract_agents(self, text: str) -> List[Tuple[str, str, float]]:
        """
        Extract legal agents from text.
        Returns list of (agent_name, agent_type, confidence) tuples.
        """
        agents = []
        text_clean = text.lower()
        
        for pattern in self.agent_patterns:
            matches = pattern.compiled_pattern.finditer(text)
            for match in matches:
                agent_name = match.group(0)
                agent_type = pattern.agent_type
                confidence = 0.8  # Base confidence for pattern matching
                
                # Increase confidence if surrounded by appropriate context
                start_pos = max(0, match.start() - 20)
                end_pos = min(len(text), match.end() + 20)
                context = text[start_pos:end_pos].lower()
                
                if any(word in context for word in ["the", "such", "said", "aforementioned"]):
                    confidence += 0.1
                
                agents.append((agent_name, agent_type, confidence))
        
        return agents
    
    def extract_conditions(self, text: str) -> List[str]:
        """Extract conditional clauses from legal text."""
        conditions = []
        
        for pattern in self.compiled_condition_patterns:
            matches = pattern.finditer(text)
            for match in matches:
                # Extract the condition clause (next 50 characters as approximation)
                start = match.end()
                end = min(len(text), start + 100)
                condition_text = text[start:end].strip()
                
                # Find the end of the condition (usually a comma, period, or conjunction)
                end_markers = [',', '.', ';', ' and ', ' or ', ' but ']
                for marker in end_markers:
                    marker_pos = condition_text.find(marker)
                    if marker_pos != -1:
                        condition_text = condition_text[:marker_pos]
                        break
                
                if condition_text and len(condition_text) > 5:  # Minimum meaningful length
                    conditions.append(condition_text.strip())
        
        return list(set(conditions))  # Remove duplicates
    
    def extract_temporal_expressions(self, text: str) -> Dict[str, List[str]]:
        """Extract temporal expressions categorized by type."""
        temporal_expressions = {
            "deadline": [],
            "duration": [], 
            "start_time": [],
            "frequency": []
        }
        
        for category, patterns in self.compiled_temporal_patterns.items():
            for pattern in patterns:
                matches = pattern.finditer(text)
                for match in matches:
                    if match.groups():
                        # Extract captured group
                        temporal_expressions[category].append(match.group(1).strip())
                    else:
                        # Extract full match
                        temporal_expressions[category].append(match.group(0).strip())
        
        return temporal_expressions
    
    def identify_legal_domain(self, text: str) -> Tuple[LegalDomain, float]:
        """
        Identify the legal domain of the text based on keyword analysis.
        Returns (domain, confidence) tuple.
        """
        text_clean = text.lower()
        domain_scores = {}
        
        for domain, keywords in self.domain_keywords.items():
            score = 0
            keyword_count = 0
            for keyword in keywords:
                if keyword in text_clean:
                    # Count occurrences and weight by keyword importance
                    occurrences = text_clean.count(keyword)
                    score += occurrences * (1.0 / len(keywords))  # Normalize by total keywords
                    keyword_count += 1
            
            # Calculate confidence based on keyword density
            if keyword_count > 0:
                confidence = min(1.0, (keyword_count / len(keywords)) + (score * 0.1))
                domain_scores[domain] = confidence
        
        if domain_scores:
            best_domain = max(domain_scores.items(), key=lambda x: x[1])
            return best_domain
        else:
            return LegalDomain.CONTRACT, 0.1  # Default fallback
    
    def extract_legal_entities(self, text: str) -> List[Dict[str, Any]]:
        """
        Extract legal entities with their properties and relationships.
        Returns list of entity dictionaries.
        """
        entities = []
        
        # Extract agents first
        agents = self.extract_agents(text)
        for agent_name, agent_type, confidence in agents:
            entities.append({
                "name": agent_name,
                "type": "agent",
                "agent_type": agent_type,
                "confidence": confidence,
                "text_position": text.lower().find(agent_name.lower())
            })
        
        # Extract specific legal terms
        legal_terms = [
            "contract", "agreement", "obligation", "right", "duty", "liability",
            "warranty", "representation", "covenant", "condition", "term",
            "breach", "violation", "compliance", "performance", "consideration"
        ]
        
        for term in legal_terms:
            if term in text.lower():
                entities.append({
                    "name": term,
                    "type": "legal_concept",
                    "confidence": 0.7,
                    "text_position": text.lower().find(term)
                })
        
        return entities
    
    def validate_deontic_extraction(self, text: str, operator: DeonticOperator, 
                                  confidence: float) -> Dict[str, Any]:
        """
        Validate a deontic logic extraction against domain knowledge.
        Returns validation result with recommendations.
        """
        validation = {
            "is_valid": True,
            "confidence_adjustment": 0.0,
            "warnings": [],
            "recommendations": []
        }
        
        # Check for conflicting signals
        text_clean = text.lower()
        
        if operator == DeonticOperator.OBLIGATION:
            # Check for permission indicators that might conflict
            permission_indicators = ["may", "can", "optional", "discretionary"]
            for indicator in permission_indicators:
                if indicator in text_clean:
                    validation["warnings"].append(f"Found permission indicator '{indicator}' in obligation context")
                    validation["confidence_adjustment"] -= 0.1
        
        elif operator == DeonticOperator.PERMISSION:
            # Check for obligation indicators that might conflict
            obligation_indicators = ["shall", "must", "required", "mandatory"]
            for indicator in obligation_indicators:
                if indicator in text_clean:
                    validation["warnings"].append(f"Found obligation indicator '{indicator}' in permission context")
                    validation["confidence_adjustment"] -= 0.1
        
        # Check confidence threshold
        adjusted_confidence = confidence + validation["confidence_adjustment"]
        if adjusted_confidence < 0.5:
            validation["is_valid"] = False
            validation["recommendations"].append("Confidence too low - consider manual review")
        
        # Check for missing agent
        agents = self.extract_agents(text)
        if not agents:
            validation["warnings"].append("No clear legal agent identified")
            validation["recommendations"].append("Consider manual agent identification")
        
        return validation


def demonstrate_legal_knowledge():
    """Demonstrate the legal domain knowledge system."""
    knowledge = LegalDomainKnowledge()
    
    # Test sentences
    test_sentences = [
        "The contractor shall complete all work by December 31, 2024.",
        "The tenant may terminate this lease with 30 days notice.",
        "Employees must not disclose confidential information.",
        "The buyer has the right to inspect the property.",
        "The seller warrants that the goods are free from defects."
    ]
    
    print("=== Legal Domain Knowledge Demonstration ===\n")
    
    for i, sentence in enumerate(test_sentences, 1):
        print(f"Sentence {i}: {sentence}")
        
        # Classify deontic operator
        operator, confidence = knowledge.classify_legal_statement(sentence)
        print(f"  Deontic Operator: {operator.value if operator else 'None'} (confidence: {confidence:.2f})")
        
        # Extract agents
        agents = knowledge.extract_agents(sentence)
        print(f"  Agents: {agents}")
        
        # Extract conditions
        conditions = knowledge.extract_conditions(sentence)
        print(f"  Conditions: {conditions}")
        
        # Extract temporal expressions
        temporal = knowledge.extract_temporal_expressions(sentence)
        print(f"  Temporal: {temporal}")
        
        # Identify domain
        domain, domain_conf = knowledge.identify_legal_domain(sentence)
        print(f"  Legal Domain: {domain.value} (confidence: {domain_conf:.2f})")
        
        # Validate extraction
        if operator:
            validation = knowledge.validate_deontic_extraction(sentence, operator, confidence)
            print(f"  Validation: {validation}")
        
        print()


if __name__ == "__main__":
    demonstrate_legal_knowledge()