"""
Deontic Logic Converter Module

This module provides the main conversion engine that transforms GraphRAG-processed
legal documents into deontic first-order logic formulas. It serves as the bridge
between the GraphRAG knowledge extraction and formal logic representation.
"""

import logging
from typing import Dict, List, Optional, Union, Any, Tuple, Set
from dataclasses import dataclass, field
import re
import json
from datetime import datetime

from .deontic_logic_core import (
    DeonticFormula, DeonticOperator, LegalAgent, LegalContext, 
    TemporalCondition, TemporalOperator, DeonticRuleSet,
    create_obligation, create_permission, create_prohibition
)
from .legal_domain_knowledge import LegalDomainKnowledge, LegalDomain
from .logic_translation_core import LogicTranslationTarget, LogicTranslator

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Type hints for GraphRAG components (these would be imported from GraphRAG modules)
try:
    from ..knowledge_graph_extraction import Entity, Relationship, KnowledgeGraph
    GRAPHRAG_AVAILABLE = True
except ImportError:
    # Fallback types when GraphRAG is not available
    GRAPHRAG_AVAILABLE = False
    
    @dataclass
    class Entity:
        id: str
        data: Dict[str, Any]
        type: str = "entity"
    
    @dataclass 
    class Relationship:
        id: str
        source: str
        target: str
        type: str
        data: Dict[str, Any] = field(default_factory=dict)
    
    @dataclass
    class KnowledgeGraph:
        entities: List[Entity] = field(default_factory=list)
        relationships: List[Relationship] = field(default_factory=list)


@dataclass
class ConversionContext:
    """Context information for the conversion process."""
    source_document_path: str
    document_title: str = ""
    legal_domain: Optional[LegalDomain] = None
    jurisdiction: Optional[str] = None
    confidence_threshold: float = 0.5
    enable_temporal_analysis: bool = True
    enable_agent_inference: bool = True
    enable_condition_extraction: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_document_path": self.source_document_path,
            "document_title": self.document_title,
            "legal_domain": self.legal_domain.value if self.legal_domain else None,
            "jurisdiction": self.jurisdiction,
            "confidence_threshold": self.confidence_threshold,
            "enable_temporal_analysis": self.enable_temporal_analysis,
            "enable_agent_inference": self.enable_agent_inference,
            "enable_condition_extraction": self.enable_condition_extraction
        }


@dataclass
class ConversionResult:
    """Result of converting GraphRAG entities/relationships to deontic logic."""
    deontic_formulas: List[DeonticFormula]
    rule_set: DeonticRuleSet
    conversion_metadata: Dict[str, Any]
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    statistics: Dict[str, int] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "deontic_formulas": [f.to_dict() for f in self.deontic_formulas],
            "rule_set": self.rule_set.to_dict(),
            "conversion_metadata": self.conversion_metadata,
            "errors": self.errors,
            "warnings": self.warnings,
            "statistics": self.statistics
        }


class DeonticLogicConverter:
    """
    Main converter from GraphRAG output to deontic logic formulas.
    
    This class orchestrates the conversion process by:
    1. Analyzing GraphRAG entities and relationships
    2. Applying legal domain knowledge to identify deontic concepts
    3. Constructing formal deontic logic formulas
    4. Validating and organizing results into rule sets
    """
    
    def __init__(self, 
                 domain_knowledge: Optional[LegalDomainKnowledge] = None,
                 enable_symbolic_ai: bool = True):
        """
        Initialize the deontic logic converter.
        
        Args:
            domain_knowledge: Legal domain knowledge base
            enable_symbolic_ai: Whether to use SymbolicAI for enhanced analysis
        """
        self.domain_knowledge = domain_knowledge or LegalDomainKnowledge()
        self.enable_symbolic_ai = enable_symbolic_ai
        
        # Initialize SymbolicAI components if available
        self.symbolic_analyzer = None
        if enable_symbolic_ai:
            try:
                from .legal_symbolic_analyzer import LegalSymbolicAnalyzer
                self.symbolic_analyzer = LegalSymbolicAnalyzer()
                logger.info("SymbolicAI legal analyzer initialized")
            except (ImportError, SystemExit) as e:
                self.symbolic_analyzer = None
                logger.warning(
                    "SymbolicAI not available or misconfigured (%s) - using fallback analysis",
                    e,
                )
            except Exception as e:
                self.symbolic_analyzer = None
                logger.warning(
                    "SymbolicAI initialization failed (%s) - using fallback analysis",
                    e,
                )
        
        # Conversion statistics
        self.conversion_stats = {
            "total_entities_processed": 0,
            "total_relationships_processed": 0,
            "obligations_extracted": 0,
            "permissions_extracted": 0,
            "prohibitions_extracted": 0,
            "agents_identified": 0,
            "temporal_conditions_extracted": 0
        }
    
    def convert_knowledge_graph_to_logic(self, 
                                       knowledge_graph: KnowledgeGraph,
                                       context: ConversionContext) -> ConversionResult:
        """
        Convert a complete knowledge graph to deontic logic formulas.
        
        Args:
            knowledge_graph: GraphRAG knowledge graph with entities and relationships
            context: Conversion context and parameters
            
        Returns:
            ConversionResult with deontic formulas and metadata
        """
        logger.info(f"Converting knowledge graph with {len(knowledge_graph.entities)} entities "
                   f"and {len(knowledge_graph.relationships)} relationships")
        
        # Reset statistics
        self._reset_statistics()
        
        errors = []
        warnings = []
        all_formulas = []
        
        try:
            # Analyze entities for deontic content  
            entities_list = list(knowledge_graph.entities.values()) if isinstance(knowledge_graph.entities, dict) else knowledge_graph.entities
            entity_formulas = self.convert_entities_to_logic(entities_list, context)
            all_formulas.extend(entity_formulas)
            
            # Analyze relationships for deontic content
            relationships_list = list(knowledge_graph.relationships.values()) if isinstance(knowledge_graph.relationships, dict) else knowledge_graph.relationships
            relationship_formulas = self.convert_relationships_to_logic(
                relationships_list, context
            )
            all_formulas.extend(relationship_formulas)
            
            # Apply cross-entity reasoning if symbolic AI is available
            if self.symbolic_analyzer:
                synthetic_formulas = self._synthesize_complex_rules(
                    all_formulas, knowledge_graph, context
                )
                all_formulas.extend(synthetic_formulas)
            
            # Create rule set
            rule_set = DeonticRuleSet(
                name=context.document_title or "Legal Document Rules",
                formulas=all_formulas,
                description=f"Deontic logic rules extracted from {context.source_document_path}",
                source_document=context.source_document_path,
                legal_context=self._create_legal_context(context)
            )
            
            # Validate rule set consistency
            validation_errors = self._validate_rule_set_consistency(rule_set)
            errors.extend(validation_errors)
            
            # Generate conversion metadata
            metadata = self._generate_conversion_metadata(context, knowledge_graph)
            
            return ConversionResult(
                deontic_formulas=all_formulas,
                rule_set=rule_set,
                conversion_metadata=metadata,
                errors=errors,
                warnings=warnings,
                statistics=self.conversion_stats.copy()
            )
            
        except Exception as e:
            logger.error(f"Error in knowledge graph conversion: {e}")
            errors.append(f"Conversion failed: {str(e)}")
            
            return ConversionResult(
                deontic_formulas=[],
                rule_set=DeonticRuleSet("Failed Conversion", []),
                conversion_metadata={},
                errors=errors,
                warnings=warnings,
                statistics=self.conversion_stats.copy()
            )
    
    def convert_entities_to_logic(self, 
                                entities: List[Entity], 
                                context: ConversionContext) -> List[DeonticFormula]:
        """
        Convert GraphRAG entities to deontic logic formulas.
        
        Args:
            entities: List of GraphRAG entities
            context: Conversion context
            
        Returns:
            List of deontic formulas extracted from entities
        """
        formulas = []
        
        for entity in entities:
            self.conversion_stats["total_entities_processed"] += 1
            
            try:
                # Extract text content from entity
                entity_text = self._extract_entity_text(entity)
                if not entity_text:
                    logger.debug(f"Skipping entity {entity.entity_id} - no text content")
                    continue
                
                # Classify the deontic nature of the entity
                operator, confidence = self.domain_knowledge.classify_legal_statement(entity_text)
                logger.debug(f"Entity {entity.entity_id}: operator={operator}, confidence={confidence}")
                
                if operator and confidence >= context.confidence_threshold:
                    # Extract components for the formula
                    proposition = self._extract_proposition_from_entity(entity)
                    agent = self._extract_agent_from_entity(entity, context)
                    conditions = self._extract_conditions_from_entity(entity, context)
                    temporal_conditions = self._extract_temporal_conditions_from_entity(entity, context)
                    
                    # Create the deontic formula
                    formula = DeonticFormula(
                        operator=operator,
                        proposition=proposition,
                        agent=agent,
                        conditions=conditions,
                        temporal_conditions=temporal_conditions,
                        confidence=confidence,
                        source_text=entity_text,
                        legal_context=self._create_legal_context(context)
                    )
                    
                    formulas.append(formula)
                    self._update_statistics(operator)
                    
                    logger.info(f"✅ Extracted formula from entity {entity.entity_id}: {formula.to_fol_string()}")
                else:
                    logger.debug(f"Skipping entity {entity.entity_id} - operator={operator}, confidence={confidence} < {context.confidence_threshold}")
                
            except Exception as e:
                logger.error(f"Error processing entity {entity.entity_id}: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        return formulas
    
    def convert_relationships_to_logic(self, 
                                     relationships: List[Relationship],
                                     context: ConversionContext) -> List[DeonticFormula]:
        """
        Convert GraphRAG relationships to deontic logic formulas.
        
        Args:
            relationships: List of GraphRAG relationships
            context: Conversion context
            
        Returns:
            List of deontic formulas extracted from relationships
        """
        formulas = []
        
        for relationship in relationships:
            self.conversion_stats["total_relationships_processed"] += 1
            
            try:
                # Extract relationship text/description
                rel_text = self._extract_relationship_text(relationship)
                if not rel_text:
                    continue
                
                # Analyze relationship type for deontic significance
                deontic_info = self._analyze_relationship_for_deontic_content(relationship, context)
                
                if deontic_info:
                    operator, confidence, proposition = deontic_info
                    
                    if confidence >= context.confidence_threshold:
                        # Extract agents from source and target entities
                        source_agent = self._create_agent_from_entity_id(relationship.source_entity.entity_id if relationship.source_entity else "", context)
                        target_agent = self._create_agent_from_entity_id(relationship.target_entity.entity_id if relationship.target_entity else "", context)
                        
                        # Use source as primary agent, target as beneficiary if applicable
                        formula = DeonticFormula(
                            operator=operator,
                            proposition=proposition,
                            agent=source_agent,
                            beneficiary=target_agent,
                            confidence=confidence,
                            source_text=rel_text,
                            legal_context=self._create_legal_context(context)
                        )
                        
                        formulas.append(formula)
                        self._update_statistics(operator)
                        
                        logger.debug(f"Extracted formula from relationship {relationship.relationship_id}: {formula.to_fol_string()}")
                
            except Exception as e:
                logger.warning(f"Error processing relationship {relationship.relationship_id}: {e}")
                continue
        
        return formulas
    
    def _extract_entity_text(self, entity: Entity) -> str:
        """Extract text content from an entity."""
        # Try various fields that might contain text
        text_fields = ["text", "content", "description", "name", "title"]
        
        for field in text_fields:
            if field in entity.properties and entity.properties[field]:
                return str(entity.properties[field])
        
        # Also try the source_text field
        if entity.source_text:
            return entity.source_text
        
        # Fallback to entity name
        return entity.name or entity.entity_id
    
    def _extract_proposition_from_entity(self, entity: Entity) -> str:
        """Extract the proposition/action from an entity."""
        # Look for action-oriented fields
        proposition_fields = ["action", "proposition", "activity", "behavior", "conduct"]
        
        for field in proposition_fields:
            if field in entity.properties and entity.properties[field]:
                return self._normalize_proposition(str(entity.properties[field]))
        
        # Extract from entity text using pattern matching
        entity_text = self._extract_entity_text(entity)
        
        # Look for verb phrases that might represent actions
        verb_patterns = [
            r'\b(shall|must|will|may|can)\s+([^,\.]+)',
            r'\b(pay|provide|deliver|complete|perform|maintain|ensure)\s+([^,\.]*)',
            r'\b(not\s+)?(disclose|interfere|violate|breach|infringe)\s+([^,\.]*)'
        ]
        
        for pattern in verb_patterns:
            match = re.search(pattern, entity_text, re.IGNORECASE)
            if match:
                if len(match.groups()) >= 2:
                    return self._normalize_proposition(match.group(2).strip())
                else:
                    return self._normalize_proposition(match.group(1).strip())
        
        # Fallback to a normalized version of entity text
        return self._normalize_proposition(entity_text[:50])  # First 50 chars
    
    def _extract_agent_from_entity(self, entity: Entity, context: ConversionContext) -> Optional[LegalAgent]:
        """Extract legal agent information from an entity."""
        if not context.enable_agent_inference:
            return None
        
        # Check if entity itself represents an agent
        agent_indicators = ["agent", "party", "person", "organization", "role"]
        
        if any(indicator in entity.entity_type.lower() for indicator in agent_indicators):
            return LegalAgent(
                identifier=entity.entity_id,
                name=entity.properties.get("name", entity.name) or entity.entity_id,
                agent_type=self._classify_agent_type(entity)
            )
        
        # Extract agent from entity text
        entity_text = self._extract_entity_text(entity)
        agents = self.domain_knowledge.extract_agents(entity_text)
        
        if agents:
            agent_name, agent_type, confidence = agents[0]  # Take the first/best agent
            return LegalAgent(
                identifier=f"agent_{hash(agent_name) % 10000}",
                name=agent_name,
                agent_type=agent_type
            )
        
        return None
    
    def _extract_conditions_from_entity(self, entity: Entity, context: ConversionContext) -> List[str]:
        """Extract conditional clauses from an entity."""
        if not context.enable_condition_extraction:
            return []
        
        entity_text = self._extract_entity_text(entity)
        return self.domain_knowledge.extract_conditions(entity_text)
    
    def _extract_temporal_conditions_from_entity(self, entity: Entity, 
                                               context: ConversionContext) -> List[TemporalCondition]:
        """Extract temporal conditions from an entity."""
        if not context.enable_temporal_analysis:
            return []
        
        temporal_conditions = []
        entity_text = self._extract_entity_text(entity)
        
        # Extract temporal expressions
        temporal_expressions = self.domain_knowledge.extract_temporal_expressions(entity_text)
        
        for category, expressions in temporal_expressions.items():
            for expr in expressions:
                if category == "deadline":
                    temporal_conditions.append(TemporalCondition(
                        operator=TemporalOperator.UNTIL,
                        condition=expr,
                        end_time=expr
                    ))
                elif category == "duration":
                    temporal_conditions.append(TemporalCondition(
                        operator=TemporalOperator.ALWAYS,
                        condition=expr,
                        duration=expr
                    ))
                elif category == "start_time":
                    temporal_conditions.append(TemporalCondition(
                        operator=TemporalOperator.EVENTUALLY,
                        condition=expr,
                        start_time=expr
                    ))
        
        if temporal_conditions:
            self.conversion_stats["temporal_conditions_extracted"] += len(temporal_conditions)
        
        return temporal_conditions
    
    def _extract_relationship_text(self, relationship: Relationship) -> str:
        """Extract text content from a relationship."""
        text_fields = ["description", "text", "label", "type"]
        
        for field in text_fields:
            if hasattr(relationship, field) and getattr(relationship, field):
                return str(getattr(relationship, field))
            elif field in relationship.data and relationship.data[field]:
                return str(relationship.data[field])
        
        # Fallback to relationship type
        return relationship.relationship_type if hasattr(relationship, 'relationship_type') else ""
    
    def _analyze_relationship_for_deontic_content(self, relationship: Relationship, 
                                                context: ConversionContext) -> Optional[Tuple[DeonticOperator, float, str]]:
        """
        Analyze a relationship for deontic significance.
        
        Returns:
            Tuple of (operator, confidence, proposition) if deontic content found, None otherwise
        """
        rel_text = self._extract_relationship_text(relationship)
        
        # Map relationship types to deontic concepts
        obligation_rels = ["must", "shall", "requires", "obligates", "binds", "compels"]
        permission_rels = ["may", "can", "allows", "permits", "authorizes", "enables"]
        prohibition_rels = ["must_not", "shall_not", "prohibits", "forbids", "bars", "prevents"]
        
        rel_type_lower = relationship.relationship_type.lower() if hasattr(relationship, 'relationship_type') else ""
        
        # Check relationship type
        if any(oblig in rel_type_lower for oblig in obligation_rels):
            return DeonticOperator.OBLIGATION, 0.8, self._extract_proposition_from_relationship(relationship)
        elif any(perm in rel_type_lower for perm in permission_rels):
            return DeonticOperator.PERMISSION, 0.8, self._extract_proposition_from_relationship(relationship)
        elif any(prohib in rel_type_lower for prohib in prohibition_rels):
            return DeonticOperator.PROHIBITION, 0.8, self._extract_proposition_from_relationship(relationship)
        
        # Analyze relationship text using domain knowledge
        operator, confidence = self.domain_knowledge.classify_legal_statement(rel_text)
        
        if operator and confidence > 0.5:
            proposition = self._extract_proposition_from_relationship(relationship)
            return operator, confidence, proposition
        
        return None
    
    def _extract_proposition_from_relationship(self, relationship: Relationship) -> str:
        """Extract proposition/action from a relationship."""
        rel_text = self._extract_relationship_text(relationship)
        
        # If relationship represents an action, use it as proposition
        action_verbs = ["pay", "provide", "deliver", "complete", "perform", "maintain", 
                       "ensure", "comply", "follow", "observe", "respect"]
        
        for verb in action_verbs:
            if verb in rel_text.lower():
                target_id = relationship.target_entity.entity_id if relationship.target_entity else "unknown"
                return self._normalize_proposition(f"{verb}_{target_id}")
        
        # Fallback to relationship type + target
        rel_type = relationship.relationship_type if hasattr(relationship, 'relationship_type') else "relates_to"
        target_id = relationship.target_entity.entity_id if relationship.target_entity else "unknown"
        return self._normalize_proposition(f"{rel_type}_{target_id}")
    
    def _create_agent_from_entity_id(self, entity_id: str, context: ConversionContext) -> Optional[LegalAgent]:
        """Create a legal agent from an entity ID."""
        if not context.enable_agent_inference:
            return None
        
        # This would ideally look up the entity in the knowledge graph
        # For now, create a basic agent from the ID
        return LegalAgent(
            identifier=entity_id,
            name=entity_id.replace("_", " ").title(),
            agent_type="unknown"
        )
    
    def _synthesize_complex_rules(self, formulas: List[DeonticFormula], 
                                knowledge_graph: KnowledgeGraph,
                                context: ConversionContext) -> List[DeonticFormula]:
        """
        Use SymbolicAI to synthesize complex legal rules from simple formulas.
        
        This method looks for patterns and relationships between simple formulas
        to create more sophisticated legal rules.
        """
        if not self.symbolic_analyzer:
            return []
        
        try:
            # Group formulas by agent
            agent_formulas = {}
            for formula in formulas:
                if formula.agent:
                    agent_id = formula.agent.identifier
                    if agent_id not in agent_formulas:
                        agent_formulas[agent_id] = []
                    agent_formulas[agent_id].append(formula)
            
            synthetic_formulas = []
            
            # For each agent with multiple formulas, try to synthesize complex rules
            for agent_id, agent_formula_list in agent_formulas.items():
                if len(agent_formula_list) > 1:
                    # Use SymbolicAI to identify logical relationships
                    complex_rules = self.symbolic_analyzer.synthesize_agent_rules(
                        agent_formula_list, context
                    )
                    synthetic_formulas.extend(complex_rules)
            
            return synthetic_formulas
            
        except Exception as e:
            logger.warning(f"Error in complex rule synthesis: {e}")
            return []
    
    def _create_legal_context(self, context: ConversionContext) -> LegalContext:
        """Create a LegalContext from ConversionContext."""
        return LegalContext(
            jurisdiction=context.jurisdiction,
            legal_domain=context.legal_domain.value if context.legal_domain else None,
            applicable_law=None  # Could be inferred from document
        )
    
    def _validate_rule_set_consistency(self, rule_set: DeonticRuleSet) -> List[str]:
        """Validate the logical consistency of a rule set."""
        errors = []
        
        # Check for direct contradictions
        conflicts = rule_set.check_consistency()
        for formula1, formula2, conflict_desc in conflicts:
            errors.append(f"Logical conflict: {conflict_desc}")
        
        return errors
    
    def _generate_conversion_metadata(self, context: ConversionContext, 
                                    knowledge_graph: KnowledgeGraph) -> Dict[str, Any]:
        """Generate metadata about the conversion process."""
        return {
            "conversion_timestamp": datetime.now().isoformat(),
            "context": context.to_dict(),
            "input_statistics": {
                "entity_count": len(knowledge_graph.entities),
                "relationship_count": len(knowledge_graph.relationships)
            },
            "conversion_statistics": self.conversion_stats.copy(),
            "symbolic_ai_enabled": self.symbolic_analyzer is not None,
            "domain_knowledge_version": "1.0"
        }
    
    def _normalize_proposition(self, text: str) -> str:
        """Normalize a proposition text for use in logic formulas."""
        # Remove extra whitespace and special characters
        normalized = re.sub(r'\s+', '_', text.strip())
        normalized = re.sub(r'[^a-zA-Z0-9_]', '', normalized)
        return normalized.lower()
    
    def _classify_agent_type(self, entity: Entity) -> str:
        """Classify the type of an agent entity."""
        entity_text = self._extract_entity_text(entity).lower()
        
        if any(word in entity_text for word in ["corporation", "company", "llc", "inc", "ltd"]):
            return "organization"
        elif any(word in entity_text for word in ["government", "state", "federal", "municipal"]):
            return "government"
        elif any(word in entity_text for word in ["person", "individual", "citizen"]):
            return "person"
        else:
            return "unknown"
    
    def _update_statistics(self, operator: DeonticOperator):
        """Update conversion statistics based on extracted operator."""
        if operator == DeonticOperator.OBLIGATION:
            self.conversion_stats["obligations_extracted"] += 1
        elif operator == DeonticOperator.PERMISSION:
            self.conversion_stats["permissions_extracted"] += 1
        elif operator == DeonticOperator.PROHIBITION:
            self.conversion_stats["prohibitions_extracted"] += 1
    
    def _reset_statistics(self):
        """Reset conversion statistics."""
        for key in self.conversion_stats:
            self.conversion_stats[key] = 0


def demonstrate_deontic_conversion():
    """Demonstrate the deontic logic conversion system."""
    
    # Create mock GraphRAG data
    entities = [
        Entity(
            id="contractor_entity",
            data={
                "name": "ABC Construction",
                "text": "The contractor shall complete all work by December 31, 2024",
                "type": "organization"
            },
            type="agent"
        ),
        Entity(
            id="payment_obligation",
            data={
                "text": "The client must pay within 30 days of completion",
                "action": "pay_within_deadline"
            },
            type="obligation"
        )
    ]
    
    relationships = [
        Relationship(
            id="contractor_must_complete",
            source="contractor_entity",
            target="work_completion",
            type="must_complete",
            data={"description": "Contractor is obligated to complete work"}
        )
    ]
    
    kg = KnowledgeGraph(entities=entities, relationships=relationships)
    
    # Create conversion context
    context = ConversionContext(
        source_document_path="./test_contract.pdf",
        document_title="Test Construction Contract",
        legal_domain=LegalDomain.CONTRACT,
        jurisdiction="Illinois",
        confidence_threshold=0.6
    )
    
    # Convert to deontic logic
    converter = DeonticLogicConverter()
    result = converter.convert_knowledge_graph_to_logic(kg, context)
    
    print("=== Deontic Logic Conversion Demonstration ===\n")
    print(f"Converted {len(result.deontic_formulas)} formulas")
    print(f"Errors: {len(result.errors)}")
    print(f"Warnings: {len(result.warnings)}")
    print()
    
    print("Extracted Formulas:")
    for i, formula in enumerate(result.deontic_formulas):
        print(f"{i+1}. {formula.operator.value}: {formula.proposition}")
        print(f"   Agent: {formula.agent.name if formula.agent else 'None'}")
        print(f"   FOL: {formula.to_fol_string()}")
        print(f"   Confidence: {formula.confidence}")
        print(f"   Source: {formula.source_text[:60]}...")
        print()
    
    print("Conversion Statistics:")
    for key, value in result.statistics.items():
        print(f"  {key}: {value}")
    
    if result.errors:
        print("\nErrors:")
        for error in result.errors:
            print(f"  - {error}")
    
    return result


if __name__ == "__main__":
    demonstrate_deontic_conversion()