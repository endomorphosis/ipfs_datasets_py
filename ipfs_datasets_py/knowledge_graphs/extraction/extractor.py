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

# Set up logging
logger = logging.getLogger(__name__)




# Helper Functions

def _map_spacy_entity_type(spacy_type: str) -> str:
    """Map spaCy entity labels to our normalized entity types."""
    mapping = {
        'PERSON': 'person',
        'PER': 'person',
        'ORG': 'organization',
        'GPE': 'location',
        'LOC': 'location',
        'FAC': 'location',
        'DATE': 'date',
        'TIME': 'time',
        'EVENT': 'event',
        'PRODUCT': 'product',
        'WORK_OF_ART': 'work',
        'LAW': 'law',
        'LANGUAGE': 'language',
        'PERCENT': 'number',
        'MONEY': 'number',
        'QUANTITY': 'number',
        'ORDINAL': 'number',
        'CARDINAL': 'number',
        'NORP': 'group',
    }
    return mapping.get(spacy_type, 'entity')


def _map_transformers_entity_type(transformers_type: str) -> str:
    """Map HuggingFace NER tags (e.g. B-PER/I-ORG) to normalized entity types."""
    tag = transformers_type
    if '-' in tag:
        tag = tag.split('-', 1)[1]

    tag = tag.upper()
    mapping = {
        'PER': 'person',
        'PERSON': 'person',
        'ORG': 'organization',
        'GPE': 'location',
        'LOC': 'location',
        'DATE': 'date',
        'TIME': 'time',
        'MISC': 'entity',
    }
    return mapping.get(tag, 'entity')


def _rule_based_entity_extraction(text: str) -> List[Entity]:
    """Extract entities using lightweight regex patterns.

    This is the default extraction path when spaCy/transformers are unavailable.
    """
    entities: List[Entity] = []
    entity_names_seen: set[tuple[str, str]] = set()

    patterns: List[tuple[str, str, float]] = [
        # Simple full names (e.g. "Marie Curie")
        (r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", 'person', 0.8),
        # Titles
        (r"(?:Dr\.|Prof\.)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})(?=\s|$|[.,;:])", 'person', 0.9),
        # Person names
        (r"Principal\s+Investigator:\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})", 'person', 0.95),
        # Organizations (AI)
        (r"(Google\s+DeepMind|OpenAI|Anthropic|Microsoft\s+Research|Meta\s+AI|IBM\s+Research)", 'organization', 0.95),
        (r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:Institute|Research|Lab|Laboratory|Center|University)", 'organization', 0.85),
        # Fields / techniques
        (r"\b((?:artificial\s+intelligence|machine\s+learning|deep\s+learning|neural\s+networks?|computer\s+vision|natural\s+language\s+processing|reinforcement\s+learning))\b", 'field', 0.95),
        (r"\b((?:transformer\s+architectures?|attention\s+mechanisms?|self-supervised\s+learning|few-shot\s+learning|cross-modal\s+reasoning))\b", 'field', 0.9),
        (r"\b((?:physics-informed\s+neural\s+networks?|graph\s+neural\s+networks?|generative\s+models?))\b", 'field', 0.9),
        # Technology/tools (heuristic)
        (r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:framework|platform|system|technology|tool|algorithm)s?\b", 'technology', 0.8),
        # Projects
        (r"Project\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?):?\s+", 'project', 0.9),
        # Medical/healthcare
        (r"\b((?:medical\s+)?(?:image\s+analysis|radiology|pathology|healthcare|diagnosis|medical\s+AI))\b", 'field', 0.9),
        # Conferences
        (r"\b(NeurIPS|ICML|ICLR|AAAI|IJCAI|NIPS)\b", 'conference', 0.95),
        # Years/timeframes
        (r"\b(20[0-9]{2}(?:-20[0-9]{2})?)\b", 'date', 0.8),
        # Locations
        (r"\b(?:in|at|from|to|headquartered\s+in)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?(?:,\s*[A-Z][A-Z])?)\b", 'location', 0.8),
    ]

    for pattern, entity_type, confidence in patterns:
        flags = re.IGNORECASE if entity_type in ['field', 'technology'] else 0

        for match in re.finditer(pattern, text, flags):
            name = match.group(1).strip()

            name = re.sub(r'\s+', ' ', name)
            name = name.strip('.,;:')

            if not name or len(name) < 2:
                continue

            name_key = (name.lower(), entity_type)
            if name_key in entity_names_seen:
                continue
            entity_names_seen.add(name_key)

            if name.lower() in {'timeline', 'the', 'and', 'our', 'this', 'that', 'with', 'from'}:
                continue

            start_pos = max(0, match.start() - 20)
            end_pos = min(len(text), match.end() + 20)
            source_snippet = text[start_pos:end_pos].replace('\\n', ' ').strip()

            entities.append(
                Entity(
                    entity_type=entity_type,
                    name=name,
                    confidence=confidence,
                    source_text=source_snippet,
                )
            )

    return entities


def _string_similarity(str1: str, str2: str) -> float:
    """Calculate similarity between two strings.

    Args:
        str1 (str): First string
        str2 (str): Second string

    Returns:
        float: Similarity score (0-1)
    """
    # Simple Jaccard similarity on words
    words1 = set(str1.lower().split())
    words2 = set(str2.lower().split())

    if not words1 or not words2:
        return 0.0

    intersection = words1.intersection(words2)
    union = words1.union(words2)

    return len(intersection) / len(union)


# Main Extractor Class

class KnowledgeGraphExtractor:
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
                    print(f"spaCy model not found ({e}), downloading...")
                    spacy.cli.download("en_core_web_sm")
                    self.nlp = spacy.load("en_core_web_sm")
            except ImportError:
                print("Warning: spaCy not installed. Running in rule-based mode only.")
                print("Install with: pip install 'ipfs_datasets_py[knowledge_graphs]'")
                print("Then: python -m spacy download en_core_web_sm")
                self.use_spacy = False

        if use_transformers:
            try:
                from transformers import pipeline
                self.ner_model = pipeline("ner")
                self.re_model = pipeline("text-classification",
                                        model="Rajkumar-Murugesan/roberta-base-finetuned-tacred-relation")
            except ImportError:
                print("Warning: transformers not installed. Running without Transformer models.")
                print("Install transformers with: pip install transformers")
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
                    details={'text_length': len(text), 'use_transformers': True}
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
                details={"text_length": len(text), "entity_count": len(entity_map)}
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

    def extract_from_wikipedia(self, 
                            page_title: str, 
                            extraction_temperature: float = 0.7,
                           structure_temperature: float = 0.5
                           ) -> KnowledgeGraph:
        """Extract a knowledge graph from a Wikipedia page with tunable parameters.

        This method fetches content from a Wikipedia page via the Wikipedia API and processes it into
        a structured knowledge graph. The extraction process is highly configurable through temperature
        parameters that control both the level of detail and structural complexity of the resulting graph.

        Args:
            page_title (str): The exact title of the Wikipedia page to extract from. Must match
                the Wikipedia page title format (case-sensitive, with proper spacing).
            extraction_temperature (float, optional): Controls the granularity and depth of entity
                and relationship extraction. Defaults to 0.7.
                - Low values (0.1-0.3): Extract only primary concepts, major entities, and the 
                    strongest, most obvious relationships. Results in a minimal, core knowledge graph.
                - Medium values (0.4-0.7): Balanced extraction including secondary concepts, 
                    moderate entity detail, and well-supported relationships. Provides good coverage
                    without excessive noise.
                - High values (0.8-1.0): Comprehensive extraction including detailed concepts,
                    entity properties, attributes, nuanced relationships, and contextual information.
                    May include more speculative or weak relationships.
            structure_temperature (float, optional): Controls the hierarchical complexity and
                relationship diversity of the knowledge graph structure. Defaults to 0.5.
                - Low values (0.1-0.3): Creates flatter graph structures with fewer relationship
                    types, focusing on direct connections and simple hierarchies.
                - Medium values (0.4-0.7): Generates balanced hierarchical structures with
                    moderate relationship type diversity and multi-level organization.
                - High values (0.8-1.0): Produces rich, multi-layered concept hierarchies with
                    diverse relationship types, complex interconnections, and deep structural nesting.

        Returns:
            KnowledgeGraph: A comprehensive knowledge graph object containing:
                - Extracted entities with their properties and confidence scores
                - Relationships between entities with type classification and confidence
                - A special Wikipedia page entity representing the source
                - "sourced_from" relationships linking all entities to their Wikipedia origin
                - Metadata including entity and relationship type classifications
                - Graph name formatted as "wikipedia_{page_title}"

        Raises:
            ValueError: If the specified Wikipedia page title is not found or does not exist.
                The error message will indicate the specific page title that was not found.
            RuntimeError: If any error occurs during the Wikipedia API request, content processing,
                or knowledge graph construction. The original exception details are preserved
                in the error message for debugging purposes.

        Note:
            - The method requires an active internet connection to access the Wikipedia API
            - Wikipedia page titles are case-sensitive and must match exactly
            - The extraction process may take significant time for large Wikipedia pages
            - If tracing is enabled, detailed extraction metadata is recorded for analysis
            - The resulting knowledge graph includes bidirectional relationship tracking
            - All extracted entities maintain provenance through "sourced_from" relationships

        Example:
            >>> extractor = KnowledgeGraphExtractor()
            >>> kg = extractor.extract_from_wikipedia(
            ...     page_title="Artificial Intelligence",
            ...     extraction_temperature=0.6,
            ...     structure_temperature=0.4
            ... )
            >>> print(f"Extracted {len(kg.entities)} entities and {len(kg.relationships)} relationships")
        """
        # Create trace if tracer is enabled
        trace_id = None
        if self.use_tracer and self.tracer:
            trace_id = self.tracer.trace_extraction(
                page_title=page_title,
                extraction_temperature=extraction_temperature,
                structure_temperature=structure_temperature
            )

        # Fetch Wikipedia content
        try:
            # Make API request to get Wikipedia page content
            url = "https://en.wikipedia.org/w/api.php"
            params = {
                "action": "query",
                "format": "json",
                "titles": page_title,
                "prop": "extracts",
                "exintro": 0,  # Include the full page, not just intro
                "explaintext": 1  # Get plain text
            }

            response = requests.get(url, params=params)
            data = response.json()

            # Extract the page content
            pages = data["query"]["pages"]
            page_id = list(pages.keys())[0]

            # Check if page exists
            if page_id == "-1":
                error_msg = f"Wikipedia page '{page_title}' not found."
                # Update trace with error if tracer is enabled
                if self.use_tracer and self.tracer and trace_id:
                    self.tracer.update_extraction_trace(
                        trace_id=trace_id,
                        status="failed",
                        error=error_msg
                    )
                raise ValueError(error_msg)

            page_content = pages[page_id]["extract"]

            # Create knowledge graph from the content with temperature parameters
            kg = self.extract_enhanced_knowledge_graph(
                page_content,
                use_chunking=True,
                extraction_temperature=extraction_temperature,
                structure_temperature=structure_temperature
            )

            # Add metadata about the source
            kg.name = f"wikipedia_{page_title}"

            # Add the Wikiepdia page as a source entity
            page_entity = Entity(
                entity_type="wikipedia_page",
                name=page_title,
                properties={"url": f"https://en.wikipedia.org/wiki/{page_title.replace(' ', '_')}"},
                confidence=1.0
            )

            kg.entities[page_entity.entity_id] = page_entity
            kg.entity_types["wikipedia_page"].add(page_entity.entity_id)
            kg.entity_names[page_title].add(page_entity.entity_id)

            # Create "source_from" relationships
            for entity in list(kg.entities.values()):
                if entity.entity_id != page_entity.entity_id:
                    rel = Relationship(
                        relationship_type="sourced_from",
                        source=entity,
                        target=page_entity,
                        confidence=1.0
                    )

                    kg.relationships[rel.relationship_id] = rel
                    kg.relationship_types["sourced_from"].add(rel.relationship_id)
                    kg.entity_relationships[entity.entity_id].add(rel.relationship_id)
                    kg.entity_relationships[page_entity.entity_id].add(rel.relationship_id)

            # Update trace with results if tracer is enabled
            if self.use_tracer and self.tracer and trace_id:
                self.tracer.update_extraction_trace(
                    trace_id=trace_id,
                    status="completed",
                    knowledge_graph=kg,
                    entity_count=len(kg.entities),
                    relationship_count=len(kg.relationships),
                    entity_types=dict(kg.entity_types),
                    relationship_types=dict(kg.relationship_types)
                )

            return kg

        except (requests.RequestException, requests.HTTPError, requests.Timeout) as e:
            error_msg = f"Network error extracting knowledge graph from Wikipedia '{page_title}': {e}"
            logger.error(error_msg)
            # Update trace with error if tracer is enabled
            if self.use_tracer and self.tracer and trace_id:
                self.tracer.update_extraction_trace(
                    trace_id=trace_id,
                    status="failed",
                    error=error_msg
                )
            # Re-raise as EntityExtractionError
            raise EntityExtractionError(error_msg, details={'wikipedia_title': page_title, 'trace_id': trace_id}) from e
        
        except (ValueError, KeyError, TypeError, IndexError) as e:
            error_msg = f"Unexpected error extracting knowledge graph from Wikipedia '{page_title}': {e}"
            logger.error(error_msg)
            # Update trace with error if tracer is enabled
            if self.use_tracer and self.tracer and trace_id:
                self.tracer.update_extraction_trace(
                    trace_id=trace_id,
                    status="failed",
                    error=error_msg
                )
            # Re-raise as EntityExtractionError
            raise EntityExtractionError(error_msg, details={'wikipedia_title': page_title, 'trace_id': trace_id}) from e

    def validate_against_wikidata(self, kg: KnowledgeGraph, entity_name: str) -> Dict[str, Any]:
        """
        Validate a knowledge graph against Wikidata's structured data.

        Args:
            kg (KnowledgeGraph): Knowledge graph to validate
            entity_name (str): Name of the main entity to validate against

        Returns:
            Dict: Validation results including:
                - coverage: Percentage of Wikidata statements covered
                - missing_relationships: Relationships in Wikidata not in the KG
                - additional_relationships: Relationships in the KG not in Wikidata
                - entity_mapping: Mapping between KG entities and Wikidata entities
        """
        # Create trace if tracer is enabled
        trace_id = None
        if self.use_tracer and self.tracer:
            trace_id = self.tracer.trace_validation(
                kg_name=kg.name,
                entity_name=entity_name
            )

        try:
            # Map the entity to Wikidata
            wikidata_id = self._get_wikidata_id(entity_name)

            if not wikidata_id:
                error_result = {
                    "error": f"Could not find Wikidata entity for '{entity_name}'",
                    "coverage": 0.0,
                    "missing_relationships": [],
                    "additional_relationships": [],
                    "entity_mapping": {}
                }

                # Update trace with error if tracer is enabled
                if self.use_tracer and self.tracer and trace_id:
                    self.tracer.update_validation_trace(
                        trace_id=trace_id,
                        status="failed",
                        error=error_result["error"],
                        validation_results=error_result
                    )

                return error_result

            # Get structured data from Wikidata
            wikidata_statements = self._get_wikidata_statements(wikidata_id)

            # Find corresponding entity in the knowledge graph
            kg_entities = kg.get_entities_by_name(entity_name)

            if not kg_entities:
                error_result = {
                    "error": f"Entity '{entity_name}' not found in the knowledge graph",
                    "coverage": 0.0,
                    "missing_relationships": wikidata_statements,
                    "additional_relationships": [],
                    "entity_mapping": {}
                }

                # Update trace with error if tracer is enabled
                if self.use_tracer and self.tracer and trace_id:
                    self.tracer.update_validation_trace(
                        trace_id=trace_id,
                        status="failed",
                        error=error_result["error"],
                        validation_results=error_result
                    )

                return error_result

            kg_entity = kg_entities[0]

            # Find relationships in the KG involving this entity
            kg_relationships = kg.get_relationships_by_entity(kg_entity)

            # Convert to simplified format for comparison
            kg_statements = []
            entity_mapping = {kg_entity.entity_id: wikidata_id}

            for rel in kg_relationships:
                if rel.source_id == kg_entity.entity_id:
                    # This is an outgoing relationship
                    kg_statements.append({
                        "property": rel.relationship_type,
                        "value": rel.target_entity.name,
                        "value_entity": rel.target_entity.entity_id
                    })
                elif rel.target_id == kg_entity.entity_id:
                    # This is an incoming relationship
                    kg_statements.append({
                        "property": f"inverse_{rel.relationship_type}",
                        "value": rel.source_entity.name,
                        "value_entity": rel.source_entity.entity_id
                    })

            # Compare statements
            covered_statements = []
            missing_statements = []

            for wk_stmt in wikidata_statements:
                # Try to find a matching statement in the KG
                found = False
                best_match = None
                best_score = 0.0

                for kg_stmt in kg_statements:
                    # Compare property names (inexact)
                    prop_match = _string_similarity(
                        wk_stmt["property"].lower(),
                        kg_stmt["property"].lower()
                    )

                    # Compare values (inexact)
                    value_match = _string_similarity(
                        wk_stmt["value"].lower(),
                        kg_stmt["value"].lower()
                    )

                    # Calculate overall match score
                    score = (prop_match + value_match) / 2.0

                    if score > 0.7 and score > best_score:  # Threshold for considering a match
                        found = True
                        best_match = kg_stmt
                        best_score = score

                if found:
                    covered_statements.append({
                        "wikidata": wk_stmt,
                        "kg": best_match,
                        "match_score": best_score
                    })

                    # Add to entity mapping
                    if "value_id" in wk_stmt and "value_entity" in best_match:
                        entity_mapping[best_match["value_entity"]] = wk_stmt["value_id"]
                else:
                    missing_statements.append(wk_stmt)

            # Find additional statements in the KG
            additional_statements = []

            for kg_stmt in kg_statements:
                if not any(covered["kg"] == kg_stmt for covered in covered_statements):
                    additional_statements.append(kg_stmt)

            # Calculate coverage
            if len(wikidata_statements) > 0:
                coverage = len(covered_statements) / len(wikidata_statements)
            else:
                coverage = 1.0  # No statements to cover

            result = {
                "coverage": coverage,
                "covered_relationships": covered_statements,
                "missing_relationships": missing_statements,
                "additional_relationships": additional_statements,
                "entity_mapping": entity_mapping
            }

            # Update trace with results if tracer is enabled
            if self.use_tracer and self.tracer and trace_id:
                self.tracer.update_validation_trace(
                    trace_id=trace_id,
                    status="completed",
                    wikidata_id=wikidata_id,
                    wikidata_statements_count=len(wikidata_statements),
                    kg_statements_count=len(kg_statements),
                    coverage=coverage,
                    covered_count=len(covered_statements),
                    missing_count=len(missing_statements),
                    additional_count=len(additional_statements),
                    validation_results=result
                )

            return result

        except (requests.RequestException, requests.HTTPError, requests.Timeout) as e:
            error_result = {
                "error": f"Network error validating against Wikidata: {e}",
                "coverage": 0.0,
                "missing_relationships": [],
                "additional_relationships": [],
                "entity_mapping": {}
            }
            logger.error(f"Wikidata validation network error: {e}")

            # Update trace with error if tracer is enabled
            if self.use_tracer and self.tracer and trace_id:
                self.tracer.update_validation_trace(
                    trace_id=trace_id,
                    status="failed",
                    error=str(e),
                    validation_results=error_result
                )

            return error_result
        
        except (ValueError, KeyError, TypeError, IndexError, AttributeError) as e:
            error_result = {
                "error": f"Unexpected error validating against Wikidata: {e}",
                "coverage": 0.0,
                "missing_relationships": [],
                "additional_relationships": [],
                "entity_mapping": {}
            }
            logger.error(f"Wikidata validation error: {e}")

            # Update trace with error if tracer is enabled
            if self.use_tracer and self.tracer and trace_id:
                self.tracer.update_validation_trace(
                    trace_id=trace_id,
                    status="failed",
                    error=str(e),
                    validation_results=error_result
                )

            # Wrap in ValidationError
            raise ValidationError(
                f"Failed to validate knowledge graph against Wikidata: {e}",
                details={'trace_id': trace_id, 'entity_name': kg.entities.get(list(kg.entities.keys())[0]).name if kg.entities else 'unknown'}
            ) from e

    def _get_wikidata_id(self, entity_name: str) -> Optional[str]:
        """
        Get the Wikidata ID for an entity name.

        Args:
            entity_name (str): Name of the entity

        Returns:
            str: Wikidata ID (Qxxxxx) or None if not found
        """
        try:
            # Make API request to search for the entity
            url = "https://www.wikidata.org/w/api.php"
            params = {
                "action": "wbsearchentities",
                "format": "json",
                "search": entity_name,
                "language": "en"
            }

            response = requests.get(url, params=params)
            data = response.json()

            # Get the first result if available
            if "search" in data and len(data["search"]) > 0:
                return data["search"][0]["id"]
            else:
                return None

        except (requests.RequestException, ValueError) as e:
            logger.debug(f"Could not retrieve Wikidata ID for '{entity_name}': {e}")
            return None
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            logger.warning(f"Unexpected error getting Wikidata ID for '{entity_name}': {e}")
            return None

    def _get_wikidata_statements(self, entity_id: str) -> List[Dict[str, Any]]:
        """
        Get structured statements for a Wikidata entity.

        Args:
            entity_id (str): Wikidata entity ID (Qxxxxx)

        Returns:
            List[Dict]: List of simplified statements
        """
        try:
            # Query the Wikidata SPARQL endpoint
            sparql_endpoint = "https://query.wikidata.org/sparql"

            # SPARQL query to get all direct relations
            query = f"""
            SELECT ?property ?propertyLabel ?value ?valueLabel ?valueId
            WHERE {{
              wd:{entity_id} ?p ?value .
              ?property wikibase:directClaim ?p .
              OPTIONAL {{ ?value wdt:P31 ?type . }}
              OPTIONAL {{
                FILTER(isIRI(?value))
                BIND(STRAFTER(STR(?value), 'http://www.wikidata.org/entity/') AS ?valueId)
              }}
              SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
            }}
            """

            headers = {
                'User-Agent': 'KnowledgeGraphValidator/1.0 (https://example.org/; info@example.org)',
                'Accept': 'application/json'
            }

            response = requests.get(
                sparql_endpoint,
                params={"query": query, "format": "json"},
                headers=headers
            )

            data = response.json()

            # Process and simplify the results
            statements = []

            for result in data.get("results", {}).get("bindings", []):
                # Skip some administrative properties
                property_id = result.get("property", {}).get("value", "")
                if property_id.endswith("/P31") or property_id.endswith("/P279"):  # Instance of, subclass of
                    continue

                statement = {
                    "property": result.get("propertyLabel", {}).get("value", "Unknown property"),
                    "value": result.get("valueLabel", {}).get("value", "Unknown value")
                }

                # Include Wikidata IDs if available
                if "valueId" in result and result["valueId"].get("value"):
                    statement["value_id"] = result["valueId"]["value"]

                statements.append(statement)

            return statements

        except (requests.RequestException, requests.HTTPError, requests.Timeout) as e:
            logger.error(f"Network error querying Wikidata for entity '{entity_id}': {e}")
            return []
        except (ValueError, KeyError, TypeError, IndexError, AttributeError) as e:
            logger.error(f"Unexpected error querying Wikidata for entity '{entity_id}': {e}")
            raise ValidationError(
                f"Failed to query Wikidata statements for entity '{entity_id}': {e}",
                details={'entity_id': entity_id}
            ) from e



    def extract_and_validate_wikipedia_graph(self, page_title: str, extraction_temperature: float = 0.7,
                                        structure_temperature: float = 0.5) -> Dict[str, Any]:
        """
        Extract knowledge graph from a Wikipedia page and validate against Wikidata SPARQL.

        This function extracts a knowledge graph from a Wikipedia page, then queries the
        Wikidata SPARQL endpoint to validate that the extraction contains at least the
        structured data already present in Wikidata.

        Args:
            page_title (str): Title of the Wikipedia page
            extraction_temperature (float): Controls level of detail (0.0-1.0)
            structure_temperature (float): Controls structural complexity (0.0-1.0)

        Returns:
            Dict: Result containing:
                - knowledge_graph: The extracted knowledge graph
                - validation: Validation results against Wikidata
                - coverage: Percentage of Wikidata statements covered (0.0-1.0)
                - metrics: Additional metrics about extraction quality
                - trace_id: ID of the trace if tracing is enabled
        """
        # Create trace if tracer is enabled
        trace_id = None
        if self.use_tracer and self.tracer:
            trace_id = self.tracer.trace_extraction_and_validation(
                page_title=page_title,
                extraction_temperature=extraction_temperature,
                structure_temperature=structure_temperature
            )

        try:
            # Extract knowledge graph from Wikipedia
            kg = self.extract_from_wikipedia(
                page_title=page_title,
                extraction_temperature=extraction_temperature,
                structure_temperature=structure_temperature
            )

            # Validate against Wikidata
            validation_results = self.validate_against_wikidata(kg, page_title)

            # Calculate additional metrics
            metrics = {
                "entity_count": len(kg.entities),
                "relationship_count": len(kg.relationships),
                "entity_types": {entity_type: len(entities) for entity_type, entities in kg.entity_types.items()},
                "relationship_types": {rel_type: len(rels) for rel_type, rels in kg.relationship_types.items()},
                "avg_confidence": sum(e.confidence for e in kg.entities.values()) / len(kg.entities) if kg.entities else 0,
                "extraction_temperature": extraction_temperature,
                "structure_temperature": structure_temperature
            }

            # Create comprehensive result
            result = {
                "knowledge_graph": kg,
                "validation": validation_results,
                "coverage": validation_results.get("coverage", 0.0),
                "metrics": metrics
            }

            # Add trace ID if tracing is enabled
            if self.use_tracer and self.tracer and trace_id:
                result["trace_id"] = trace_id

                # Update combined trace with results
                self.tracer.update_extraction_and_validation_trace(
                    trace_id=trace_id,
                    status="completed",
                    knowledge_graph=kg,
                    validation_results=validation_results,
                    metrics=metrics,
                    entity_count=len(kg.entities),
                    relationship_count=len(kg.relationships),
                    coverage=validation_results.get("coverage", 0.0)
                )

            return result

        except EntityExtractionError:
            # Re-raise our custom exceptions
            raise
        except ValidationError:
            # Re-raise validation errors
            raise
        except (ValueError, KeyError, TypeError, IndexError, AttributeError) as e:
            error_result = {
                "error": f"Unexpected error extracting and validating graph from '{page_title}': {e}",
                "knowledge_graph": None,
                "validation": {"error": str(e)},
                "coverage": 0.0,
                "metrics": {}
            }
            logger.error(f"Extract and validate failed for '{page_title}': {e}")
            # Wrap in EntityExtractionError
            raise EntityExtractionError(
                f"Failed to extract and validate knowledge graph from Wikipedia page '{page_title}': {e}",
                details={'page_title': page_title, 'extraction_temperature': extraction_temperature, 
                        'structure_temperature': structure_temperature}
            ) from e

            # Update trace with error if tracer is enabled
            if self.use_tracer and self.tracer and trace_id:
                error_result["trace_id"] = trace_id

                self.tracer.update_extraction_and_validation_trace(
                    trace_id=trace_id,
                    status="failed",
                    error=str(e)
                )

            return error_result

