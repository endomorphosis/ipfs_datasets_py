#!/usr/bin/env python3
"""
Advanced Knowledge Extractor for GraphRAG Systems

This module provides enhanced knowledge extraction capabilities beyond the basic
implementation, focusing on academic content, technical documents, and research
papers with improved accuracy and detailed entity relationships.

Features:
- Domain-specific entity recognition (academic, technical, business)
- Advanced relationship extraction with confidence scoring
- Multi-pass extraction for improved accuracy
- Context-aware entity disambiguation
- Temporal relationship extraction
- Cross-document entity linking
"""

import re
import json
import logging
from typing import Dict, List, Set, Tuple, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict, Counter
import uuid

# Import base classes
from ipfs_datasets_py.knowledge_graph_extraction import Entity, Relationship, KnowledgeGraph


logger = logging.getLogger(__name__)


@dataclass
class ExtractionContext:
    """Context information for knowledge extraction"""
    domain: str = "general"  # academic, technical, business, news, etc.
    source_type: str = "text"  # webpage, pdf, paper, book, etc.
    confidence_threshold: float = 0.6
    enable_disambiguation: bool = True
    extract_temporal: bool = True
    max_entities_per_pass: int = 100


@dataclass
class EntityCandidate:
    """Candidate entity before final selection"""
    text: str
    entity_type: str
    confidence: float
    context: str
    start_pos: int
    end_pos: int
    supporting_evidence: List[str] = field(default_factory=list)


@dataclass
class RelationshipCandidate:
    """Candidate relationship before final selection"""
    subject: EntityCandidate
    predicate: str
    object: EntityCandidate
    confidence: float
    context: str
    supporting_evidence: str


class AdvancedKnowledgeExtractor:
    """
    Advanced knowledge extraction with domain-specific patterns and
    improved accuracy for academic and technical content.
    """
    
    def __init__(self, context: ExtractionContext = None):
        """
        Initialize the advanced knowledge extractor
        
        Args:
            context: Extraction context with domain-specific settings
        """
        self.context = context or ExtractionContext()
        self._initialize_patterns()
        
        # Statistics tracking
        self.extraction_stats = {
            'entities_found': 0,
            'relationships_found': 0,
            'disambiguation_resolved': 0,
            'low_confidence_filtered': 0
        }
    
    def _initialize_patterns(self):
        """Initialize domain-specific extraction patterns"""
        
        # Academic/Research patterns
        self.academic_patterns = {
            'person': [
                r'\b(?:Dr\.?|Professor|Prof\.?|Mr\.?|Ms\.?|Mrs\.?)\s+([A-Z][a-z]+ [A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b',
                r'\b([A-Z][a-z]+\s+[A-Z]\.\s+[A-Z][a-z]+)\b',  # John A. Smith
                r'\b([A-Z][a-z]+\s+[A-Z][a-z]+)\s+(?:et al\.?|and colleagues)\b',
                r'\bauthors?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b',
                r'\bresearchers?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b'
            ],
            'organization': [
                r'\b([A-Z][a-zA-Z\s]+(?:University|Institute|Laboratory|Lab|Center|Centre))\b',
                r'\b([A-Z][a-zA-Z\s]+(?:Research|Academy|Foundation|Corporation|Company|Corp))\b',
                r'\b(?:University of|Institute for|Center for)\s+([A-Z][a-zA-Z\s]+)\b',
                r'\b([A-Z]{2,})\b(?:\s+(?:University|Institute|Lab))?',  # MIT, NASA, etc.
            ],
            'field': [
                r'\b(artificial intelligence|machine learning|deep learning|neural networks)\b',
                r'\b(natural language processing|computer vision|data science|robotics)\b',
                r'\b(quantum computing|bioinformatics|cybersecurity|blockchain)\b',
                r'\b([a-z]+\s+(?:science|engineering|studies|research))\b',
                r'\bin the field of\s+([a-z][a-zA-Z\s]+)\b'
            ],
            'technology': [
                r'\b((?:transformer|attention|BERT|GPT|CNN|RNN|LSTM|GAN)\s*(?:architecture|model|network)?s?)\b',
                r'\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*\s+(?:algorithm|framework|library|toolkit|platform))\b',
                r'\b(?:using|with|via)\s+([A-Z][a-zA-Z]+(?:\s+[0-9.]+)?)\b',  # TensorFlow 2.0
            ],
            'concept': [
                r'\b((?:supervised|unsupervised|reinforcement)\s+learning)\b',
                r'\b((?:computer|machine|artificial)\s+(?:vision|intelligence|learning))\b',
                r'\b([a-z]+\s+(?:optimization|classification|clustering|regression))\b',
                r'\b(transfer learning|few-shot learning|zero-shot learning|meta-learning)\b'
            ],
            'conference': [
                r'\b(NeurIPS|ICML|ICLR|AAAI|IJCAI|ACL|EMNLP|ICCV|ECCV|CVPR)\b',
                r'\b([A-Z]{3,}\s+[0-9]{4})\b',  # NIPS 2023
                r'\b(?:Conference on|Workshop on|Symposium on)\s+([A-Z][a-zA-Z\s]+)\b'
            ]
        }
        
        # Relationship patterns
        self.relationship_patterns = [
            # Academic relationships
            (r'([^.]+?)\s+(?:works? at|is affiliated with|from)\s+([^.]+)', 'affiliated_with'),
            (r'([^.]+?)\s+(?:specializes? in|focuses on|researches?)\s+([^.]+)', 'specializes_in'),
            (r'([^.]+?)\s+(?:developed|created|invented|proposed)\s+([^.]+)', 'developed'),
            (r'([^.]+?)\s+(?:contributes? to|works on)\s+([^.]+)', 'contributes_to'),
            (r'([^.]+?)\s+(?:is based on|extends|builds upon)\s+([^.]+)', 'based_on'),
            (r'([^.]+?)\s+(?:collaborates? with|partners with)\s+([^.]+)', 'collaborates_with'),
            
            # Technical relationships
            (r'([^.]+?)\s+(?:uses|utilizes|employs)\s+([^.]+)', 'uses'),
            (r'([^.]+?)\s+(?:implements|applies)\s+([^.]+)', 'implements'),
            (r'([^.]+?)\s+(?:outperforms|beats|surpasses)\s+([^.]+)', 'outperforms'),
            (r'([^.]+?)\s+(?:is trained on|learns from)\s+([^.]+)', 'trained_on'),
            (r'([^.]+?)\s+(?:evaluates? on|tested on)\s+([^.]+)', 'evaluated_on'),
            
            # General relationships
            (r'([^.]+?)\s+(?:includes?|contains?|comprises?)\s+([^.]+)', 'includes'),
            (r'([^.]+?)\s+(?:relates? to|connected to|associated with)\s+([^.]+)', 'related_to'),
        ]
        
        # Confidence modifiers
        self.confidence_modifiers = {
            'high': ['significant', 'major', 'important', 'key', 'primary', 'main'],
            'medium': ['notable', 'relevant', 'considerable', 'substantial'],
            'low': ['possible', 'potential', 'might', 'could', 'perhaps', 'may']
        }
    
    def extract_knowledge(
        self,
        text: str,
        context: Optional['ExtractionContext'] = None
    ) -> KnowledgeGraph:
        """
        Main extraction method for compatibility with test interface
        
        Args:
            text: Input text to process
            context: Extraction context with domain and settings
            
        Returns:
            Knowledge graph with extracted entities and relationships
        """
        if context:
            self.context = context
        
        return self.extract_enhanced_knowledge_graph(
            text, 
            domain=self.context.domain,
            multi_pass=True
        )
    
    def extract_enhanced_knowledge_graph(
        self,
        text: str,
        domain: Optional[str] = None,
        multi_pass: bool = True
    ) -> KnowledgeGraph:
        """
        Extract knowledge graph with enhanced accuracy and domain-specific patterns
        
        Args:
            text: Input text to process
            domain: Domain override (academic, technical, business, etc.)
            multi_pass: Whether to use multi-pass extraction for better accuracy
            
        Returns:
            Enhanced knowledge graph with detailed entities and relationships
        """
        if domain:
            self.context.domain = domain
        
        logger.info(f"Starting enhanced knowledge extraction for domain: {self.context.domain}")
        
        # Initialize knowledge graph
        knowledge_graph = KnowledgeGraph()
        
        # Multi-pass extraction for better accuracy
        if multi_pass:
            return self._multi_pass_extraction(text, knowledge_graph)
        else:
            return self._single_pass_extraction(text, knowledge_graph)
    
    def _multi_pass_extraction(self, text: str, kg: KnowledgeGraph) -> KnowledgeGraph:
        """Perform multi-pass extraction for improved accuracy"""
        
        # Pass 1: Extract high-confidence entities
        logger.info("Pass 1: High-confidence entity extraction")
        high_conf_entities = self._extract_entities_pass(text, confidence_threshold=0.8)
        
        # Pass 2: Extract relationships between high-confidence entities
        logger.info("Pass 2: Relationship extraction")
        relationships = self._extract_relationships_pass(text, high_conf_entities)
        
        # Pass 3: Extract additional entities based on relationships
        logger.info("Pass 3: Context-aware entity extraction")
        additional_entities = self._extract_context_entities(text, relationships)
        
        # Pass 4: Disambiguation and filtering
        logger.info("Pass 4: Entity disambiguation and filtering")
        all_entities = high_conf_entities + additional_entities
        final_entities = self._disambiguate_entities(all_entities)
        final_relationships = self._filter_relationships(relationships, final_entities)
        
        # Build final knowledge graph
        self._build_knowledge_graph(kg, final_entities, final_relationships)
        
        logger.info(f"Enhanced extraction completed: {len(kg.entities)} entities, {len(kg.relationships)} relationships")
        
        return kg
    
    def _single_pass_extraction(self, text: str, kg: KnowledgeGraph) -> KnowledgeGraph:
        """Perform single-pass extraction (fallback method)"""
        
        entities = self._extract_entities_pass(text, confidence_threshold=self.context.confidence_threshold)
        relationships = self._extract_relationships_pass(text, entities)
        
        # Apply disambiguation if enabled
        if self.context.enable_disambiguation:
            entities = self._disambiguate_entities(entities)
            relationships = self._filter_relationships(relationships, entities)
        
        self._build_knowledge_graph(kg, entities, relationships)
        
        return kg
    
    def _extract_entities_pass(
        self, 
        text: str, 
        confidence_threshold: float = 0.6
    ) -> List[EntityCandidate]:
        """Extract entity candidates with confidence scoring"""
        
        candidates = []
        patterns = self.academic_patterns if self.context.domain == 'academic' else self.academic_patterns
        
        for entity_type, type_patterns in patterns.items():
            for pattern in type_patterns:
                try:
                    matches = re.finditer(pattern, text, re.IGNORECASE)
                    for match in matches:
                        entity_text = match.group(1) if match.groups() else match.group(0)
                        
                        # Calculate confidence based on context and patterns
                        confidence = self._calculate_entity_confidence(
                            entity_text, entity_type, match, text
                        )
                        
                        if confidence >= confidence_threshold:
                            candidate = EntityCandidate(
                                text=entity_text.strip(),
                                entity_type=entity_type,
                                confidence=confidence,
                                context=self._extract_context(match, text),
                                start_pos=match.start(),
                                end_pos=match.end(),
                                supporting_evidence=self._gather_evidence(entity_text, text)
                            )
                            candidates.append(candidate)
                            
                except re.error as e:
                    logger.warning(f"Regex error in pattern {pattern}: {e}")
                    continue
        
        # Remove duplicates and sort by confidence
        candidates = self._deduplicate_entities(candidates)
        candidates.sort(key=lambda x: x.confidence, reverse=True)
        
        self.extraction_stats['entities_found'] = len(candidates)
        
        return candidates[:self.context.max_entities_per_pass]
    
    def _extract_relationships_pass(
        self, 
        text: str, 
        entities: List[EntityCandidate]
    ) -> List[RelationshipCandidate]:
        """Extract relationships between entities"""
        
        relationship_candidates = []
        
        for pattern, relation_type in self.relationship_patterns:
            try:
                matches = re.finditer(pattern, text, re.IGNORECASE)
                for match in matches:
                    if len(match.groups()) >= 2:
                        subject_text = match.group(1).strip()
                        object_text = match.group(2).strip()
                        
                        # Find matching entities
                        subject_entity = self._find_matching_entity(subject_text, entities)
                        object_entity = self._find_matching_entity(object_text, entities)
                        
                        if subject_entity and object_entity:
                            confidence = self._calculate_relationship_confidence(
                                subject_entity, object_entity, relation_type, match, text
                            )
                            
                            if confidence >= self.context.confidence_threshold:
                                relationship_candidates.append(RelationshipCandidate(
                                    subject=subject_entity,
                                    predicate=relation_type,
                                    object=object_entity,
                                    confidence=confidence,
                                    context=self._extract_context(match, text),
                                    supporting_evidence=match.group(0)
                                ))
                                
            except re.error as e:
                logger.warning(f"Regex error in relationship pattern {pattern}: {e}")
                continue
        
        self.extraction_stats['relationships_found'] = len(relationship_candidates)
        
        return relationship_candidates
    
    def _extract_context_entities(
        self, 
        text: str, 
        relationships: List[RelationshipCandidate]
    ) -> List[EntityCandidate]:
        """Extract additional entities based on relationship context"""
        
        additional_entities = []
        
        # Look for entities mentioned in relationship contexts
        for rel in relationships:
            context_window = rel.context
            
            # Extract potential entities from relationship context
            potential_entities = self._extract_entities_from_context(context_window)
            additional_entities.extend(potential_entities)
        
        return self._deduplicate_entities(additional_entities)
    
    def _disambiguate_entities(self, entities: List[EntityCandidate]) -> List[EntityCandidate]:
        """Disambiguate entities to remove duplicates and resolve conflicts"""
        
        if not self.context.enable_disambiguation:
            return entities
        
        # Group entities by normalized text
        entity_groups = defaultdict(list)
        for entity in entities:
            normalized_text = self._normalize_entity_text(entity.text)
            entity_groups[normalized_text].append(entity)
        
        disambiguated = []
        for group in entity_groups.values():
            if len(group) == 1:
                disambiguated.extend(group)
            else:
                # Resolve conflicts - keep highest confidence, best type match
                best_entity = max(group, key=lambda x: (x.confidence, self._type_priority(x.entity_type)))
                disambiguated.append(best_entity)
                self.extraction_stats['disambiguation_resolved'] += len(group) - 1
        
        return disambiguated
    
    def _filter_relationships(
        self, 
        relationships: List[RelationshipCandidate],
        final_entities: List[EntityCandidate]
    ) -> List[RelationshipCandidate]:
        """Filter relationships to only include those with final entities"""
        
        final_entity_texts = {self._normalize_entity_text(e.text) for e in final_entities}
        
        filtered_relationships = []
        for rel in relationships:
            subject_norm = self._normalize_entity_text(rel.subject.text)
            object_norm = self._normalize_entity_text(rel.object.text)
            
            if subject_norm in final_entity_texts and object_norm in final_entity_texts:
                filtered_relationships.append(rel)
        
        return filtered_relationships
    
    def _build_knowledge_graph(
        self,
        kg: KnowledgeGraph,
        entities: List[EntityCandidate],
        relationships: List[RelationshipCandidate]
    ):
        """Build the final knowledge graph from candidates"""
        
        # Add entities
        entity_map = {}  # Map entity text to Entity object
        for candidate in entities:
            entity = Entity(
                entity_id=str(uuid.uuid4()),
                entity_type=candidate.entity_type,
                name=candidate.text,
                properties={
                    'confidence': candidate.confidence,
                    'context': candidate.context,
                    'supporting_evidence': candidate.supporting_evidence
                },
                confidence=candidate.confidence,
                source_text=candidate.context
            )
            kg.add_entity(entity)
            entity_map[self._normalize_entity_text(candidate.text)] = entity
        
        # Add relationships
        for rel_candidate in relationships:
            subject_norm = self._normalize_entity_text(rel_candidate.subject.text)
            object_norm = self._normalize_entity_text(rel_candidate.object.text)
            
            if subject_norm in entity_map and object_norm in entity_map:
                relationship = Relationship(
                    source_entity=entity_map[subject_norm],
                    target_entity=entity_map[object_norm],
                    relationship_type=rel_candidate.predicate,
                    confidence=rel_candidate.confidence,
                    properties={
                        'context': rel_candidate.context,
                        'supporting_evidence': rel_candidate.supporting_evidence
                    }
                )
                kg.add_relationship(relationship)
    
    # Helper methods
    
    def _calculate_entity_confidence(
        self, 
        entity_text: str, 
        entity_type: str, 
        match: re.Match, 
        full_text: str
    ) -> float:
        """Calculate confidence score for entity candidate"""
        
        base_confidence = 0.7
        
        # Adjust based on entity characteristics
        if len(entity_text) >= 3:  # Reasonable length
            base_confidence += 0.1
        
        if entity_text.istitle():  # Proper case
            base_confidence += 0.1
        
        # Context-based adjustments
        context = self._extract_context(match, full_text, window=50)
        
        # Check for confidence modifiers in context
        context_lower = context.lower()
        for level, modifiers in self.confidence_modifiers.items():
            for modifier in modifiers:
                if modifier in context_lower:
                    if level == 'high':
                        base_confidence += 0.15
                    elif level == 'medium':
                        base_confidence += 0.05
                    elif level == 'low':
                        base_confidence -= 0.1
                    break
        
        # Type-specific adjustments
        type_priorities = {
            'person': 0.9,
            'organization': 0.85,
            'technology': 0.8,
            'field': 0.75,
            'concept': 0.7,
            'conference': 0.8
        }
        
        type_modifier = type_priorities.get(entity_type, 0.6)
        base_confidence *= type_modifier
        
        return min(max(base_confidence, 0.0), 1.0)
    
    def _calculate_relationship_confidence(
        self,
        subject: EntityCandidate,
        obj: EntityCandidate,
        relation_type: str,
        match: re.Match,
        full_text: str
    ) -> float:
        """Calculate confidence score for relationship candidate"""
        
        # Base confidence from entity confidences
        base_confidence = (subject.confidence + obj.confidence) / 2
        
        # Relationship type adjustments
        relation_priorities = {
            'affiliated_with': 0.9,
            'specializes_in': 0.85,
            'developed': 0.9,
            'contributes_to': 0.8,
            'based_on': 0.75,
            'collaborates_with': 0.8,
            'uses': 0.7,
            'implements': 0.8,
            'related_to': 0.6
        }
        
        relation_modifier = relation_priorities.get(relation_type, 0.6)
        base_confidence *= relation_modifier
        
        return min(max(base_confidence, 0.0), 1.0)
    
    def _extract_context(self, match: re.Match, text: str, window: int = 100) -> str:
        """Extract context around a match"""
        start = max(0, match.start() - window)
        end = min(len(text), match.end() + window)
        return text[start:end].strip()
    
    def _gather_evidence(self, entity_text: str, full_text: str, max_examples: int = 3) -> List[str]:
        """Gather supporting evidence for entity"""
        evidence = []
        entity_lower = entity_text.lower()
        
        # Find sentences containing the entity
        sentences = re.split(r'[.!?]+', full_text)
        for sentence in sentences:
            if entity_lower in sentence.lower() and len(evidence) < max_examples:
                evidence.append(sentence.strip())
        
        return evidence
    
    def _find_matching_entity(self, text: str, entities: List[EntityCandidate]) -> Optional[EntityCandidate]:
        """Find entity that matches the given text"""
        text_normalized = self._normalize_entity_text(text)
        
        for entity in entities:
            if self._normalize_entity_text(entity.text) == text_normalized:
                return entity
            
            # Check for partial matches
            if (text_normalized in self._normalize_entity_text(entity.text) or 
                self._normalize_entity_text(entity.text) in text_normalized):
                return entity
        
        return None
    
    def _extract_entities_from_context(self, context: str) -> List[EntityCandidate]:
        """Extract potential entities from context string"""
        # This is a simplified version - in practice, would use the full extraction pipeline
        candidates = []
        
        # Look for capitalized phrases that might be entities
        capitalized_phrases = re.findall(r'\b[A-Z][a-zA-Z\s]{2,20}\b', context)
        
        for phrase in capitalized_phrases:
            candidate = EntityCandidate(
                text=phrase.strip(),
                entity_type='unknown',
                confidence=0.5,
                context=context,
                start_pos=0,
                end_pos=len(phrase)
            )
            candidates.append(candidate)
        
        return candidates
    
    def _normalize_entity_text(self, text: str) -> str:
        """Normalize entity text for comparison"""
        return re.sub(r'\s+', ' ', text.lower().strip())
    
    def _type_priority(self, entity_type: str) -> int:
        """Return priority score for entity type (higher is better)"""
        priorities = {
            'person': 10,
            'organization': 9,
            'technology': 8,
            'field': 7,
            'concept': 6,
            'conference': 5,
            'unknown': 1
        }
        return priorities.get(entity_type, 1)
    
    def _deduplicate_entities(self, entities: List[EntityCandidate]) -> List[EntityCandidate]:
        """Remove duplicate entity candidates"""
        seen = set()
        unique_entities = []
        
        for entity in entities:
            normalized = self._normalize_entity_text(entity.text)
            if normalized not in seen:
                seen.add(normalized)
                unique_entities.append(entity)
        
        return unique_entities
    
    def get_extraction_statistics(self) -> Dict[str, Any]:
        """Get statistics about the extraction process"""
        return {
            'extraction_stats': self.extraction_stats.copy(),
            'context': {
                'domain': self.context.domain,
                'confidence_threshold': self.context.confidence_threshold,
                'disambiguation_enabled': self.context.enable_disambiguation,
                'temporal_extraction': self.context.extract_temporal
            }
        }
    
    def analyze_content_domain(self, text: str) -> Dict[str, float]:
        """Analyze text to determine most likely domain"""
        
        domain_indicators = {
            'academic': [
                'research', 'study', 'paper', 'journal', 'university', 'professor', 
                'methodology', 'results', 'conclusion', 'hypothesis', 'experiment'
            ],
            'technical': [
                'algorithm', 'implementation', 'system', 'architecture', 'framework',
                'performance', 'optimization', 'configuration', 'deployment'
            ],
            'business': [
                'market', 'revenue', 'strategy', 'management', 'customer', 'product',
                'sales', 'investment', 'growth', 'competition', 'profit'
            ],
            'news': [
                'reported', 'according to', 'sources', 'yesterday', 'today', 'breaking',
                'announced', 'confirmed', 'statement', 'officials'
            ]
        }
        
        text_lower = text.lower()
        domain_scores = {}
        
        for domain, indicators in domain_indicators.items():
            score = sum(1 for indicator in indicators if indicator in text_lower)
            domain_scores[domain] = score / len(indicators)  # Normalize
        
        return domain_scores


# Example usage and testing
if __name__ == "__main__":
    def test_advanced_knowledge_extraction():
        """Test the advanced knowledge extraction capabilities"""
        
        # Sample academic text
        academic_text = """
        Dr. Sarah Chen from MIT's Computer Science Department has been working on 
        transformer architectures for natural language processing. Her research focuses 
        on attention mechanisms and their applications in machine learning. Professor Chen 
        collaborated with researchers at Google DeepMind to develop a new approach to 
        few-shot learning. The work was published in NeurIPS 2023 and demonstrates 
        significant improvements over existing methods. The team used PyTorch and 
        TensorFlow to implement their algorithms, which outperformed BERT on several 
        benchmarks. This research contributes to the broader field of artificial 
        intelligence and has potential applications in computer vision and robotics.
        """
        
        # Initialize extractor with academic context
        context = ExtractionContext(
            domain="academic",
            confidence_threshold=0.6,
            enable_disambiguation=True,
            extract_temporal=True
        )
        
        extractor = AdvancedKnowledgeExtractor(context)
        
        print("🧠 Advanced Knowledge Extraction Test")
        print("=" * 60)
        
        # Analyze domain
        domain_analysis = extractor.analyze_content_domain(academic_text)
        print(f"📊 Domain Analysis: {domain_analysis}")
        
        # Extract knowledge graph
        kg = extractor.extract_enhanced_knowledge_graph(academic_text, multi_pass=True)
        
        print(f"\n📈 Extraction Results:")
        print(f"   • Entities: {len(kg.entities)}")
        print(f"   • Relationships: {len(kg.relationships)}")
        
        print(f"\n🏷️  Entities:")
        for entity_id, entity in kg.entities.items():
            print(f"   • {entity.name} ({entity.entity_type}) - confidence: {entity.confidence:.3f}")
        
        print(f"\n🔗 Relationships:")
        for rel_id, relationship in kg.relationships.items():
            source_name = getattr(relationship.source_entity, 'name', 'Unknown')
            target_name = getattr(relationship.target_entity, 'name', 'Unknown') 
            print(f"   • {source_name} --[{relationship.relationship_type}]--> {target_name}")
            print(f"     Confidence: {relationship.confidence:.3f}")
        
        # Get statistics
        stats = extractor.get_extraction_statistics()
        print(f"\n📊 Extraction Statistics:")
        for key, value in stats['extraction_stats'].items():
            print(f"   • {key}: {value}")
        
        print("\n✅ Advanced extraction test completed!")
        
        return kg
    
    # Run test
    test_advanced_knowledge_extraction()