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
from typing import Dict, List, Any, Optional

# Import extraction package components
from .entities import Entity
from .relationships import Relationship
from .graph import KnowledgeGraph

# Import the Wikipedia knowledge graph tracer for enhanced tracing capabilities
from ipfs_datasets_py.ml.llm.llm_reasoning_tracer import WikipediaKnowledgeGraphTracer




# Helper Functions

def _default_relation_patterns() -> List[Dict[str, Any]]:
    """Create default relation extraction patterns.

    Returns:
        List[Dict]: List of relation patterns
    """
    return [
        # Enhanced patterns for AI research content
        {
            "name": "expert_in",
            "pattern": r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+is\s+(?:a\s+)?(?:leading\s+)?expert\s+in\s+([a-z][a-z\s]+)",
            "source_type": "person",
            "target_type": "field",
            "confidence": 0.9
        },
        {
            "name": "focuses_on",
            "pattern": r"(Project\s+[A-Z][a-z]+)\s+focus(?:es)?\s+on\s+([a-z][a-z\s]+)",
            "source_type": "project",
            "target_type": "field",
            "confidence": 0.8
        },
        {
            "name": "contributed_to",
            "pattern": r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+contributed\s+to\s+([a-z][a-z\s]+)",
            "source_type": "person",
            "target_type": "field",
            "confidence": 0.85
        },
        {
            "name": "works_at_org",
            "pattern": r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:works?\s+at|is\s+at|joined)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
            "source_type": "person",
            "target_type": "organization",
            "confidence": 0.9
        },
        # Original comprehensive patterns
        {
            "name": "founded_by",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+(?:was|were)\s+founded\s+by\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "organization",
            "target_type": "person",
            "confidence": 0.8
        },
        {
            "name": "works_for",
            "pattern": r"(\b\w+(?:\s+\w+){0,3}?)\s+works\s+(?:for|at)\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "organization",
            "confidence": 0.8
        },
        {
            "name": "part_of",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+is\s+(?:a\s+)?part\s+of\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "entity",
            "target_type": "entity",
            "confidence": 0.7
        },
        {
            "name": "located_in",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+(?:is|are)\s+(?:located|based)\s+in\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "entity",
            "target_type": "location",
            "confidence": 0.8
        },
        {
            "name": "created",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+created\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "entity",
            "confidence": 0.8
        },
        {
            "name": "developed",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+developed\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "entity",
            "confidence": 0.8
        },
        {
            "name": "acquired",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+acquired\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "organization",
            "target_type": "organization",
            "confidence": 0.9
        },
        {
            "name": "parent_of",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+is\s+(?:the\s+)?parent\s+(?:company\s+)?of\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "organization",
            "target_type": "organization",
            "confidence": 0.9
        },
        {
            "name": "subsidiary_of",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+is\s+(?:a\s+)?subsidiary\s+of\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "organization",
            "target_type": "organization",
            "confidence": 0.9
        },
        {
            "name": "headquartered_in",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+is\s+headquartered\s+in\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "organization",
            "target_type": "location",
            "confidence": 0.9
        },
        {
            "name": "founded_in",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+(?:was|were)\s+founded\s+in\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "organization",
            "target_type": "location",
            "confidence": 0.8
        },
        {
            "name": "CEO_of",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+is\s+(?:the\s+)?(?:CEO|Chief\s+Executive\s+Officer)\s+of\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "organization",
            "confidence": 0.9
        },
        {
            "name": "has_CEO",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)(?:'s)?\s+(?:CEO|Chief\s+Executive\s+Officer)\s+is\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "organization",
            "target_type": "person",
            "confidence": 0.9
        },
        {
            "name": "author_of",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+(?:is\s+the\s+author\s+of|wrote|authored)\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "work",
            "confidence": 0.9
        },
        {
            "name": "invented",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+invented\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "entity",
            "confidence": 0.9
        },
        {
            "name": "discovered",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+discovered\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "entity",
            "confidence": 0.9
        },
        {
            "name": "used_for",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+is\s+used\s+for\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "entity",
            "target_type": "entity",
            "confidence": 0.8
        },
        {
            "name": "predecessor_of",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+is\s+(?:the\s+)?predecessor\s+of\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "entity",
            "target_type": "entity",
            "confidence": 0.8
        },
        {
            "name": "successor_to",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+is\s+(?:the\s+)?successor\s+to\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "entity",
            "target_type": "entity",
            "confidence": 0.8
        },
        {
            "name": "parent_company",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)'s\s+parent\s+company\s+is\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "organization",
            "target_type": "organization",
            "confidence": 0.8
        },
        {
            "name": "born_in",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+was\s+born\s+in\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "location",
            "confidence": 0.9
        },
        {
            "name": "died_in",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+died\s+in\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "location",
            "confidence": 0.9
        },
        {
            "name": "married_to",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+is\s+married\s+to\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "person",
            "confidence": 0.9,
            "bidirectional": True
        },
        {
            "name": "capital_of",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+is\s+the\s+capital\s+of\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "location",
            "target_type": "location",
            "confidence": 0.9
        },
        {
            "name": "has_capital",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)(?:'s)?\s+capital\s+is\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "location",
            "target_type": "location",
            "confidence": 0.9
        },
        {
            "name": "employs",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+employs\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "organization",
            "target_type": "person",
            "confidence": 0.8
        },
        # Domain-specific patterns for AI/ML
        {
            "name": "developed_by",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+(?:was|were)\s+developed\s+by\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "model",
            "target_type": "organization",
            "confidence": 0.8
        },
        {
            "name": "created_by",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+(?:was|were)\s+created\s+by\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "model",
            "target_type": "organization",
            "confidence": 0.8
        },
        {
            "name": "trained_on",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+(?:was|were)\s+trained\s+on\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "model",
            "target_type": "dataset",
            "confidence": 0.8
        },
        {
            "name": "based_on",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+is\s+based\s+on\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "model",
            "target_type": "model",
            "confidence": 0.8
        },
        {
            "name": "subfield_of",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+is\s+a\s+subfield\s+of\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "field",
            "target_type": "field",
            "confidence": 0.9
        },
        {
            "name": "pioneered",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+pioneered\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "field",
            "confidence": 0.9
        },
        {
            "name": "leads",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+leads\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "organization",
            "confidence": 0.8
        },
        {
            "name": "works_at",
            "pattern": r"(\b\w+(?:\s+\w+){0,5}?)\s+works\s+at\s+(\b\w+(?:\s+\w+){0,5}?)\b",
            "source_type": "person",
            "target_type": "organization",
            "confidence": 0.8
        }
    ]

def _map_spacy_entity_type(spacy_type: str) -> str:
    """Map spaCy entity types to our entity types.

    Args:
        spacy_type (str): spaCy entity type

    Returns:
        str: Mapped entity type
    """
    mapping = {
        "PERSON": "person",
        "PER": "person",
        "ORG": "organization",
        "GPE": "location",
        "LOC": "location",
        "DATE": "date",
        "TIME": "time",
        "PRODUCT": "product",
        "EVENT": "event",
        "WORK_OF_ART": "work",
        "LAW": "law",
        "LANGUAGE": "language",
        "PERCENT": "number",
        "MONEY": "number",
        "QUANTITY": "number",
        "ORDINAL": "number",
        "CARDINAL": "number",
        "NORP": "group",
        "FAC": "location",
    }
    return mapping.get(spacy_type, "entity")

def _map_transformers_entity_type(transformers_type: str) -> str:
    """Map Transformers entity types to our entity types.

    Args:
        transformers_type (str): Transformers entity type

    Returns:
        str: Mapped entity type
    """
    mapping = {
        "PER": "person",
        "PERSON": "person",
        "I-PER": "person",
        "B-PER": "person",
        "ORG": "organization",
        "I-ORG": "organization",
        "B-ORG": "organization",
        "LOC": "location",
        "I-LOC": "location",
        "B-LOC": "location",
        "GPE": "location",
        "I-GPE": "location",
        "B-GPE": "location",
        "DATE": "date",
        "I-DATE": "date",
        "B-DATE": "date",
        "TIME": "time",
        "I-TIME": "time",
        "B-TIME": "time",
        "PRODUCT": "product",
        "I-PRODUCT": "product",
        "B-PRODUCT": "product",
        "EVENT": "event",
        "I-EVENT": "event",
        "B-EVENT": "event",
        "WORK_OF_ART": "work",
        "I-WORK_OF_ART": "work",
        "B-WORK_OF_ART": "work",
        "LAW": "law",
        "I-LAW": "law",
        "B-LAW": "law",
        "LANGUAGE": "language",
        "I-LANGUAGE": "language",
        "B-LANGUAGE": "language",
        "MISC": "entity",
        "I-MISC": "entity",
        "B-MISC": "entity",
    }

    return mapping.get(transformers_type, "entity")

def _rule_based_entity_extraction(text: str) -> List[Entity]:
    """
    Extract entities using rule-based patterns.

    Args:
        text (str): Text to extract entities from

    Returns:
        List[Entity]: List of extracted entities
    """
    entities = []
    entity_names_seen = set()  # Track unique entities

    # Enhanced patterns for better AI research content extraction
    patterns = [
        # Person names: Dr./Prof. + proper names (improved)
        (r"(?:Dr\.|Prof\.)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})(?=\s|$|[.,;:])", "person", 0.9),
        
        # Person names: common academic patterns
        (r"Principal\s+Investigator:\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})", "person", 0.95),
        
        # Organizations: specific patterns for AI companies/institutes
        (r"(Google\s+DeepMind|OpenAI|Anthropic|Microsoft\s+Research|Meta\s+AI|IBM\s+Research)", "organization", 0.95),
        (r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:Institute|Research|Lab|Laboratory|Center|University)", "organization", 0.85),
        
        # AI/ML fields and techniques (enhanced)
        (r"\b((?:artificial\s+intelligence|machine\s+learning|deep\s+learning|neural\s+networks?|computer\s+vision|natural\s+language\s+processing|reinforcement\s+learning))\b", "field", 0.95),
        (r"\b((?:transformer\s+architectures?|attention\s+mechanisms?|self-supervised\s+learning|few-shot\s+learning|cross-modal\s+reasoning))\b", "field", 0.9),
        (r"\b((?:physics-informed\s+neural\s+networks?|graph\s+neural\s+networks?|generative\s+models?))\b", "field", 0.9),
        
        # Technology and tools
        (r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:framework|platform|system|technology|tool|algorithm)s?\b", "technology", 0.8),
        
        # Projects and research areas
        (r"Project\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?):?\s+", "project", 0.9),
        
        # Medical/Healthcare terms
        (r"\b((?:medical\s+)?(?:image\s+analysis|radiology|pathology|healthcare|diagnosis|medical\s+AI))\b", "field", 0.9),
        
        # Conferences and venues (common in AI)
        (r"\b(NeurIPS|ICML|ICLR|AAAI|IJCAI|NIPS)\b", "conference", 0.95),
        
        # Years and timeframes
        (r"\b(20[0-9]{2}(?:-20[0-9]{2})?)\b", "date", 0.8),
        
        # Locations (improved)
        (r"\b(?:in|at|from|to|headquartered\s+in)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?(?:,\s*[A-Z][A-Z])?)\b", "location", 0.8),
    ]
    
    for pattern, entity_type, confidence in patterns:
        flags = re.IGNORECASE if entity_type in ["field", "technology"] else 0
        
        for match in re.finditer(pattern, text, flags):
            name = match.group(1).strip()
            
            # Clean up the extracted name
            name = re.sub(r'\s+', ' ', name)  # Normalize whitespace
            name = name.strip('.,;:')  # Remove trailing punctuation
            
            # Skip if empty or too short
            if not name or len(name) < 2:
                continue
                
            # Skip if already seen (for deduplication)
            name_key = (name.lower(), entity_type)
            if name_key in entity_names_seen:
                continue
            entity_names_seen.add(name_key)
            
            # Skip common false positives
            if name.lower() in ['timeline', 'the', 'and', 'our', 'this', 'that', 'with', 'from']:
                continue
                
            # Create entity with better source text extraction
            start_pos = max(0, match.start() - 20)
            end_pos = min(len(text), match.end() + 20)
            source_snippet = text[start_pos:end_pos].replace('\n', ' ').strip()
            
            entity = Entity(
                entity_type=entity_type,
                name=name,
                confidence=confidence,
                source_text=source_snippet
            )
            entities.append(entity)
    
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
                import spacy # TODO Add in spacy as a dependency
                try:
                    self.nlp = spacy.load("en_core_web_sm")
                except:
                    # If the model is not available, download it
                    print("Downloading spaCy model...")
                    spacy.cli.download("en_core_web_sm")
                    self.nlp = spacy.load("en_core_web_sm")
            except ImportError:
                print("Warning: spaCy not installed. Running in rule-based mode only.")
                print("Install spaCy with: pip install spacy")
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

            except Exception as e:
                print(f"Warning: Error in transformers NER: {e}")
                # Fall back to rule-based extraction
                entities.extend(_rule_based_entity_extraction(text))
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
            # TODO extract_relationships needs a more specific RE model from Transformers.
            # Not implemented yet - would require a more specific RE model
            pass

        # Use rule-based relationship extraction
        relationships.extend(self._rule_based_relationship_extraction(text, entity_map))

        return relationships

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
            source_type = pattern_info["source_type"] # TODO source_type is not used in this implementation. Figure out if needed
            target_type = pattern_info["target_type"] # TODO target_type is not used in this implementation. Figure out if needed
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
            
            except Exception as e:
                # Skip problematic patterns and continue
                continue

        return relationships

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
            # For high temperature, try to extract additional entities
            # TODO Implement more aggressive entity extraction
            # (In a real implementation, this could use more aggressive extraction techniques)
            pass

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
            # TODO Implement more complex relationship inference
            # (In a real implementation, this would add more complex relationship inference)
            pass

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

        except Exception as e:
            error_msg = f"Error extracting knowledge graph from Wikipedia: {e}"
            # Update trace with error if tracer is enabled
            if self.use_tracer and self.tracer and trace_id:
                self.tracer.update_extraction_trace(
                    trace_id=trace_id,
                    status="failed",
                    error=error_msg
                )
            raise RuntimeError(error_msg)

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

        except Exception as e:
            error_result = {
                "error": f"Error validating against Wikidata: {e}",
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
                    error=str(e),
                    validation_results=error_result
                )

            return error_result

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

        except Exception:
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

        except Exception as e:
            print(f"Error querying Wikidata: {e}")
            return []



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

        except Exception as e:
            error_result = {
                "error": f"Error extracting and validating graph: {e}",
                "knowledge_graph": None,
                "validation": {"error": str(e)},
                "coverage": 0.0,
                "metrics": {}
            }

            # Update trace with error if tracer is enabled
            if self.use_tracer and self.tracer and trace_id:
                error_result["trace_id"] = trace_id

                self.tracer.update_extraction_and_validation_trace(
                    trace_id=trace_id,
                    status="failed",
                    error=str(e)
                )

            return error_result

