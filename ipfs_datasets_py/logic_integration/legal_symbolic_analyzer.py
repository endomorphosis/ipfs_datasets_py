"""
Legal SymbolicAI Analyzer Module

This module provides SymbolicAI-powered legal text analysis for enhanced
understanding of legal concepts, reasoning, and deontic logic extraction.
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import re

from .deontic_logic_core import DeonticOperator, LegalAgent, TemporalCondition
from .legal_domain_knowledge import LegalDomain

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Check for SymbolicAI availability
try:
    from ..utils.engine_env import autoconfigure_engine_env
    autoconfigure_engine_env()

    from ..utils.symai_config import choose_symai_neurosymbolic_engine, ensure_symai_config

    chosen_engine = choose_symai_neurosymbolic_engine()
    if chosen_engine:
        # If we're routing through Codex, force-refresh the venv config so a
        # previously written (and potentially unsupported) model string doesn't
        # stick around.
        force_config = bool(chosen_engine.get("model", "").startswith("codex:"))
        ensure_symai_config(
            neurosymbolic_model=chosen_engine["model"],
            neurosymbolic_api_key=chosen_engine["api_key"],
            force=force_config,
        )

    import symai
    from symai import Expression

    # If we are routing via Codex, register the custom engine before any queries.
    try:
        if chosen_engine and chosen_engine.get("model", "").startswith("codex:"):
            from symai.functional import EngineRepository

            from ipfs_datasets_py.utils.symai_codex_engine import CodexExecNeurosymbolicEngine

            EngineRepository.register(
                "neurosymbolic",
                CodexExecNeurosymbolicEngine(),
                allow_engine_override=True,
            )
    except Exception as e:
        logger.warning("Failed to register Codex-backed symai engine (%s)", e)

    SYMBOLIC_AI_AVAILABLE = True
    logger.info("SymbolicAI available for enhanced legal analysis")
except (ImportError, SystemExit):
    SYMBOLIC_AI_AVAILABLE = False
    logger.warning("SymbolicAI not available - using fallback legal analysis")


@dataclass
class LegalAnalysisResult:
    """Result of SymbolicAI-powered legal text analysis."""
    legal_domain: Optional[LegalDomain] = None
    primary_parties: List[str] = field(default_factory=list)
    legal_concepts: List[str] = field(default_factory=list)
    deontic_statements: List[Dict[str, Any]] = field(default_factory=list)
    temporal_expressions: List[str] = field(default_factory=list)
    conditions: List[str] = field(default_factory=list)
    confidence: float = 0.0
    reasoning: str = ""


@dataclass
class DeonticProposition:
    """A deontic proposition extracted by SymbolicAI."""
    operator: DeonticOperator
    agent: Optional[str] = None
    action: str = ""
    conditions: List[str] = field(default_factory=list)
    confidence: float = 0.0
    source_text: str = ""
    reasoning: str = ""


@dataclass
class LegalEntity:
    """A legal entity identified by SymbolicAI."""
    name: str
    entity_type: str  # "person", "organization", "government"
    role: str  # "contractor", "client", "party"
    confidence: float = 0.0
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TemporalCondition:
    """A temporal condition extracted by SymbolicAI."""
    condition_type: str  # "deadline", "duration", "start_date"
    temporal_expression: str
    normalized_date: Optional[str] = None
    confidence: float = 0.0


class LegalSymbolicAnalyzer:
    """SymbolicAI-powered legal text analysis for enhanced understanding."""
    
    def __init__(self):
        """Initialize the legal symbolic analyzer."""
        self.symbolic_ai_available = SYMBOLIC_AI_AVAILABLE
        
        if self.symbolic_ai_available:
            self._initialize_symbolic_ai()
        else:
            logger.info("Using fallback legal analysis (SymbolicAI not available)")
    
    def _initialize_symbolic_ai(self):
        """Initialize SymbolicAI components for legal analysis."""
        try:
            # Store prompt context strings; evaluation happens via `Expression.prompt(...)()`.
            self.legal_context_text = """
You are an expert legal analyst specializing in converting legal text into formal logic.
Your task is to identify:
1. Legal obligations (what parties MUST do)
2. Legal permissions (what parties MAY do)  
3. Legal prohibitions (what parties MUST NOT do)
4. Legal agents (who are the parties involved)
5. Temporal conditions (when things must happen)
6. Conditional requirements (under what circumstances)

Focus on precise identification of deontic concepts for formal logic conversion.
""".strip()

            self.entity_extractor_text = """
Extract all legal entities (parties, organizations, roles) from the given legal text.
Return a structured list with entity names, types, and roles.
""".strip()

            self.deontic_extractor_text = """
Identify all deontic statements (obligations, permissions, prohibitions) in the legal text.
For each statement, identify:
- The deontic operator (must/shall/may/must not/shall not)
- The agent (who has the obligation/permission/prohibition)
- The action or proposition
- Any conditions or temporal constraints
""".strip()
            
            logger.info("SymbolicAI legal analysis components initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize SymbolicAI: {e}")
            self.symbolic_ai_available = False
    
    def analyze_legal_document(self, text: str) -> LegalAnalysisResult:
        """
        Analyze a legal document using SymbolicAI for comprehensive understanding.
        
        Args:
            text: Legal document text
            
        Returns:
            Comprehensive analysis result
        """
        if not self.symbolic_ai_available:
            return self._fallback_analysis(text)
        
        try:
            # Use SymbolicAI for document analysis
            analysis_prompt = f"""
Analyze this legal document and provide:
1. Primary legal domain (contract, tort, criminal, etc.)
2. Main parties involved
3. Key legal concepts
4. All deontic statements (obligations, permissions, prohibitions)
5. Temporal expressions (deadlines, durations)
6. Conditional requirements

Document text:
{text}

Provide structured analysis with confidence scores.
"""
            
            # Get SymbolicAI analysis
            result = Expression.prompt(
                analysis_prompt,
                static_context=self.legal_context_text,
            )()
            
            # Parse the result (this would be more sophisticated in real implementation)
            return self._parse_symbolic_analysis(str(result), text)
            
        except Exception as e:
            logger.error(f"SymbolicAI analysis failed: {e}")
            return self._fallback_analysis(text)
    
    def extract_deontic_propositions(self, text: str) -> List[DeonticProposition]:
        """
        Extract deontic propositions using SymbolicAI reasoning.
        
        Args:
            text: Legal text to analyze
            
        Returns:
            List of identified deontic propositions
        """
        if not self.symbolic_ai_available:
            return self._fallback_deontic_extraction(text)
        
        try:
            # Use SymbolicAI for deontic extraction
            extraction_prompt = f"""
Extract all deontic statements from this legal text. For each statement, identify:
1. Deontic operator: obligation (must/shall), permission (may/can), prohibition (must not/shall not)
2. Agent: who has the obligation/permission/prohibition
3. Action: what must/may/must not be done
4. Conditions: any conditions or requirements

Text: {text}

Format as structured list with confidence scores.
"""
            
            result = Expression.prompt(
                extraction_prompt,
                static_context=f"{self.legal_context_text}\n\n{self.deontic_extractor_text}",
            )()
            
            return self._parse_deontic_propositions(str(result), text)
            
        except Exception as e:
            logger.error(f"SymbolicAI deontic extraction failed: {e}")
            return self._fallback_deontic_extraction(text)
    
    def identify_legal_entities(self, text: str) -> List[LegalEntity]:
        """
        Identify legal entities using SymbolicAI.
        
        Args:
            text: Legal text to analyze
            
        Returns:
            List of identified legal entities
        """
        if not self.symbolic_ai_available:
            return self._fallback_entity_identification(text)
        
        try:
            # Use SymbolicAI for entity identification
            entity_prompt = f"""
Identify all legal entities in this text including:
1. Parties to agreements (individuals, organizations)
2. Government entities
3. Roles and positions
4. Legal concepts and objects

Text: {text}

Provide entity names, types (person/organization/government), and roles with confidence scores.
"""
            
            result = Expression.prompt(
                entity_prompt,
                static_context=f"{self.legal_context_text}\n\n{self.entity_extractor_text}",
            )()
            
            return self._parse_legal_entities(str(result))
            
        except Exception as e:
            logger.error(f"SymbolicAI entity identification failed: {e}")
            return self._fallback_entity_identification(text)
    
    def extract_temporal_conditions(self, text: str) -> List[TemporalCondition]:
        """
        Extract temporal conditions using SymbolicAI.
        
        Args:
            text: Legal text to analyze
            
        Returns:
            List of temporal conditions
        """
        if not self.symbolic_ai_available:
            return self._fallback_temporal_extraction(text)
        
        try:
            # Enhanced temporal analysis with SymbolicAI
            temporal_prompt = f"""
Extract all temporal expressions and conditions from this legal text:
1. Deadlines (by when something must happen)
2. Durations (how long something lasts)
3. Start dates (when something begins)
4. Conditional timing (when certain conditions trigger actions)

Text: {text}

Provide structured temporal information with normalized dates where possible.
"""
            
            result = Expression.prompt(
                temporal_prompt,
                static_context=self.legal_context_text,
            )()
            
            return self._parse_temporal_conditions(str(result))
            
        except Exception as e:
            logger.error(f"SymbolicAI temporal extraction failed: {e}")
            return self._fallback_temporal_extraction(text)
    
    def _fallback_analysis(self, text: str) -> LegalAnalysisResult:
        """Fallback analysis when SymbolicAI is not available."""
        # Basic pattern-based analysis
        legal_concepts = []
        if "contract" in text.lower():
            legal_concepts.append("contract")
        if "agreement" in text.lower():
            legal_concepts.append("agreement")
        if "obligation" in text.lower():
            legal_concepts.append("obligation")
        
        # Basic party identification
        parties = []
        if "contractor" in text.lower():
            parties.append("contractor")
        if "client" in text.lower():
            parties.append("client")
        
        return LegalAnalysisResult(
            legal_domain=LegalDomain.CONTRACT,
            primary_parties=parties,
            legal_concepts=legal_concepts,
            confidence=0.5,
            reasoning="Fallback analysis using basic pattern matching"
        )
    
    def _fallback_deontic_extraction(self, text: str) -> List[DeonticProposition]:
        """Fallback deontic extraction using pattern matching."""
        propositions = []
        
        # Simple pattern-based extraction
        sentences = re.split(r'[.!?]+', text)
        
        for sentence in sentences:
            sentence = sentence.strip().lower()
            if not sentence:
                continue
            
            # Check for obligations
            if any(word in sentence for word in ["shall", "must", "required", "obligated"]):
                if "not" not in sentence:  # Avoid prohibitions
                    propositions.append(DeonticProposition(
                        operator=DeonticOperator.OBLIGATION,
                        action=sentence[:50],
                        confidence=0.6,
                        source_text=sentence,
                        reasoning="Pattern matching: obligation keywords found"
                    ))
            
            # Check for permissions  
            elif any(word in sentence for word in ["may", "can", "allowed", "permitted"]):
                propositions.append(DeonticProposition(
                    operator=DeonticOperator.PERMISSION,
                    action=sentence[:50],
                    confidence=0.6,
                    source_text=sentence,
                    reasoning="Pattern matching: permission keywords found"
                ))
            
            # Check for prohibitions
            elif any(phrase in sentence for phrase in ["must not", "shall not", "prohibited", "forbidden"]):
                propositions.append(DeonticProposition(
                    operator=DeonticOperator.PROHIBITION,
                    action=sentence[:50],
                    confidence=0.6,
                    source_text=sentence,
                    reasoning="Pattern matching: prohibition keywords found"
                ))
        
        return propositions
    
    def _fallback_entity_identification(self, text: str) -> List[LegalEntity]:
        """Fallback entity identification using pattern matching."""
        entities = []
        
        # Simple entity patterns
        entity_patterns = {
            "contractor": ("organization", "contractor"),
            "client": ("organization", "client"),
            "company": ("organization", "party"),
            "corporation": ("organization", "party"),
            "government": ("government", "authority"),
            "state": ("government", "authority"),
            "party": ("unknown", "party")
        }
        
        text_lower = text.lower()
        for pattern, (entity_type, role) in entity_patterns.items():
            if pattern in text_lower:
                entities.append(LegalEntity(
                    name=pattern.title(),
                    entity_type=entity_type,
                    role=role,
                    confidence=0.5
                ))
        
        return entities
    
    def _fallback_temporal_extraction(self, text: str) -> List[TemporalCondition]:
        """Fallback temporal extraction using pattern matching."""
        conditions = []
        
        # Basic temporal patterns
        deadline_patterns = [
            r'by\s+([^,\.]+)',
            r'before\s+([^,\.]+)',
            r'no\s+later\s+than\s+([^,\.]+)'
        ]
        
        for pattern in deadline_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                conditions.append(TemporalCondition(
                    condition_type="deadline",
                    temporal_expression=match.group(1),
                    confidence=0.6
                ))
        
        return conditions
    
    def _parse_symbolic_analysis(self, analysis_text: str, original_text: str) -> LegalAnalysisResult:
        """Parse SymbolicAI analysis result into structured format."""
        # This is a simplified parser - in real implementation would be more sophisticated
        return LegalAnalysisResult(
            legal_domain=LegalDomain.CONTRACT,
            primary_parties=["contractor", "client"],
            legal_concepts=["obligation", "permission", "contract"],
            confidence=0.8,
            reasoning=f"SymbolicAI analysis: {analysis_text[:100]}..."
        )
    
    def _parse_deontic_propositions(self, analysis_text: str, original_text: str) -> List[DeonticProposition]:
        """Parse SymbolicAI deontic analysis into structured propositions."""
        # Simplified parser - would be more sophisticated with real SymbolicAI integration
        return self._fallback_deontic_extraction(original_text)
    
    def _parse_legal_entities(self, analysis_text: str) -> List[LegalEntity]:
        """Parse SymbolicAI entity analysis into structured entities."""
        # Simplified parser - would be more sophisticated with real SymbolicAI integration
        return self._fallback_entity_identification(analysis_text)
    
    def _parse_temporal_conditions(self, analysis_text: str) -> List[TemporalCondition]:
        """Parse SymbolicAI temporal analysis into structured conditions."""
        # Simplified parser - would be more sophisticated with real SymbolicAI integration
        return self._fallback_temporal_extraction(analysis_text)


class LegalReasoningEngine:
    """Advanced legal reasoning using SymbolicAI for complex inferences."""
    
    def __init__(self, analyzer: Optional[LegalSymbolicAnalyzer] = None):
        """Initialize legal reasoning engine."""
        self.analyzer = analyzer or LegalSymbolicAnalyzer()
        self.symbolic_ai_available = SYMBOLIC_AI_AVAILABLE
        
        if self.symbolic_ai_available:
            self._initialize_reasoning_components()
    
    def _initialize_reasoning_components(self):
        """Initialize SymbolicAI reasoning components."""
        try:
            self.consistency_checker = Symbol("""
You are a legal logic consistency checker. Analyze sets of legal rules for:
1. Logical contradictions (obligations vs prohibitions)
2. Circular dependencies
3. Impossible conditions
4. Conflicting temporal requirements

Provide detailed consistency analysis with confidence scores.
""")
            
            self.implication_reasoner = Symbol("""
You are a legal implication reasoner. Given a set of explicit legal rules,
identify implicit obligations, permissions, and prohibitions that follow
from the explicit rules through legal reasoning.

Focus on standard legal inferences and well-established legal principles.
""")
            
            logger.info("SymbolicAI legal reasoning components initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize SymbolicAI reasoning: {e}")
            self.symbolic_ai_available = False
    
    def infer_implicit_obligations(self, explicit_rules: List[str]) -> List[DeonticProposition]:
        """
        Infer implicit legal obligations from explicit rules.
        
        Args:
            explicit_rules: List of explicit legal rule texts
            
        Returns:
            List of inferred implicit obligations
        """
        if not self.symbolic_ai_available:
            return self._fallback_implication_reasoning(explicit_rules)
        
        try:
            # Use SymbolicAI for advanced reasoning
            reasoning_prompt = f"""
Given these explicit legal rules:
{chr(10).join(f"{i+1}. {rule}" for i, rule in enumerate(explicit_rules))}

Identify implicit obligations that follow from these explicit rules.
Consider standard legal principles like:
- Duty of good faith
- Reasonable care standards
- Notification requirements
- Compliance obligations
"""
            
            reasoning_symbol = Symbol(reasoning_prompt)
            result = self.implication_reasoner(reasoning_symbol)
            
            return self._parse_implicit_obligations(str(result))
            
        except Exception as e:
            logger.error(f"SymbolicAI implication reasoning failed: {e}")
            return self._fallback_implication_reasoning(explicit_rules)
    
    def check_legal_consistency(self, rules: List[str]) -> Dict[str, Any]:
        """
        Check logical consistency of legal rules.
        
        Args:
            rules: List of legal rule texts
            
        Returns:
            Consistency analysis report
        """
        if not self.symbolic_ai_available:
            return self._fallback_consistency_check(rules)
        
        try:
            # Use SymbolicAI for consistency checking
            consistency_prompt = f"""
Check these legal rules for logical consistency:
{chr(10).join(f"{i+1}. {rule}" for i, rule in enumerate(rules))}

Identify:
1. Direct contradictions (must do X vs must not do X)
2. Circular dependencies
3. Impossible conditions
4. Temporal conflicts

Provide detailed analysis with confidence scores.
"""
            
            consistency_symbol = Symbol(consistency_prompt)
            result = self.consistency_checker(consistency_symbol)
            
            return self._parse_consistency_result(str(result))
            
        except Exception as e:
            logger.error(f"SymbolicAI consistency checking failed: {e}")
            return self._fallback_consistency_check(rules)
    
    def analyze_legal_precedents(self, current_case: str, precedents: List[str]) -> Dict[str, Any]:
        """
        Analyze how legal precedents apply to the current case.
        
        Args:
            current_case: Current case text
            precedents: List of relevant precedent texts
            
        Returns:
            Precedent analysis with applicability scores
        """
        if not self.symbolic_ai_available:
            return self._fallback_precedent_analysis(current_case, precedents)
        
        # Simplified implementation for now
        return {
            "applicable_precedents": [],
            "reasoning": "Precedent analysis requires advanced SymbolicAI integration",
            "confidence": 0.0
        }
    
    def _fallback_implication_reasoning(self, explicit_rules: List[str]) -> List[DeonticProposition]:
        """Fallback implication reasoning using basic patterns."""
        implications = []
        
        # Basic implication patterns
        if any("contract" in rule.lower() for rule in explicit_rules):
            implications.append(DeonticProposition(
                operator=DeonticOperator.OBLIGATION,
                action="act_in_good_faith",
                confidence=0.5,
                reasoning="Implicit good faith obligation in contracts"
            ))
        
        return implications
    
    def _fallback_consistency_check(self, rules: List[str]) -> Dict[str, Any]:
        """Fallback consistency checking using basic pattern matching."""
        issues = []
        
        # Check for obvious contradictions
        obligations = [rule for rule in rules if any(word in rule.lower() for word in ["shall", "must"])]
        prohibitions = [rule for rule in rules if any(phrase in rule.lower() for phrase in ["shall not", "must not"])]
        
        # Very basic contradiction detection
        for obligation in obligations:
            for prohibition in prohibitions:
                if len(set(obligation.split()) & set(prohibition.split())) > 3:
                    issues.append(f"Potential contradiction between: {obligation[:50]}... and {prohibition[:50]}...")
        
        return {
            "is_consistent": len(issues) == 0,
            "issues": issues,
            "confidence": 0.6,
            "method": "Basic pattern matching"
        }
    
    def _fallback_precedent_analysis(self, current_case: str, precedents: List[str]) -> Dict[str, Any]:
        """Fallback precedent analysis."""
        return {
            "applicable_precedents": [],
            "reasoning": "Precedent analysis requires SymbolicAI integration",
            "confidence": 0.0
        }
    
    def _parse_implicit_obligations(self, analysis_text: str) -> List[DeonticProposition]:
        """Parse implicit obligations from SymbolicAI analysis."""
        # Simplified parser - in practice would use more sophisticated NLP
        return []
    
    def _parse_consistency_result(self, result_text: str) -> Dict[str, Any]:
        """Parse consistency analysis from SymbolicAI."""
        # Simplified parser - in practice would use structured output
        return {
            "is_consistent": "consistent" in result_text.lower(),
            "confidence": 0.8,
            "analysis": result_text[:200],
            "method": "SymbolicAI analysis"
        }


# Convenience functions
def create_legal_analyzer() -> LegalSymbolicAnalyzer:
    """Create a legal symbolic analyzer with default configuration."""
    return LegalSymbolicAnalyzer()


def create_legal_reasoning_engine() -> LegalReasoningEngine:
    """Create a legal reasoning engine with default configuration."""
    return LegalReasoningEngine()