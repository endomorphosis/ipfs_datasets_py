#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Temporal Deontic Caselaw Processor

This module integrates multiple case law precedents and automatically converts them
into domain-specific first-order temporal deontic logic, creating chronologically 
consistent theorems across entire case lineages. It leverages existing tools from
the ipfs_datasets_py package for logic integration and proof generation.

Based on research in temporal deontic logic and legal reasoning systems.
"""

import os
import json
import logging
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass, field
from datetime import datetime, date
from collections import defaultdict, OrderedDict
import re

# Import existing logic integration tools
try:
    from .logic_integration.deontic_logic_core import (
        DeonticFormula, DeonticOperator, LegalAgent, LegalContext,
        TemporalCondition, TemporalOperator, DeonticRuleSet,
        create_obligation, create_permission, create_prohibition
    )
    from .logic_integration.deontic_logic_converter import DeonticLogicConverter
    from .logic_integration.legal_domain_knowledge import LegalDomainKnowledge, LegalDomain
    from .logic_integration.proof_execution_engine import ProofExecutionEngine, ProofResult
    from .logic_integration.modal_logic_extension import ModalFormula, ModalLogicExtension
    LOGIC_INTEGRATION_AVAILABLE = True
except ImportError as e:
    logging.warning(f"Logic integration modules not fully available: {e}")
    LOGIC_INTEGRATION_AVAILABLE = False
    
    # Create fallback classes
    class DeonticFormula: pass
    class DeonticOperator: pass
    class LegalAgent: pass
    class LegalContext: pass
    class TemporalCondition: pass
    class TemporalOperator: pass
    class DeonticRuleSet: pass
    class DeonticLogicConverter: pass
    class LegalDomainKnowledge: pass
    class LegalDomain: pass
    class ProofExecutionEngine: pass
    class ProofResult: pass
    class ModalFormula: pass
    class ModalLogicExtension: pass

try:
    from .deontological_reasoning import DeontologicalReasoningEngine, DeonticStatement, DeonticModality
    DEONTO_REASONING_AVAILABLE = True
except ImportError as e:
    logging.warning(f"Deontological reasoning module not available: {e}")
    DEONTO_REASONING_AVAILABLE = False
    
    # Create fallback classes
    class DeontologicalReasoningEngine: pass
    class DeonticStatement:
        def __init__(self):
            self.entity = ""
            self.action = ""
            self.modality = None
            self.confidence = 0.0
    class DeonticModality:
        OBLIGATION = "obligation"
        PERMISSION = "permission" 
        PROHIBITION = "prohibition"
        CONDITIONAL = "conditional"
        EXCEPTION = "exception"

# Import caselaw processing tools
try:
    from .caselaw_graphrag import CaselawGraphRAGProcessor, LegalCitationParser
    from .caselaw_dataset import CaselawDatasetLoader
    CASELAW_TOOLS_AVAILABLE = True
except ImportError as e:
    logging.warning(f"Caselaw processing tools not available: {e}")
    CASELAW_TOOLS_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class TemporalLegalPrecedent:
    """Represents a legal precedent with temporal and logical constraints."""
    case_id: str
    case_name: str
    citation: str
    date_decided: datetime
    court: str
    legal_principles: List[str]
    deontic_statements: List[DeonticStatement]
    temporal_conditions: List[str]
    precedent_relationships: List[str]  # Cases this relies on
    superseded_by: Optional[str] = None  # If overruled
    domain: Optional[str] = None
    confidence: float = 1.0
    
    
@dataclass
class TemporalDeonticTheorem:
    """Represents a formal theorem derived from case lineage."""
    theorem_id: str
    name: str
    formal_statement: str  # First-order logic representation
    natural_language: str
    supporting_cases: List[str]
    temporal_constraints: List[str]
    consistency_proof: Optional[str] = None
    domain: Optional[str] = None
    creation_date: datetime = field(default_factory=datetime.now)
    

class TemporalDeonticCaselawProcessor:
    """
    Main processor for converting caselaw precedents into temporal deontic logic
    with chronologically consistent theorems.
    """
    
    def __init__(self, 
                 use_existing_tools: bool = True,
                 proof_engine: Optional[ProofExecutionEngine] = None):
        """Initialize the processor with existing ipfs_datasets_py tools."""
        
        # Initialize existing tools if available
        self.use_existing_tools = use_existing_tools and LOGIC_INTEGRATION_AVAILABLE
        
        if self.use_existing_tools:
            try:
                self.deontic_converter = DeonticLogicConverter()
                self.legal_knowledge = LegalDomainKnowledge()
                self.modal_logic = ModalLogicExtension()
                self.proof_engine = proof_engine or ProofExecutionEngine()
            except Exception as e:
                logger.warning(f"Could not initialize logic integration tools: {e}")
                self.use_existing_tools = False
                
        if DEONTO_REASONING_AVAILABLE:
            try:
                self.deonto_reasoning = DeontologicalReasoningEngine()
            except Exception as e:
                logger.warning(f"Could not initialize deontological reasoning: {e}")
                self.deonto_reasoning = None
        else:
            logger.warning("Using basic implementation without full deontological reasoning")
            self.deonto_reasoning = None
            
        if not self.use_existing_tools:
            logger.warning("Using basic implementation without full logic integration")
            
        # Initialize caselaw processing tools
        if CASELAW_TOOLS_AVAILABLE:
            self.caselaw_processor = CaselawGraphRAGProcessor()
            self.citation_parser = LegalCitationParser()
        
        # Storage for processed precedents and theorems
        self.precedents: Dict[str, TemporalLegalPrecedent] = {}
        self.theorems: Dict[str, TemporalDeonticTheorem] = {}
        self.precedent_graph: Dict[str, List[str]] = defaultdict(list)
        
        # Initialize legal domain patterns for temporal deontic logic
        self._initialize_temporal_patterns()
    
    def _initialize_temporal_patterns(self):
        """Initialize patterns for extracting temporal legal concepts."""
        self.temporal_patterns = {
            'before': [
                r'before\s+(.+?),\s*(.+?\s+(?:must|shall|may not|cannot))',
                r'prior to\s+(.+?),\s*(.+?\s+(?:must|shall|may not|cannot))',
                r'until\s+(.+?),\s*(.+?\s+(?:must|shall|may not|cannot))'
            ],
            'after': [
                r'after\s+(.+?),\s*(.+?\s+(?:must|shall|may not|cannot))',
                r'following\s+(.+?),\s*(.+?\s+(?:must|shall|may not|cannot))',
                r'subsequent to\s+(.+?),\s*(.+?\s+(?:must|shall|may not|cannot))'
            ],
            'during': [
                r'during\s+(.+?),\s*(.+?\s+(?:must|shall|may not|cannot))',
                r'while\s+(.+?),\s*(.+?\s+(?:must|shall|may not|cannot))',
                r'throughout\s+(.+?),\s*(.+?\s+(?:must|shall|may not|cannot))'
            ],
            'conditional': [
                r'if\s+(.+?),\s*then\s+(.+?\s+(?:must|shall|may not|cannot))',
                r'when\s+(.+?),\s*(.+?\s+(?:must|shall|may not|cannot))',
                r'provided that\s+(.+?),\s*(.+?\s+(?:must|shall|may not|cannot))'
            ]
        }
    
    async def process_caselaw_lineage(self, 
                                    cases: List[Dict[str, Any]], 
                                    doctrine_name: str) -> Dict[str, Any]:
        """
        Process multiple caselaw precedents for a specific legal doctrine
        and generate temporal deontic logic theorems.
        """
        logger.info(f"Processing caselaw lineage for doctrine: {doctrine_name}")
        
        try:
            # Step 1: Parse and extract deontic statements from each case
            precedents = []
            for case_data in cases:
                precedent = await self._process_single_case(case_data)
                if precedent:
                    precedents.append(precedent)
                    self.precedents[precedent.case_id] = precedent
            
            # Step 2: Sort precedents chronologically
            precedents.sort(key=lambda p: p.date_decided)
            
            # Step 3: Build precedent relationships graph
            await self._build_precedent_graph(precedents)
            
            # Step 4: Extract temporal deontic patterns across the lineage
            temporal_patterns = await self._extract_temporal_patterns(precedents, doctrine_name)
            
            # Step 5: Generate formal temporal deontic logic theorems
            theorems = await self._generate_theorems(precedents, temporal_patterns, doctrine_name)
            
            # Step 6: Verify chronological consistency
            consistency_results = await self._verify_chronological_consistency(theorems, precedents)
            
            # Step 7: Generate proof obligations and verify with theorem provers
            proof_results = []
            if self.use_existing_tools:
                proof_results = await self._execute_consistency_proofs(theorems)
            
            return {
                "doctrine": doctrine_name,
                "processed_cases": len(precedents),
                "precedents": [self._format_precedent(p) for p in precedents],
                "temporal_patterns": temporal_patterns,
                "generated_theorems": [self._format_theorem(t) for t in theorems],
                "consistency_analysis": consistency_results,
                "proof_results": proof_results,
                "precedent_graph": dict(self.precedent_graph),
                "processing_timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error processing caselaw lineage: {e}")
            return {
                "error": str(e),
                "doctrine": doctrine_name,
                "processing_timestamp": datetime.now().isoformat()
            }
    
    async def _process_single_case(self, case_data: Dict[str, Any]) -> Optional[TemporalLegalPrecedent]:
        """Process a single case into temporal deontic logic representation."""
        try:
            case_id = case_data.get('id', case_data.get('case_id', 'unknown'))
            case_name = case_data.get('name', case_data.get('case_name', 'Unknown Case'))
            content = case_data.get('content', case_data.get('full_text', ''))
            
            # Parse date
            date_str = case_data.get('date_decided', case_data.get('date', ''))
            try:
                date_decided = datetime.fromisoformat(date_str) if date_str else datetime.now()
            except:
                # Try various date parsing approaches
                date_decided = self._parse_case_date(date_str)
            
            # Extract citation information
            citation = case_data.get('citation', '')
            court = case_data.get('court', '')
            
            # Extract deontic statements using existing tools
            deontic_statements = []
            if self.deonto_reasoning and content:
                try:
                    # Use the existing deontological reasoning engine
                    documents = [{'id': case_id, 'content': content}]
                    analysis_result = await self.deonto_reasoning.analyze_corpus_for_deontic_conflicts(documents)
                    
                    # Extract statements from the analysis
                    deontic_statements = list(self.deonto_reasoning.statement_database.values())
                except Exception as e:
                    logger.warning(f"Could not extract deontic statements: {e}")
                    # Fallback to basic pattern matching
                    deontic_statements = self._extract_basic_deontic_statements(content, case_id)
            else:
                # Use basic pattern matching fallback
                deontic_statements = self._extract_basic_deontic_statements(content, case_id)
            
            # Extract legal principles and temporal conditions
            legal_principles = self._extract_legal_principles(content, case_name)
            temporal_conditions = self._extract_temporal_conditions(content)
            precedent_relationships = self._extract_precedent_relationships(content)
            
            # Determine legal domain
            domain = self._classify_legal_domain(content, case_name)
            
            return TemporalLegalPrecedent(
                case_id=case_id,
                case_name=case_name,
                citation=citation,
                date_decided=date_decided,
                court=court,
                legal_principles=legal_principles,
                deontic_statements=deontic_statements,
                temporal_conditions=temporal_conditions,
                precedent_relationships=precedent_relationships,
                domain=domain,
                confidence=0.8
            )
            
        except Exception as e:
            logger.error(f"Error processing case {case_data.get('id', 'unknown')}: {e}")
            return None
    
    def _extract_basic_deontic_statements(self, content: str, case_id: str) -> List[DeonticStatement]:
        """Fallback method to extract basic deontic statements using pattern matching."""
        statements = []
        
        # Basic patterns for legal obligations, permissions, and prohibitions
        obligation_patterns = [
            r'(\w+(?:\s+\w+)*)\s+(?:must|shall|are required to|have to|need to|are obligated to)\s+([^.!?]+)',
            r'(\w+(?:\s+\w+)*)\s+(?:has a duty to|has an obligation to|is responsible for)\s+([^.!?]+)',
        ]
        
        permission_patterns = [
            r'(\w+(?:\s+\w+)*)\s+(?:may|can|are allowed to|are permitted to|have the right to)\s+([^.!?]+)',
            r'(\w+(?:\s+\w+)*)\s+(?:is|are) (?:allowed|permitted|authorized) to\s+([^.!?]+)',
        ]
        
        prohibition_patterns = [
            r'(\w+(?:\s+\w+)*)\s+(?:must not|cannot|shall not|are not allowed to|are forbidden to|are prohibited from)\s+([^.!?]+)',
            r'(\w+(?:\s+\w+)*)\s+(?:is|are) (?:forbidden|prohibited|banned) (?:from|to)\s+([^.!?]+)',
        ]
        
        statement_counter = 0
        
        # Extract obligations
        for pattern in obligation_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                try:
                    entity = match.group(1).strip()
                    action = match.group(2).strip()
                    
                    if len(entity) > 2 and len(action) > 3:
                        statement_counter += 1
                        stmt = DeonticStatement()
                        stmt.id = f"stmt_{statement_counter}"
                        stmt.entity = entity
                        stmt.action = action
                        stmt.modality = DeonticModality.OBLIGATION
                        stmt.confidence = 0.7
                        statements.append(stmt)
                        
                except (IndexError, AttributeError):
                    continue
        
        # Extract permissions
        for pattern in permission_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                try:
                    entity = match.group(1).strip()
                    action = match.group(2).strip()
                    
                    if len(entity) > 2 and len(action) > 3:
                        statement_counter += 1
                        stmt = DeonticStatement()
                        stmt.id = f"stmt_{statement_counter}"
                        stmt.entity = entity
                        stmt.action = action
                        stmt.modality = DeonticModality.PERMISSION
                        stmt.confidence = 0.7
                        statements.append(stmt)
                        
                except (IndexError, AttributeError):
                    continue
        
        # Extract prohibitions
        for pattern in prohibition_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                try:
                    entity = match.group(1).strip()
                    action = match.group(2).strip()
                    
                    if len(entity) > 2 and len(action) > 3:
                        statement_counter += 1
                        stmt = DeonticStatement()
                        stmt.id = f"stmt_{statement_counter}"
                        stmt.entity = entity
                        stmt.action = action
                        stmt.modality = DeonticModality.PROHIBITION
                        stmt.confidence = 0.7
                        statements.append(stmt)
                        
                except (IndexError, AttributeError):
                    continue
        
        return statements

    def _parse_case_date(self, date_str: str) -> datetime:
        """Parse various date formats found in case data."""
        if not date_str:
            return datetime.now()
        
        # Common date patterns in legal cases
        patterns = [
            r'(\d{4})-(\d{1,2})-(\d{1,2})',  # YYYY-MM-DD
            r'(\d{1,2})/(\d{1,2})/(\d{4})',  # MM/DD/YYYY
            r'(\d{4})',  # Just year
            r'(\w+)\s+(\d{1,2}),?\s+(\d{4})',  # Month DD, YYYY
        ]
        
        for pattern in patterns:
            match = re.search(pattern, date_str)
            if match:
                try:
                    if len(match.groups()) == 1:  # Just year
                        return datetime(int(match.group(1)), 1, 1)
                    elif len(match.groups()) == 3:
                        if pattern == patterns[0]:  # YYYY-MM-DD
                            return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
                        elif pattern == patterns[1]:  # MM/DD/YYYY
                            return datetime(int(match.group(3)), int(match.group(1)), int(match.group(2)))
                        elif pattern == patterns[3]:  # Month DD, YYYY
                            # Convert month name to number
                            month_map = {
                                'january': 1, 'february': 2, 'march': 3, 'april': 4,
                                'may': 5, 'june': 6, 'july': 7, 'august': 8,
                                'september': 9, 'october': 10, 'november': 11, 'december': 12
                            }
                            month_num = month_map.get(match.group(1).lower(), 1)
                            return datetime(int(match.group(3)), month_num, int(match.group(2)))
                except ValueError:
                    continue
        
        return datetime.now()
    
    def _extract_legal_principles(self, content: str, case_name: str) -> List[str]:
        """Extract legal principles from case content."""
        principles = []
        
        # Common legal principle indicators
        principle_patterns = [
            r'(?:holding|rule|principle|doctrine|standard):\s*(.+?)(?:\.|;|\n)',
            r'(?:we hold that|the rule is|the principle states)\s+(.+?)(?:\.|;|\n)',
            r'(?:establishes? that|provides? that|requires? that)\s+(.+?)(?:\.|;|\n)'
        ]
        
        for pattern in principle_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                principle = match.group(1).strip()
                if len(principle) > 10 and len(principle) < 200:  # Filter reasonable length
                    principles.append(principle)
        
        # Extract from case name common legal concepts
        case_concepts = [
            'qualified immunity', 'due process', 'equal protection', 'reasonable suspicion',
            'probable cause', 'miranda rights', 'fourth amendment', 'first amendment',
            'commerce clause', 'civil rights'
        ]
        
        for concept in case_concepts:
            if concept in content.lower() or concept in case_name.lower():
                principles.append(concept.title())
        
        return list(set(principles))  # Remove duplicates
    
    def _extract_temporal_conditions(self, content: str) -> List[str]:
        """Extract temporal conditions from case content."""
        temporal_conditions = []
        
        for temporal_type, patterns in self.temporal_patterns.items():
            for pattern in patterns:
                matches = re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE)
                for match in matches:
                    condition = f"{temporal_type}: {match.group(1).strip()} -> {match.group(2).strip()}"
                    temporal_conditions.append(condition)
        
        return temporal_conditions
    
    def _extract_precedent_relationships(self, content: str) -> List[str]:
        """Extract relationships to other precedent cases."""
        relationships = []
        
        # Pattern for case citations and references
        citation_patterns = [
            r'(?:following|citing|relying on|pursuant to)\s+(.+?v\.?\s+.+?)(?:\s+\d+|\s+\(|\.|,)',
            r'(?:see|accord|cf\.?)\s+(.+?v\.?\s+.+?)(?:\s+\d+|\s+\(|\.|,)',
            r'(?:overrule?s?|reverse?s?|distinguish?e?s?)\s+(.+?v\.?\s+.+?)(?:\s+\d+|\s+\(|\.|,)'
        ]
        
        for pattern in citation_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                case_ref = match.group(1).strip()
                if 'v.' in case_ref and len(case_ref) > 5:
                    relationships.append(case_ref)
        
        return list(set(relationships))
    
    def _classify_legal_domain(self, content: str, case_name: str) -> Optional[str]:
        """Classify the legal domain of the case."""
        # Use string constants instead of enum when LegalDomain not available
        domain_indicators = {
            'constitutional': ['amendment', 'constitutional', 'bill of rights', 'due process'],
            'criminal': ['criminal', 'prosecution', 'defendant', 'guilty', 'sentencing'],
            'contract': ['contract', 'breach', 'agreement', 'consideration', 'offer'],
            'tort': ['negligence', 'liability', 'damages', 'tort', 'injury'],
            'corporate': ['corporation', 'securities', 'shareholder', 'merger', 'corporate'],
            'employment': ['employment', 'discrimination', 'workplace', 'employee', 'labor']
        }
        
        text = (content + ' ' + case_name).lower()
        
        for domain, indicators in domain_indicators.items():
            if any(indicator in text for indicator in indicators):
                return domain
        
        return None
    
    async def _build_precedent_graph(self, precedents: List[TemporalLegalPrecedent]):
        """Build a graph of precedent relationships."""
        for precedent in precedents:
            # Add precedent to graph
            self.precedent_graph[precedent.case_id] = []
            
            # Find relationships with other precedents
            for other in precedents:
                if other.case_id != precedent.case_id:
                    # Check if this case cites the other
                    if any(other.case_name.lower() in rel.lower() for rel in precedent.precedent_relationships):
                        self.precedent_graph[precedent.case_id].append(other.case_id)
                    
                    # Check chronological ordering for implicit relationships
                    if (precedent.date_decided > other.date_decided and 
                        precedent.domain == other.domain):
                        # Potential implicit precedent relationship
                        if any(principle in [p.lower() for p in other.legal_principles] 
                               for principle in [p.lower() for p in precedent.legal_principles]):
                            self.precedent_graph[precedent.case_id].append(other.case_id)
    
    async def _extract_temporal_patterns(self, 
                                       precedents: List[TemporalLegalPrecedent], 
                                       doctrine_name: str) -> Dict[str, Any]:
        """Extract temporal patterns across the case lineage."""
        patterns = {
            "chronological_evolution": [],
            "temporal_constraints": [],
            "consistency_patterns": [],
            "doctrine_development": []
        }
        
        # Analyze chronological evolution of deontic statements
        for i, precedent in enumerate(precedents):
            evolution_entry = {
                "case_id": precedent.case_id,
                "date": precedent.date_decided.isoformat(),
                "deontic_changes": [],
                "new_obligations": [],
                "new_permissions": [],
                "new_prohibitions": []
            }
            
            # Categorize deontic statements
            for stmt in precedent.deontic_statements:
                if hasattr(stmt, 'modality'):
                    modality = getattr(stmt, 'modality', None)
                    if modality == DeonticModality.OBLIGATION or (isinstance(modality, str) and modality == "obligation"):
                        evolution_entry["new_obligations"].append(stmt.action)
                    elif modality == DeonticModality.PERMISSION or (isinstance(modality, str) and modality == "permission"):
                        evolution_entry["new_permissions"].append(stmt.action)
                    elif modality == DeonticModality.PROHIBITION or (isinstance(modality, str) and modality == "prohibition"):
                        evolution_entry["new_prohibitions"].append(stmt.action)
            
            patterns["chronological_evolution"].append(evolution_entry)
        
        # Extract temporal constraints
        for precedent in precedents:
            for condition in precedent.temporal_conditions:
                patterns["temporal_constraints"].append({
                    "case_id": precedent.case_id,
                    "condition": condition,
                    "date": precedent.date_decided.isoformat()
                })
        
        return patterns
    
    async def _generate_theorems(self, 
                               precedents: List[TemporalLegalPrecedent],
                               temporal_patterns: Dict[str, Any],
                               doctrine_name: str) -> List[TemporalDeonticTheorem]:
        """Generate formal temporal deontic logic theorems from case lineage."""
        theorems = []
        
        # Generate theorem for chronological consistency
        consistency_theorem = await self._generate_consistency_theorem(precedents, doctrine_name)
        if consistency_theorem:
            theorems.append(consistency_theorem)
        
        # Generate theorems for each major legal principle
        for precedent in precedents:
            for principle in precedent.legal_principles:
                principle_theorem = await self._generate_principle_theorem(precedent, principle, precedents)
                if principle_theorem:
                    theorems.append(principle_theorem)
        
        # Generate temporal constraint theorems
        temporal_theorem = await self._generate_temporal_theorem(temporal_patterns, doctrine_name, precedents)
        if temporal_theorem:
            theorems.append(temporal_theorem)
        
        return theorems
    
    async def _generate_consistency_theorem(self, 
                                          precedents: List[TemporalLegalPrecedent],
                                          doctrine_name: str) -> Optional[TemporalDeonticTheorem]:
        """Generate a theorem asserting chronological consistency."""
        if len(precedents) < 2:
            return None
        
        theorem_id = f"consistency_{doctrine_name}_{len(precedents)}"
        
        # Build formal statement
        formal_parts = []
        case_vars = []
        
        for i, precedent in enumerate(precedents):
            case_var = f"C{i+1}"
            case_vars.append(case_var)
            
            # Add temporal ordering constraints
            if i > 0:
                prev_var = f"C{i}"
                formal_parts.append(f"Before({prev_var}, {case_var})")
            
            # Add consistency constraints for obligations
            for stmt in precedent.deontic_statements:
                if stmt.modality == DeonticModality.OBLIGATION:
                    formal_parts.append(f"O({case_var}, {stmt.action})")
                elif stmt.modality == DeonticModality.PROHIBITION:
                    formal_parts.append(f"F({case_var}, {stmt.action})")
                elif stmt.modality == DeonticModality.PERMISSION:
                    formal_parts.append(f"P({case_var}, {stmt.action})")
        
        # Add consistency constraint: no contradictions across time
        consistency_constraint = f"∀x,t1,t2 (Before(t1,t2) → ¬(O(t1,x) ∧ F(t2,x)))"
        formal_parts.append(consistency_constraint)
        
        formal_statement = " ∧ ".join(formal_parts)
        
        natural_language = (
            f"The {doctrine_name} doctrine maintains chronological consistency: "
            f"obligations established in earlier cases cannot be directly contradicted "
            f"by prohibitions in later cases without explicit overruling."
        )
        
        return TemporalDeonticTheorem(
            theorem_id=theorem_id,
            name=f"Chronological Consistency of {doctrine_name}",
            formal_statement=formal_statement,
            natural_language=natural_language,
            supporting_cases=[p.case_id for p in precedents],
            temporal_constraints=[f"Before(C{i}, C{i+1})" for i in range(len(precedents)-1)],
            domain=precedents[0].domain if precedents else None
        )
    
    async def _generate_principle_theorem(self, 
                                        precedent: TemporalLegalPrecedent,
                                        principle: str,
                                        all_precedents: List[TemporalLegalPrecedent]) -> Optional[TemporalDeonticTheorem]:
        """Generate a theorem for a specific legal principle."""
        theorem_id = f"principle_{precedent.case_id}_{principle.replace(' ', '_')}"
        
        # Find related deontic statements
        related_statements = [
            stmt for stmt in precedent.deontic_statements 
            if principle.lower() in stmt.action.lower() or principle.lower() in stmt.source_text.lower()
        ]
        
        if not related_statements:
            return None
        
        # Build formal statement
        formal_parts = []
        
        for stmt in related_statements:
            if stmt.modality == DeonticModality.OBLIGATION:
                formal_parts.append(f"∀x (Context({precedent.case_id}, x) → O(x, {stmt.action}))")
            elif stmt.modality == DeonticModality.PROHIBITION:
                formal_parts.append(f"∀x (Context({precedent.case_id}, x) → F(x, {stmt.action}))")
            elif stmt.modality == DeonticModality.PERMISSION:
                formal_parts.append(f"∀x (Context({precedent.case_id}, x) → P(x, {stmt.action}))")
        
        formal_statement = " ∧ ".join(formal_parts)
        
        natural_language = (
            f"In {precedent.case_name} ({precedent.date_decided.year}), "
            f"the principle of {principle} establishes specific legal obligations "
            f"and permissions that must be consistently applied in similar contexts."
        )
        
        return TemporalDeonticTheorem(
            theorem_id=theorem_id,
            name=f"Principle of {principle} in {precedent.case_name}",
            formal_statement=formal_statement,
            natural_language=natural_language,
            supporting_cases=[precedent.case_id],
            temporal_constraints=[f"After({precedent.date_decided.isoformat()}, application)"],
            domain=precedent.domain
        )
    
    async def _generate_temporal_theorem(self, 
                                       temporal_patterns: Dict[str, Any],
                                       doctrine_name: str,
                                       precedents: List[TemporalLegalPrecedent]) -> Optional[TemporalDeonticTheorem]:
        """Generate theorems for temporal constraints."""
        if not temporal_patterns.get("temporal_constraints"):
            return None
        
        theorem_id = f"temporal_{doctrine_name}_constraints"
        
        formal_parts = []
        
        # Process temporal constraints
        for constraint in temporal_patterns["temporal_constraints"]:
            condition = constraint["condition"]
            case_id = constraint["case_id"]
            
            # Parse temporal relationships
            if "before:" in condition.lower():
                parts = condition.split(" -> ")
                if len(parts) == 2:
                    temporal_cond = parts[0].split(": ")[1]
                    deontic_stmt = parts[1]
                    formal_parts.append(f"∀x,t (Before(t, {temporal_cond}) → {deontic_stmt})")
            elif "after:" in condition.lower():
                parts = condition.split(" -> ")
                if len(parts) == 2:
                    temporal_cond = parts[0].split(": ")[1]
                    deontic_stmt = parts[1]
                    formal_parts.append(f"∀x,t (After(t, {temporal_cond}) → {deontic_stmt})")
        
        if not formal_parts:
            return None
        
        formal_statement = " ∧ ".join(formal_parts)
        
        natural_language = (
            f"The {doctrine_name} doctrine includes specific temporal constraints "
            f"that determine when certain legal obligations and permissions apply "
            f"based on chronological relationships between events and legal determinations."
        )
        
        return TemporalDeonticTheorem(
            theorem_id=theorem_id,
            name=f"Temporal Constraints in {doctrine_name}",
            formal_statement=formal_statement,
            natural_language=natural_language,
            supporting_cases=[p.case_id for p in precedents],
            temporal_constraints=[c["condition"] for c in temporal_patterns["temporal_constraints"]],
            domain=precedents[0].domain if precedents else None
        )
    
    async def _verify_chronological_consistency(self, 
                                              theorems: List[TemporalDeonticTheorem],
                                              precedents: List[TemporalLegalPrecedent]) -> Dict[str, Any]:
        """Verify that theorems are chronologically consistent."""
        consistency_results = {
            "overall_consistent": True,
            "conflicts_detected": [],
            "temporal_violations": [],
            "resolution_suggestions": []
        }
        
        # Check for temporal ordering violations
        for i, theorem1 in enumerate(theorems):
            for j, theorem2 in enumerate(theorems[i+1:], i+1):
                conflicts = self._detect_theorem_conflicts(theorem1, theorem2)
                if conflicts:
                    consistency_results["conflicts_detected"].extend(conflicts)
                    consistency_results["overall_consistent"] = False
        
        # Check precedent chronological ordering
        for i, precedent in enumerate(precedents[:-1]):
            next_precedent = precedents[i+1]
            if precedent.date_decided > next_precedent.date_decided:
                consistency_results["temporal_violations"].append({
                    "type": "chronological_ordering",
                    "case1": precedent.case_id,
                    "case2": next_precedent.case_id,
                    "issue": "Later case appears before earlier case in sequence"
                })
        
        # Generate resolution suggestions
        if not consistency_results["overall_consistent"]:
            consistency_results["resolution_suggestions"] = [
                "Review case chronological ordering for accuracy",
                "Check for explicit overruling relationships",
                "Verify contextual differences that might resolve apparent conflicts",
                "Consider domain-specific exceptions to general rules"
            ]
        
        return consistency_results
    
    def _detect_theorem_conflicts(self, 
                                theorem1: TemporalDeonticTheorem, 
                                theorem2: TemporalDeonticTheorem) -> List[Dict[str, Any]]:
        """Detect conflicts between two theorems."""
        conflicts = []
        
        # Simple conflict detection based on formal statements
        # In a full implementation, this would use formal logic analysis
        
        if ("O(" in theorem1.formal_statement and "F(" in theorem2.formal_statement):
            # Check for obligation vs prohibition conflicts
            # This is a simplified check - real implementation would parse formal logic
            conflicts.append({
                "type": "obligation_prohibition_conflict",
                "theorem1": theorem1.theorem_id,
                "theorem2": theorem2.theorem_id,
                "description": "Potential conflict between obligation and prohibition"
            })
        
        return conflicts
    
    async def _execute_consistency_proofs(self, 
                                        theorems: List[TemporalDeonticTheorem]) -> List[Dict[str, Any]]:
        """Execute consistency proofs using theorem provers."""
        if not self.use_existing_tools:
            return []
        
        proof_results = []
        
        for theorem in theorems:
            try:
                # Convert to appropriate format for theorem prover
                if hasattr(self.deontic_converter, 'convert_to_smt'):
                    # Use existing SMT conversion if available
                    smt_formula = self.deontic_converter.convert_to_smt(theorem.formal_statement)
                    
                    # Execute proof
                    proof_result = self.proof_engine.prove_formula(smt_formula, prover="z3")
                    
                    proof_results.append({
                        "theorem_id": theorem.theorem_id,
                        "proof_status": proof_result.status.value if hasattr(proof_result, 'status') else "unknown",
                        "execution_time": proof_result.execution_time if hasattr(proof_result, 'execution_time') else 0,
                        "proof_output": proof_result.proof_output if hasattr(proof_result, 'proof_output') else ""
                    })
                    
            except Exception as e:
                logger.warning(f"Could not execute proof for theorem {theorem.theorem_id}: {e}")
                proof_results.append({
                    "theorem_id": theorem.theorem_id,
                    "proof_status": "error",
                    "error": str(e)
                })
        
        return proof_results
    
    def _format_precedent(self, precedent: TemporalLegalPrecedent) -> Dict[str, Any]:
        """Format precedent for output."""
        return {
            "case_id": precedent.case_id,
            "case_name": precedent.case_name,
            "citation": precedent.citation,
            "date_decided": precedent.date_decided.isoformat(),
            "court": precedent.court,
            "legal_principles": precedent.legal_principles,
            "deontic_statements_count": len(precedent.deontic_statements),
            "temporal_conditions": precedent.temporal_conditions,
            "precedent_relationships": precedent.precedent_relationships,
            "domain": precedent.domain if precedent.domain else None,
            "confidence": precedent.confidence
        }
    
    def _format_theorem(self, theorem: TemporalDeonticTheorem) -> Dict[str, Any]:
        """Format theorem for output."""
        return {
            "theorem_id": theorem.theorem_id,
            "name": theorem.name,
            "formal_statement": theorem.formal_statement,
            "natural_language": theorem.natural_language,
            "supporting_cases": theorem.supporting_cases,
            "temporal_constraints": theorem.temporal_constraints,
            "domain": theorem.domain if theorem.domain else None,
            "creation_date": theorem.creation_date.isoformat()
        }
    
    async def export_theorems_to_ipld(self, theorems: List[TemporalDeonticTheorem]) -> Dict[str, Any]:
        """Export theorems to IPLD format for decentralized storage."""
        ipld_data = {
            "type": "temporal_deontic_theorems",
            "version": "1.0",
            "created": datetime.now().isoformat(),
            "theorems": {}
        }
        
        for theorem in theorems:
            ipld_data["theorems"][theorem.theorem_id] = {
                "formal_statement": theorem.formal_statement,
                "natural_language": theorem.natural_language,
                "supporting_cases": theorem.supporting_cases,
                "temporal_constraints": theorem.temporal_constraints,
                "domain": theorem.domain if theorem.domain else None,
                "proof_hash": None  # Would contain hash of consistency proof
            }
        
        return ipld_data


# Integration functions for the existing caselaw dashboard

async def integrate_temporal_deontic_logic(caselaw_processor, cases: List[Dict[str, Any]], 
                                         doctrine: str) -> Dict[str, Any]:
    """
    Integration function to add temporal deontic logic processing
    to the existing caselaw GraphRAG dashboard.
    """
    temporal_processor = TemporalDeonticCaselawProcessor()
    
    # Process the cases through temporal deontic logic
    logic_analysis = await temporal_processor.process_caselaw_lineage(cases, doctrine)
    
    # Add formal logic representation to each case
    enhanced_cases = []
    for case in cases:
        case_id = case.get('id', case.get('case_id'))
        
        # Find corresponding precedent
        precedent = temporal_processor.precedents.get(case_id)
        if precedent:
            case['formal_logic'] = {
                'deontic_statements': [
                    {
                        'entity': stmt.entity,
                        'action': stmt.action,
                        'modality': stmt.modality.value,
                        'confidence': stmt.confidence
                    }
                    for stmt in precedent.deontic_statements
                ],
                'temporal_conditions': precedent.temporal_conditions,
                'legal_principles': precedent.legal_principles,
                'domain': precedent.domain if precedent.domain else None
            }
        
        enhanced_cases.append(case)
    
    return {
        'enhanced_cases': enhanced_cases,
        'logic_analysis': logic_analysis,
        'formal_theorems': logic_analysis.get('generated_theorems', []),
        'consistency_verified': logic_analysis.get('consistency_analysis', {}).get('overall_consistent', False)
    }


if __name__ == "__main__":
    # Example usage
    import asyncio
    
    async def demo_temporal_deontic_logic():
        processor = TemporalDeonticCaselawProcessor()
        
        # Example cases for qualified immunity doctrine
        example_cases = [
            {
                "id": "pierson_v_ray_1967",
                "case_name": "Pierson v. Ray", 
                "citation": "386 U.S. 547 (1967)",
                "date": "1967-01-15",
                "court": "Supreme Court",
                "content": "Police officers acting in good faith and with probable cause are immune from civil liability under Section 1983. Officers must have objectively reasonable belief that their conduct was lawful."
            },
            {
                "id": "harlow_v_fitzgerald_1982",
                "case_name": "Harlow v. Fitzgerald",
                "citation": "457 U.S. 800 (1982)", 
                "date": "1982-06-30",
                "court": "Supreme Court",
                "content": "Government officials performing discretionary functions are shielded from liability insofar as their conduct does not violate clearly established statutory or constitutional rights of which a reasonable person would have known."
            }
        ]
        
        result = await processor.process_caselaw_lineage(example_cases, "qualified_immunity")
        
        print("Temporal Deontic Logic Analysis:")
        print(json.dumps(result, indent=2))
    
    # Run demo
    asyncio.run(demo_temporal_deontic_logic())