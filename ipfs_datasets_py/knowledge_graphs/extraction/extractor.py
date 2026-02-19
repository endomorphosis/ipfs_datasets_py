"""
Knowledge Graph Extractor Module

This module provides the KnowledgeGraphExtractor class for extracting structured
knowledge graphs from unstructured text. It handles entity and relationship 
extraction, confidence scoring, and supports Wikipedia integration with SPARQL
validation against Wikidata.

Key Features:
- Rule-based and model-based entity extraction (spaCy, Transformers)
- Relationship extraction using patterns
- Temperature-controlled extraction parameters
- Wikipedia page extraction
- Wikidata SPARQL validation
- Detailed tracing through WikipediaKnowledgeGraphTracer integration
"""

import re
import requests
import logging
from typing import Dict, List, Any, Optional, Tuple

# Import extraction package components
from .entities import Entity
from .relationships import Relationship
from .graph import KnowledgeGraph
from .relation_patterns import _default_relation_patterns

# Import custom exceptions
from ..exceptions import (
    EntityExtractionError,
    RelationshipExtractionError,
    ValidationError
)

# Import the Wikipedia knowledge graph tracer for enhanced tracing capabilities
from ipfs_datasets_py.ml.llm.llm_reasoning_tracer import WikipediaKnowledgeGraphTracer

# Helper functions extracted to a focused module (Workstream I — reduce god modules).
# They are re-imported here so existing callers are unaffected.
from ._entity_helpers import (  # noqa: F401 (re-exported for backward compat)
    _map_spacy_entity_type,
    _map_transformers_entity_type,
    _rule_based_entity_extraction,
    _string_similarity,
)
from ._wikipedia_helpers import WikipediaExtractionMixin

# Set up logging
logger = logging.getLogger(__name__)


# Main Extractor Class

class KnowledgeGraphExtractor(WikipediaExtractionMixin):
    """
    Extracts knowledge graphs from text.

    Uses rule-based and optionally model-based approaches to extract
    entities and relationships from text. Supports Wikipedia integration for
    extracting knowledge graphs from Wikipedia pages and SPARQL validation
    against Wikidata's structured data. Includes detailed tracing functionality
    through integration with WikipediaKnowledgeGraphTracer.

    Key Features:
    - Extraction of entities and relationships from text with confidence scoring
    - Temperature-controlled extraction with tunable parameters
    - Wikipedia integration for extracting knowledge graphs from Wikipedia pages
    - SPARQL validation against Wikidata's structured data
    - Detailed tracing of extraction and validation reasoning
    """

    def __init__(
        self,
        use_spacy: bool = False,
        use_transformers: bool = False,
        relation_patterns: Optional[List[Dict[str, Any]]] = None,
        min_confidence: float = 0.5,
        use_tracer: bool = True
    ):
        """
        Initialize the knowledge graph extractor.

        Args:
            use_spacy (bool): Whether to use spaCy for extraction
            use_transformers (bool): Whether to use Transformers for extraction
            relation_patterns (List[Dict], optional): Custom relation extraction patterns
            min_confidence (float): Minimum confidence threshold for extraction
            use_tracer (bool): Whether to use the WikipediaKnowledgeGraphTracer
        """
        self.use_spacy = use_spacy
        self.use_transformers = use_transformers
        self.min_confidence = min_confidence
        self.use_tracer = use_tracer

        # Initialize the Wikipedia knowledge graph tracer if enabled
        self.tracer = WikipediaKnowledgeGraphTracer() if use_tracer else None

        # Initialize NLP tools if requested
        self.nlp = None
        self.ner_model = None
        self.re_model = None

        if use_spacy:
            try:
                # spaCy is an optional dependency - install with:
                # pip install "ipfs_datasets_py[knowledge_graphs]"
                # python -m spacy download en_core_web_sm
                import spacy
                try:
                    self.nlp = spacy.load("en_core_web_sm")
                except (OSError, IOError) as e:
                    # If the model is not available, download it
                    logger.warning("spaCy model 'en_core_web_sm' not found (%s) — downloading...", e)
                    spacy.cli.download("en_core_web_sm")
                    self.nlp = spacy.load("en_core_web_sm")
            except ImportError:
                logger.warning(
                    "spaCy not installed — running in rule-based mode only. "
                    "Install with: pip install 'ipfs_datasets_py[knowledge_graphs]' "
                    "then run: python -m spacy download en_core_web_sm"
                )
                self.use_spacy = False

        if use_transformers:
            try:
                from transformers import pipeline
                self.ner_model = pipeline("ner")
                self.re_model = pipeline("text-classification",
                                        model="Rajkumar-Murugesan/roberta-base-finetuned-tacred-relation")
            except ImportError:
                logger.warning(
                    "transformers not installed — running without transformer models. "
                    "Install with: pip install transformers"
                )
                self.use_transformers = False

        # Initialize relation patterns
        self.relation_patterns = relation_patterns or _default_relation_patterns()


    def extract_entities(self, text: str) -> List[Entity]:
        """
        Extract entities from text.

        Args:
            text (str): Text to extract entities from

        Returns:
            List[Entity]: List of extracted entities
        """
        entities = []

        # Use different methods based on available tools
        if self.use_spacy and self.nlp:
            # Use spaCy for NER
            doc = self.nlp(text)

            for ent in doc.ents:
                # Map spaCy entity types to our entity types
                entity_type = _map_spacy_entity_type(ent.label_)

                # Skip entities with low confidence
                if ent._.get("confidence", 1.0) < self.min_confidence:
                    continue

                # Create entity
                entity = Entity(
                    entity_type=entity_type,
                    name=ent.text,
                    confidence=ent._.get("confidence", 0.8),
                    source_text=text[max(0, ent.start_char - 20):min(len(text), ent.end_char + 20)]
                )

                # Add to entities list
                entities.append(entity)

        elif self.use_transformers and self.ner_model:
            # Use Transformers for NER
            try:
                ner_results = self.ner_model(text)

                # Group results by entity
                entity_groups = {}
                for result in ner_results:
                    if result["score"] < self.min_confidence:
                        continue

                    entity_text = result["word"]
                    entity_type = _map_transformers_entity_type(result["entity"])

                    # Use entity text as key to group entities
                    if entity_text not in entity_groups:
                        entity_groups[entity_text] = {
                            "type": entity_type,
                            "confidence": result["score"]
                        }
                    elif result["score"] > entity_groups[entity_text]["confidence"]:
                        # Update if confidence is higher
                        entity_groups[entity_text] = {
                            "type": entity_type,
                            "confidence": result["score"]
                        }

                # Create entities from groups
                for entity_text, entity_info in entity_groups.items():
                    entity = Entity(
                        entity_type=entity_info["type"],
                        name=entity_text,
                        confidence=entity_info["confidence"],
                        source_text=text
                    )

                    entities.append(entity)

            except (ImportError, AttributeError, ValueError) as e:
                logger.warning(f"Transformers NER failed: {e}. Falling back to rule-based extraction.")
                # Fall back to rule-based extraction
                entities.extend(_rule_based_entity_extraction(text))
            except Exception as e:
                # Unexpected error - wrap in EntityExtractionError
                raise EntityExtractionError(
                    f"Failed to extract entities using transformers: {e}",
                    details={
                        'operation': 'entity_extraction',
                        'text_length': len(text),
                        'use_transformers': True,
                        'error_class': type(e).__name__,
                        'remediation': "Check that the transformers pipeline is loaded correctly; "
                                       "fall back with use_transformers=False.",
                    }
                ) from e
        else:
            # Use rule-based entity extraction
            entities.extend(_rule_based_entity_extraction(text))

        return entities






    def extract_relationships(self, text: str, entities: List[Entity]) -> List[Relationship]:
        """Extract relationships between entities from text.

        Args:
            text (str): Text to extract relationships from
            entities (List[Entity]): List of entities to consider

        Returns:
            List[Relationship]: List of extracted relationships
        """
        relationships = []

        # Create a map from entity names to entities
        entity_map = {}
        for entity in entities:
            entity_map[entity.name] = entity

        # Use different methods based on available tools
        if self.use_transformers and self.re_model:
            # Neural relationship extraction using transformer models
            # Implemented in v2.5.0 - Uses REBEL or similar models for end-to-end relation extraction
            try:
                neural_relationships = self._neural_relationship_extraction(text, entity_map)
                relationships.extend(neural_relationships)
            except RelationshipExtractionError as e:
                logger.warning(f"Neural relationship extraction failed: {e}. Falling back to rule-based.")
        
        # Use rule-based relationship extraction (always runs as fallback or primary)
        relationships.extend(self._rule_based_relationship_extraction(text, entity_map))

        return relationships
    
    def _neural_relationship_extraction(self, text: str, entity_map: Dict[str, Entity]) -> List[Relationship]:
        """Extract relationships using neural transformer models.
        
        This method uses pre-trained transformer models for end-to-end relationship extraction.
        Supports models like REBEL, LUKE, or other relation extraction models from HuggingFace.
        
        Args:
            text (str): Text to extract relationships from
            entity_map (Dict): Map from entity names to Entity objects
            
        Returns:
            List[Relationship]: List of extracted relationships with confidence scores
            
        Note:
            Requires transformers library and a loaded relation extraction model.
            Falls back gracefully if model is not available.
        """
        relationships = []
        
        if not self.re_model:
            return relationships
        
        try:
            # Try REBEL-style triplet extraction if available
            # REBEL outputs triplets in format: (subject, relation, object)
            from transformers import pipeline
            
            # Check if we have a triplet extraction model
            if hasattr(self.re_model, 'task') and 'text2text' in str(self.re_model.task):
                # REBEL-style generation model
                triplets = self.re_model(text, max_length=512)
                
                # Parse triplets (format varies by model)
                # REBEL format: "<triplet> subject <subj> relation <obj> object"
                if isinstance(triplets, list) and len(triplets) > 0:
                    generated_text = triplets[0].get('generated_text', '')
                    parsed_triplets = self._parse_rebel_output(generated_text)
                    
                    for subject, relation, obj in parsed_triplets:
                        # Find matching entities
                        source_entity = self._find_best_entity_match(subject, entity_map)
                        target_entity = self._find_best_entity_match(obj, entity_map)
                        
                        if source_entity and target_entity and source_entity != target_entity:
                            rel = Relationship(
                                relationship_type=relation,
                                source_entity=source_entity,
                                target_entity=target_entity,
                                confidence=0.85,  # Neural models typically have high confidence
                                source_text=text[:200],  # Context snippet
                                extraction_method='neural'
                            )
                            relationships.append(rel)
            
            else:
                # Classification-based relation extraction
                # Split text into sentence chunks for processing
                sentences = text.split('. ')
                
                for sentence in sentences[:10]:  # Limit to first 10 sentences for efficiency
                    if len(sentence.strip()) < 10:
                        continue
                    
                    # Extract relationships from sentence
                    # This approach works with models trained on datasets like TACRED
                    try:
                        result = self.re_model(sentence)
                        if isinstance(result, list) and len(result) > 0:
                            top_result = result[0]
                            relation_label = top_result.get('label', 'related_to')
                            confidence = top_result.get('score', 0.7)
                            
                            # Only include high-confidence relationships
                            if confidence > 0.6:
                                # Try to extract entities from the sentence
                                sentence_entities = [e for e in entity_map.values()
                                                   if e.name.lower() in sentence.lower()]
                                
                                # Create relationships between entities in the sentence
                                if len(sentence_entities) >= 2:
                                    rel = Relationship(
                                        relationship_type=relation_label,
                                        source_entity=sentence_entities[0],
                                        target_entity=sentence_entities[1],
                                        confidence=confidence,
                                        source_text=sentence,
                                        extraction_method='neural'
                                    )
                                    relationships.append(rel)
                    except (TypeError, ValueError, KeyError, IndexError, AttributeError) as e:
                        logger.debug(f"Failed to process sentence with neural model: {e}")
                        continue
        
        except (ImportError, AttributeError, TypeError, ValueError, KeyError, IndexError) as e:
            logger.warning(f"Neural relationship extraction encountered an error: {e}")
            # Return whatever we extracted so far
            return relationships

        except Exception as e:
            raise RelationshipExtractionError(
                f"Neural relationship extraction failed: {e}",
                details={
                    'operation': 'relationship_extraction',
                    'text_length': len(text),
                    'entity_count': len(entity_map),
                    'error_class': type(e).__name__,
                    'remediation': "Check that the NER/RE pipeline is loaded; "
                                   "set use_transformers=False to use rule-based extraction.",
                }
            ) from e
        
        return relationships
    
    def _parse_rebel_output(self, generated_text: str) -> List[Tuple[str, str, str]]:
        """Parse REBEL model output into triplets.
        
        Args:
            generated_text: Generated text from REBEL model
            
        Returns:
            List of (subject, relation, object) tuples
        """
        triplets = []
        
        try:
            # REBEL format: "<triplet> subject <subj> relation <obj> object <triplet> ..."
            # Split by <triplet> marker
            parts = generated_text.split('<triplet>')
            
            for part in parts:
                if not part.strip():
                    continue
                
                # Extract subject, relation, object
                if '<subj>' in part and '<obj>' in part:
                    try:
                        subject = part.split('<subj>')[0].strip()
                        rest = part.split('<subj>')[1]
                        relation = rest.split('<obj>')[0].strip()
                        obj = rest.split('<obj>')[1].strip()
                        
                        if subject and relation and obj:
                            triplets.append((subject, relation, obj))
                    except (IndexError, ValueError):
                        continue
        
        except (AttributeError, ValueError, TypeError) as e:
            logger.debug(f"Failed to parse REBEL output: {e}")
        
        return triplets

    def _rule_based_relationship_extraction(self, text: str, entity_map: Dict[str, Entity]) -> List[Relationship]:
        """Extract relationships using rule-based patterns.

        Args:
            text (str): Text to extract relationships from
            entity_map (Dict): Map from entity names to Entity objects

        Returns:
            List[Relationship]: List of extracted relationships
        """
        relationships = []

        # Apply relationship patterns
        for pattern_info in self.relation_patterns:
            pattern = pattern_info["pattern"]
            relation_type = pattern_info["name"]
            # Note: source_type and target_type are available in pattern_info but not currently used
            # They could be used for type validation in future enhancements:
            # source_type = pattern_info["source_type"]
            # target_type = pattern_info["target_type"]
            confidence = pattern_info.get("confidence", 0.7)
            bidirectional = pattern_info.get("bidirectional", False)

            # Find matches
            try:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    # Check if the pattern has exactly 2 groups
                    if len(match.groups()) < 2:
                        continue
                        
                    source_text = match.group(1).strip()
                    target_text = match.group(2).strip()

                    # Look for entities that match or contain the matched text
                    source_entity = self._find_best_entity_match(source_text, entity_map)
                    target_entity = self._find_best_entity_match(target_text, entity_map)

                    if source_entity and target_entity and source_entity != target_entity:
                        # Create relationship
                        rel = Relationship(
                            relationship_type=relation_type,
                            source_entity=source_entity,
                            target_entity=target_entity,
                            confidence=confidence,
                            source_text=text[max(0, match.start() - 20):min(len(text), match.end() + 20)],
                            bidirectional=bidirectional
                        )

                        relationships.append(rel)
            
            except (re.error, ValueError) as e:
                # Pattern matching error - log and skip this pattern
                logger.warning(f"Skipping problematic relationship pattern '{pattern_info.get('name', 'unknown')}': {e}")
                continue
            except Exception as e:
                # Unexpected error in relationship extraction
                raise RelationshipExtractionError(
                    f"Failed to extract relationships using pattern '{pattern_info.get('name', 'unknown')}': {e}",
                    details={'pattern': pattern_info.get('pattern', ''), 'text_length': len(text)}
                ) from e

        return relationships
    
    def _aggressive_entity_extraction(self, text: str, existing_entities: List[Entity]) -> List[Entity]:
        """Extract additional entities using aggressive spaCy techniques.
        
        Uses dependency parsing, compound noun extraction, and advanced NER patterns
        to find entities that might be missed by standard extraction.
        
        Args:
            text: Text to extract from
            existing_entities: Already extracted entities (to avoid duplicates)
            
        Returns:
            List of additional entities
        """
        additional_entities = []
        
        if not self.nlp:
            return additional_entities
        
        try:
            doc = self.nlp(text)
            existing_names = {e.name.lower() for e in existing_entities}
            
            # 1. Extract compound nouns using dependency parsing
            for chunk in doc.noun_chunks:
                chunk_text = chunk.text.strip()
                if len(chunk_text) > 2 and chunk_text.lower() not in existing_names:
                    # Check if it's a meaningful compound noun
                    if len(chunk) >= 2 or chunk.root.pos_ in ['PROPN', 'NOUN']:
                        entity = Entity(
                            name=chunk_text,
                            entity_type='concept',
                            confidence=0.6,
                            extraction_method='dependency_parsing'
                        )
                        additional_entities.append(entity)
                        existing_names.add(chunk_text.lower())
            
            # 2. Extract entities based on syntactic patterns
            # Look for subjects and objects in sentences
            for token in doc:
                # Subject entities
                if token.dep_ in ['nsubj', 'nsubjpass'] and token.pos_ in ['NOUN', 'PROPN']:
                    # Get the full noun phrase
                    subtree = ' '.join([t.text for t in token.subtree])
                    if len(subtree) > 2 and subtree.lower() not in existing_names:
                        entity = Entity(
                            name=subtree.strip(),
                            entity_type='agent',
                            confidence=0.65,
                            extraction_method='syntax_pattern'
                        )
                        additional_entities.append(entity)
                        existing_names.add(subtree.lower())
                
                # Object entities
                elif token.dep_ in ['dobj', 'pobj'] and token.pos_ in ['NOUN', 'PROPN']:
                    subtree = ' '.join([t.text for t in token.subtree])
                    if len(subtree) > 2 and subtree.lower() not in existing_names:
                        entity = Entity(
                            name=subtree.strip(),
                            entity_type='object',
                            confidence=0.65,
                            extraction_method='syntax_pattern'
                        )
                        additional_entities.append(entity)
                        existing_names.add(subtree.lower())
            
            # 3. Extract capitalized phrases (likely proper nouns)
            for i, token in enumerate(doc):
                if token.is_title and i + 1 < len(doc):
                    # Collect consecutive capitalized words
                    phrase_tokens = [token]
                    j = i + 1
                    while j < len(doc) and doc[j].is_title:
                        phrase_tokens.append(doc[j])
                        j += 1
                    
                    if len(phrase_tokens) >= 2:
                        phrase = ' '.join([t.text for t in phrase_tokens])
                        if phrase.lower() not in existing_names:
                            entity = Entity(
                                name=phrase,
                                entity_type='named_entity',
                                confidence=0.7,
                                extraction_method='capitalization_pattern'
                            )
                            additional_entities.append(entity)
                            existing_names.add(phrase.lower())
        
        except (AttributeError, ValueError, TypeError) as e:
            logger.warning(f"Error in aggressive entity extraction: {e}")
        except Exception as e:
            raise EntityExtractionError(
                f"Aggressive entity extraction failed: {e}",
                details={"text_length": len(text), "existing_entity_count": len(existing_entities)}
            ) from e
        
        return additional_entities
    
    def _infer_complex_relationships(self, text: str, existing_relationships: List[Relationship],
                                    entities: List[Entity]) -> List[Relationship]:
        """Infer complex relationships using semantic role labeling and dependency parsing.
        
        Identifies implicit relationships, hierarchical structures, and semantic roles
        that may not be captured by pattern matching.
        
        Args:
            text: Source text
            existing_relationships: Already extracted relationships
            entities: Extracted entities
            
        Returns:
            List of inferred relationships
        """
        inferred_relationships = []
        
        if not self.nlp:
            return inferred_relationships
        
        try:
            doc = self.nlp(text)
            entity_map = {e.name.lower(): e for e in entities}
            
            # Track existing relationships to avoid duplicates
            existing_pairs = {(r.source_id, r.target_id, r.relationship_type) 
                            for r in existing_relationships}
            
            # 1. Infer hierarchical relationships from compound nouns
            # e.g., "machine learning algorithm" implies "algorithm" is_a "machine learning"
            for chunk in doc.noun_chunks:
                if len(list(chunk)) >= 3:
                    tokens = list(chunk)
                    # Check if first tokens form a modifier and last is head
                    modifier = ' '.join([t.text for t in tokens[:-1]])
                    head = tokens[-1].text
                    
                    modifier_entity = entity_map.get(modifier.lower())
                    head_entity = entity_map.get(head.lower())
                    
                    if modifier_entity and head_entity:
                        rel_key = (head_entity.entity_id, modifier_entity.entity_id, 'subtype_of')
                        if rel_key not in existing_pairs:
                            rel = Relationship(
                                relationship_type='subtype_of',
                                source_entity=head_entity,
                                target_entity=modifier_entity,
                                confidence=0.6,
                                source_text=chunk.text,
                                extraction_method='hierarchical_inference'
                            )
                            inferred_relationships.append(rel)
                            existing_pairs.add(rel_key)
            
            # 2. Infer relationships from dependency patterns
            # Agent-Action-Patient patterns
            for token in doc:
                if token.pos_ == 'VERB':
                    # Find subject (agent)
                    subjects = [child for child in token.children if child.dep_ in ['nsubj', 'nsubjpass']]
                    # Find object (patient)
                    objects = [child for child in token.children if child.dep_ in ['dobj', 'pobj']]
                    
                    for subj in subjects:
                        for obj in objects:
                            subj_text = ' '.join([t.text for t in subj.subtree])
                            obj_text = ' '.join([t.text for t in obj.subtree])
                            
                            subj_entity = entity_map.get(subj_text.lower())
                            obj_entity = entity_map.get(obj_text.lower())
                            
                            if subj_entity and obj_entity:
                                # Create relationship based on verb
                                rel_type = token.lemma_ + '_of'  # e.g., "uses" -> "uses_of"
                                rel_key = (subj_entity.entity_id, obj_entity.entity_id, rel_type)
                                
                                if rel_key not in existing_pairs:
                                    rel = Relationship(
                                        relationship_type=rel_type,
                                        source_entity=subj_entity,
                                        target_entity=obj_entity,
                                        confidence=0.65,
                                        source_text=token.sent.text[:100],
                                        extraction_method='srl_inference'
                                    )
                                    inferred_relationships.append(rel)
                                    existing_pairs.add(rel_key)
            
            # 3. Infer transitive relationships
            # If A relates to B and B relates to C, infer A relates to C (with lower confidence)
            entity_ids = {e.entity_id for e in entities}
            relationship_graph = {}
            
            for rel in existing_relationships:
                if rel.source_id not in relationship_graph:
                    relationship_graph[rel.source_id] = []
                relationship_graph[rel.source_id].append((rel.target_id, rel.relationship_type))
            
            # Look for 2-hop paths
            for source_id in relationship_graph:
                for target_id, rel_type1 in relationship_graph.get(source_id, []):
                    for next_target_id, rel_type2 in relationship_graph.get(target_id, []):
                        # Avoid cycles
                        if next_target_id != source_id and next_target_id in entity_ids:
                            # Infer transitive relationship with reduced confidence
                            rel_key = (source_id, next_target_id, f'transitive_{rel_type1}')
                            if rel_key not in existing_pairs:
                                source_entity = next(e for e in entities if e.entity_id == source_id)
                                target_entity = next(e for e in entities if e.entity_id == next_target_id)
                                
                                rel = Relationship(
                                    relationship_type=f'transitive_{rel_type1}',
                                    source_entity=source_entity,
                                    target_entity=target_entity,
                                    confidence=0.5,  # Lower confidence for inferred relationships
                                    source_text='',
                                    extraction_method='transitive_inference'
                                )
                                inferred_relationships.append(rel)
                                existing_pairs.add(rel_key)
                                
                                # Limit transitive relationships to avoid explosion
                                if len(inferred_relationships) >= 20:
                                    break
                    if len(inferred_relationships) >= 20:
                        break
                if len(inferred_relationships) >= 20:
                    break
        
        except (AttributeError, ValueError, TypeError, KeyError, IndexError, StopIteration) as e:
            logger.warning(f"Error in complex relationship inference: {e}")
        except Exception as e:
            raise RelationshipExtractionError(
                f"Complex relationship inference failed: {e}",
                details={
                    "text_length": len(text),
                    "entity_count": len(entities),
                    "relationship_count": len(existing_relationships),
                }
            ) from e
        
        return inferred_relationships

    def _find_best_entity_match(self, text: str, entity_map: Dict[str, Entity]) -> Optional[Entity]:
        """
        Find the best matching entity for a text.

        Args:
            text (str): Text to match
            entity_map (Dict): Map from entity names to Entity objects

        Returns:
            Optional[Entity]: Best matching entity, or None if no match
        """
        # Direct match
        if text in entity_map:
            return entity_map[text]

        # Case-insensitive match
        for name, entity in entity_map.items():
            if name.lower() == text.lower():
                return entity

        # Substring match
        for name, entity in entity_map.items():
            if text.lower() in name.lower() or name.lower() in text.lower():
                return entity

        return None

    def extract_knowledge_graph(self, text: str, extraction_temperature: float = 0.7, structure_temperature: float = 0.5) -> KnowledgeGraph:
        """
        Extract a knowledge graph from text with tunable parameters.

        Args:
            text (str): Text to extract knowledge graph from
            extraction_temperature (float): Controls level of detail (0.0-1.0)
                - Lower values (0.1-0.3): Extract only major concepts and strongest relationships
                - Medium values (0.4-0.7): Extract balanced set of entities and relationships
                - Higher values (0.8-1.0): Extract detailed concepts, properties, and nuanced relationships
            structure_temperature (float): Controls structural complexity (0.0-1.0)
                - Lower values (0.1-0.3): Flatter structure with fewer relationship types
                - Medium values (0.4-0.7): Balanced hierarchical structure
                - Higher values (0.8-1.0): Rich, multi-level concept hierarchies with diverse relationship types

        Returns:
            KnowledgeGraph: Extracted knowledge graph
        """
        # Create a new knowledge graph
        kg = KnowledgeGraph()

        # Apply extraction temperature to confidence thresholds
        # Lower extraction temperature = higher confidence threshold (fewer entities)
        adjusted_confidence = max(0.1, min(0.9, 1.0 - 0.5 * extraction_temperature))
        original_confidence = self.min_confidence
        self.min_confidence = adjusted_confidence

        # Extract entities
        entities = self.extract_entities(text)

        # Apply extraction temperature to entity filtering
        # Higher extraction temperature = more entities included
        if extraction_temperature < 0.5:
            # Keep only high-confidence entities for low temperature
            entities = [e for e in entities if e.confidence > 0.8]
        elif extraction_temperature > 0.8:
            # For high temperature, try to extract additional entities using advanced techniques
            # v2.5.0: Aggressive entity extraction with spaCy dependency parsing
            if self.use_spacy and self.nlp:
                try:
                    additional_entities = self._aggressive_entity_extraction(text, entities)
                    entities.extend(additional_entities)
                except EntityExtractionError as e:
                    logger.warning(f"Aggressive entity extraction failed: {e}")

        # Add entities to the knowledge graph
        for entity in entities:
            kg.entities[entity.entity_id] = entity
            kg.entity_types[entity.entity_type].add(entity.entity_id)
            kg.entity_names[entity.name].add(entity.entity_id)

        # Extract relationships
        relationships = self.extract_relationships(text, entities)

        # Apply structure temperature to relationship inclusion
        # Lower structure temperature = simpler relationship structure
        if structure_temperature < 0.3:
            # Keep only the most important relationship types for low structure temperature
            common_relationship_types = ["is_a", "part_of", "has_part", "related_to", "subfield_of"]
            relationships = [r for r in relationships if r.relationship_type in common_relationship_types]
        elif structure_temperature > 0.8:
            # For high structure temperature, include all relationship types and try to infer
            # additional hierarchical relationships
            # v2.5.0: Complex relationship inference with semantic role labeling
            if self.use_spacy and self.nlp:
                try:
                    inferred_relationships = self._infer_complex_relationships(text, relationships, entities)
                    relationships.extend(inferred_relationships)
                except RelationshipExtractionError as e:
                    logger.warning(f"Complex relationship inference failed: {e}")

        # Add relationships to the knowledge graph
        for rel in relationships:
            kg.relationships[rel.relationship_id] = rel
            kg.relationship_types[rel.relationship_type].add(rel.relationship_id)
            kg.entity_relationships[rel.source_id].add(rel.relationship_id)
            kg.entity_relationships[rel.target_id].add(rel.relationship_id)

        # Restore original confidence threshold
        self.min_confidence = original_confidence

        return kg

    def extract_enhanced_knowledge_graph(self, text: str, use_chunking: bool = True,
                                   extraction_temperature: float = 0.7, structure_temperature: float = 0.5) -> KnowledgeGraph:
        """
        Extract a knowledge graph with enhanced processing and tunable parameters.

        Args:
            text (str): Text to extract knowledge graph from
            use_chunking (bool): Whether to process the text in chunks
            extraction_temperature (float): Controls level of detail (0.0-1.0)
                - Lower values (0.1-0.3): Extract only major concepts and strongest relationships
                - Medium values (0.4-0.7): Extract balanced set of entities and relationships
                - Higher values (0.8-1.0): Extract detailed concepts, properties, and nuanced relationships
            structure_temperature (float): Controls structural complexity (0.0-1.0)
                - Lower values (0.1-0.3): Flatter structure with fewer relationship types
                - Medium values (0.4-0.7): Balanced hierarchical structure
                - Higher values (0.8-1.0): Rich, multi-level concept hierarchies with diverse relationship types

        Returns:
            KnowledgeGraph: Extracted knowledge graph
        """
        # Create a new knowledge graph
        kg = KnowledgeGraph()

        # Process text in chunks if requested
        if use_chunking and len(text) > 2000:
            # Split into chunks with some overlap
            chunk_size = 1000
            overlap = 200
            chunks = []

            for idx in range(0, len(text), chunk_size - overlap):
                chunk = text[idx:idx + chunk_size]
                chunks.append(chunk)

            # Process each chunk and merge the results
            for idx, chunk in enumerate(chunks):
                # Extract knowledge graph from chunk using temperature parameters
                chunk_kg = self.extract_knowledge_graph(chunk, extraction_temperature, structure_temperature)

                # For the first chunk, use it as the base
                if idx == 0:
                    kg = chunk_kg
                else:
                    # Merge subsequent chunks
                    kg.merge(chunk_kg)

        else:
            # Process the entire text at once with temperature parameters
            kg = self.extract_knowledge_graph(text, extraction_temperature, structure_temperature)

        return kg

    def extract_from_documents(self, documents: List[Dict[str, str]], text_key: str = "text",
                             extraction_temperature: float = 0.7, structure_temperature: float = 0.5) -> KnowledgeGraph:
        """
        Extract a knowledge graph from a collection of documents with tunable parameters.

        Args:
            documents (List[Dict]): List of document dictionaries
            text_key (str): Key for the text field in the documents
            extraction_temperature (float): Controls level of detail (0.0-1.0)
                - Lower values (0.1-0.3): Extract only major concepts and strongest relationships
                - Medium values (0.4-0.7): Extract balanced set of entities and relationships
                - Higher values (0.8-1.0): Extract detailed concepts, properties, and nuanced relationships
            structure_temperature (float): Controls structural complexity (0.0-1.0)
                - Lower values (0.1-0.3): Flatter structure with fewer relationship types
                - Medium values (0.4-0.7): Balanced hierarchical structure
                - Higher values (0.8-1.0): Rich, multi-level concept hierarchies with diverse relationship types

        Returns:
            KnowledgeGraph: Extracted knowledge graph
        """
        # Create a master knowledge graph
        master_kg = KnowledgeGraph()

        # Process each document
        for idx, doc in enumerate(documents):
            if text_key not in doc:
                print(f"Warning: Document {idx} does not contain key '{text_key}'")
                continue

            # Extract KG from document with temperature parameters
            doc_kg = self.extract_enhanced_knowledge_graph(
                doc[text_key],
                use_chunking=True,
                extraction_temperature=extraction_temperature,
                structure_temperature=structure_temperature
            )

            # Add document metadata to entities
            for entity in doc_kg.entities.values():
                if not entity.properties:
                    entity.properties = {}
                entity.properties["document_id"] = doc.get("id", str(idx))
                if "title" in doc:
                    entity.properties["document_title"] = doc["title"]

            # Merge into master KG
            master_kg.merge(doc_kg)

        return master_kg

    @staticmethod
    def enrich_with_types(kg: KnowledgeGraph) -> KnowledgeGraph:
        """Enrich a knowledge graph with inferred entity types.

        Args:
            kg (KnowledgeGraph): Knowledge graph to enrich

        Returns:
            KnowledgeGraph: Enriched knowledge graph
        """
        # Define type inference rules based on relationships
        type_rules = {
            "works_for": {"source": "person", "target": "organization"},
            "founded_by": {"source": "organization", "target": "person"},
            "headquartered_in": {"source": "organization", "target": "location"},
            "born_in": {"source": "person", "target": "location"},
            "capital_of": {"source": "location", "target": "location"},
            "author_of": {"source": "person", "target": "work"},
            "developed": {"source": "person", "target": "technology"},
            "created": {"source": "person", "target": "entity"},
            "CEO_of": {"source": "person", "target": "organization"},
            "has_CEO": {"source": "organization", "target": "person"},
            "employs": {"source": "organization", "target": "person"},
            "developed_by": {"source": "model", "target": "organization"},
            "created_by": {"source": "model", "target": "organization"},
            "trained_on": {"source": "model", "target": "dataset"},
            "based_on": {"source": "model", "target": "model"},
            "subfield_of": {"source": "field", "target": "field"},
            "pioneered": {"source": "person", "target": "field"},
        }
        # Apply type inference rules
        for rel in kg.relationships.values():
            if rel.relationship_type in type_rules:
                rule = type_rules[rel.relationship_type]

                # Update source type if generic
                if rel.source_entity.entity_type == "entity":
                    rel.source_entity.entity_type = rule["source"]

                # Update target type if generic
                if rel.target_entity.entity_type == "entity":
                    rel.target_entity.entity_type = rule["target"]
        return kg


