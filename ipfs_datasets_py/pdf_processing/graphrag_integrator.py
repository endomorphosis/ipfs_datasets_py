"""
GraphRAG Integration Module for PDF Processing Pipeline

Integrates processed PDF content into GraphRAG knowledge graph:
- Creates entity-relationship structures
- Builds knowledge graph representations
- Supports cross-document relationship discovery
- Enables semantic querying and retrieval
- Maintains IPLD data integrity
"""
import asyncio
import hashlib
import logging
import re
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional


import networkx as nx
from nltk import word_tokenize, pos_tag, ne_chunk, tree2conlltags, Tree

# Optional dependencies with proper error handling
try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    np = None
    HAVE_NUMPY = False

try:
    import openai
    HAVE_OPENAI = True
except ImportError:
    openai = None
    HAVE_OPENAI = False

import ipfs_datasets_py.ipfs_multiformats as ipfs_multiformats

get_cid = ipfs_multiformats.ipfs_multiformats_py(None, None).get_cid


from ipfs_datasets_py.ipld import IPLDStorage
from ipfs_datasets_py.pdf_processing.llm_optimizer import (
    LLMDocument, LLMChunk,
    WIKIPEDIA_CLASSIFICATIONS
)

module_logger = logging.getLogger(__name__)


def get_continuous_chunks(text, label):
    chunked = ne_chunk(pos_tag(word_tokenize(text)))
    prev = None
    continuous_chunk = []
    current_chunk = []

    for subtree in chunked:
        if type(subtree) == Tree and subtree.label() == label:
            current_chunk.append(" ".join([token for token, pos in subtree.leaves()]))
        if current_chunk:
            named_entity = " ".join(current_chunk)
            if named_entity not in continuous_chunk:
                continuous_chunk.append(named_entity)
                current_chunk = []
        else:
            continue

    return continuous_chunk

def _extract_entity_names_from_query(query: str, min_chars: int = 0) -> List[str]:
    """
    Extract potential entity names from query text using NLTK NER and POS tagging.

    This method identifies likely entity names within query text using proper
    Natural Language Processing techniques including Named Entity Recognition (NER)
    and Part-of-Speech (POS) tagging from NLTK. It combines NER results with
    proper noun detection to identify person names, organization names, locations,
    and other named entities.

    Args:
        query (str): Query string that may contain entity names.
            Can be normalized or raw query text. 
        min_chars (int): Minimum character length for valid entity names.
            Defaults to 0 characters to filter capture abbreviations (e.g. CA, NY).

    Returns:
        List[str]: List of potential entity names extracted from the query.
            Each name is a complete entity as identified by NER.
            Returns empty list if no entities are found.
            Names are returned in order of appearance in the query.

    Raises:
        TypeError: If query is not a string.
        ValueError: If query is empty or contains only whitespace.
        ImportError: If NLTK is not available.
        RuntimeError: If NLTK data cannot be downloaded or loaded.

    Examples:
        >>> _extract_entity_names_from_query("Who is Bill Gates?")
        ['Bill Gates']
        >>> _extract_entity_names_from_query("Microsoft and Apple are competitors")
        ['Microsoft', 'Apple']
        >>> _extract_entity_names_from_query("path from John Smith to Mary Johnson")
        ['John Smith', 'Mary Johnson']
        >>> _extract_entity_names_from_query("what is artificial intelligence")
        []

    Notes:
        - Uses NLTK's named entity recognition for accurate entity detection
        - Filters out common question words and stop words
        - Combines NER results with proper noun detection for comprehensive coverage
        - Handles punctuation and various text formats appropriately
        - Works with properly formatted natural language queries
    """
    start_time = time.time()
    def _print_time(step: str = ""):
        elapsed = time.time() - start_time
        string = f"integrate_document elapsed time: {elapsed:.2f} seconds"
        string = f"{step} - {string}" if step else string
        print(string)

    #module_logger.info(f"Extracting entities from query: {query}")

    # Input validation
    if not isinstance(query, str):
        raise TypeError("Query must be a string")

    if not query.strip():
        raise ValueError("Query cannot be empty or contain only whitespace")

    # Tokenize and tag
    tokens = word_tokenize(query)
    pos_tags = pos_tag(tokens)
    _print_time(step="Completed POS tagging")

    # Named Entity Recognition
    # NOTE This takes half a second per chunk!
    entities = ne_chunk(pos_tags, binary=False)
    #module_logger.debug(f"NER tree: {entities}")
    _print_time(step="Completed NER chunking")

    # Extract entities from NER tree
    entity_names = []

    # Convert tree to IOB tags for easier processing
    iob_tags = tree2conlltags(entities)
    #module_logger.debug(f"IOB tags: {iob_tags}")

    current_entity = []
    current_label = None

    for word, pos, ner in iob_tags:
        if ner.startswith('B-'):  # Beginning of entity
            # Save previous entity if exists
            if current_entity:
                #module_logger.debug(f"Beginning entity: {current_entity} with label {current_label}")
                entity_names.append(' '.join(current_entity))
            # Start new entity
            current_entity = [word]
            current_label = ner[2:]
        elif ner.startswith('I-') and current_entity:  # Inside entity
            #module_logger.debug(f"Inside entity: {current_entity} with label {current_label}")
            current_entity.append(word)
        else:  # Outside entity
            # Save previous entity if exists
            #module_logger.debug(f"Outside entity: {current_entity} with label {current_label}")
            if current_entity:
                entity_names.append(' '.join(current_entity))
            current_entity = []
            current_label = None
    # Don't forget the last entity
    if current_entity:
        entity_names.append(' '.join(current_entity))
    
    #module_logger.debug(f"Found entities from NER: {entity_names}")

    # Also find proper nouns that might not be caught by NER
    proper_nouns = []
    current_noun_phrase = []

    for word, pos in pos_tags:
        if pos in ['NNP', 'NNPS']:  # Proper nouns
            module_logger.debug(f"word is {pos}: {word}")
            current_noun_phrase.append(word)
        else:
            if current_noun_phrase and len(current_noun_phrase) >= 1:
                noun_phrase = ' '.join(current_noun_phrase)
                module_logger.debug(f"Found proper noun phrase: {noun_phrase}")
                # Only add if not already found by NER and meets criteria
                if (noun_phrase not in entity_names and 
                    len(noun_phrase) >= min_chars and
                    not _is_question_word(noun_phrase)):
                    proper_nouns.append(noun_phrase)
            current_noun_phrase = []

    # Don't forget the last noun phrase
    if current_noun_phrase and len(current_noun_phrase) >= 1:
        noun_phrase = ' '.join(current_noun_phrase)
        if (noun_phrase not in entity_names and 
            len(noun_phrase) >= 3 and
            not _is_question_word(noun_phrase)):
            proper_nouns.append(noun_phrase)

    # Combine NER results with proper noun detection
    all_entities = entity_names + proper_nouns
    
    # Remove duplicates while preserving order
    seen = set()
    unique_entities = []
    for entity in all_entities:
        # if ' ' in entity:
        #     # split it up and check each word
        #     words = entity.split()
        #     for word in words:
        #         word = word.strip()
        #         if word not in seen and len(word) >= min_chars:
        #             seen.add(word)
        #             unique_entities.append(word)
        if entity not in seen:
            seen.add(entity)
            unique_entities.append(entity)

    # Filter out obvious non-entities
    filtered_entities = []
    for entity in unique_entities:
        module_logger.debug(entity)
        if not _is_question_word(entity) and len(entity.strip()) >= min_chars:
            #module_logger.debug(f"{entity} is a valid entity")
            filtered_entities.append(entity)

    #module_logger.debug(f"filtered_entities:\n{filtered_entities}")

    # Check if numbers are in the query
    has_numbers = any(char.isdigit() for char in query)
    if has_numbers:
        #module_logger.debug("has_numbers is True")
        # Consider numbers as part of potential entities IF
        # - They precede or follow a stand-alone proper noun (e.g. 'Death Race 2000', '2020 Olympics')
        # - They are preceded by a determiner (e.g. 'the 19th century', 'The 1970s')
        # Alternatively, consider numbers as NOT entities if:
        # - The whole query is just a number (e.g. '42', '12345252562667', '3.14')
        # - They are the only things left if NLP strips out all non-numeric content.
        # (e.g. 'What is 42') -> ('42')
        # Append the numbers
        for entity in filtered_entities:
            # Check immediately before and after the entity in the query for a number
            entity_start = query.find(entity)
            module_logger.debug(f"Checking entity: {entity} at position {entity_start}")
            if entity_start != -1:
                # Check for numbers before the entity
                before_text = query[:entity_start].strip()
                #module_logger.debug(f"Check before entity: {before_text}")
                if before_text and before_text[-1].isdigit():
                    # Find the full number before the entity
                    words_before = before_text.split()
                    #module_logger.debug(f"words_before: {words_before}")
                    if words_before:
                        last_word = words_before[-1]
                        if any(char.isdigit() for char in last_word):
                            number_entity = f"{last_word} {entity}"
                            #module_logger.debug(f"Found number before entity: {number_entity}")
                            if number_entity not in filtered_entities:
                                filtered_entities.append(number_entity)

                
                # Check for numbers after the entity
                entity_end = entity_start + len(entity)
                after_text = query[entity_end:].strip()
                if after_text and after_text[0].isdigit():
                    # Find the full number after the entity
                    words_after = after_text.split()
                    #module_logger.debug(f"Check after entity: {before_text}")
                    if words_after:
                        first_word = words_after[0]
                        #module_logger.debug(f"first_word: {first_word}")
                        if any(char.isdigit() for char in first_word):
                            number_entity = f"{entity} {first_word}"
                            #module_logger.debug(f"Found number after entity: {number_entity}")
                            if number_entity not in filtered_entities:
                                filtered_entities.append(number_entity)

        # Consolidate entries
        # Ex: ['Main Street', 'San Francisco', 'New York', '123 Main Street', '123']
        # becomes ['San Francisco', 'New York', '123 Main Street']
        consolidated_entities = []
        for entity in filtered_entities:
           pass 


    end_time = time.time()
    module_logger.debug(f"Entity extraction completed in {end_time - start_time:.2f} seconds")
    #module_logger.debug(f"filtered_entities on return:\n{filtered_entities}")
    return filtered_entities

def _is_question_word(word: str) -> bool:
    """Helper method to check if a word is a common question word or stop word."""
    question_words = {
        'who', 'what', 'when', 'where', 'why', 'how', 'which', 'whose',
        'can', 'could', 'would', 'should', 'will', 'may', 'might',
        'is', 'are', 'was', 'were', 'been', 'being', 'have', 'has', 'had',
        'do', 'does', 'did', 'the', 'and', 'or', 'but', 'a', 'an', 'this',
        'that', 'these', 'those', 'from', 'to', 'in', 'on', 'at', 'for'
    }
    return word in question_words

import nltk

from nltk.corpus import brown


def _confirm_match_with_nltk(text: str, type_: str) -> str:
    """
    Confirm entity types from text using NLTK.
    
    Args:
        text: a string of text. Should be just an entity (e.g. Apple Inc, New York, etc.)
        type_: the expected type of the entity (e.g. 'person', 'organization', 'location')
    
    Returns:
        str: Either the original entity label, or the confirmed NLTK label.
            Conflicts default to the NLTK label.
    """
    nltk_entities = []
    
    # Tokenize, POS tag, and NER chunk
    tokens = word_tokenize(text)
    pos_tags = pos_tag(tokens)
    ner_tree = ne_chunk(pos_tags, binary=False)

    # Convert tree to IOB tags for easier processing
    iob_tags = tree2conlltags(ner_tree)

    current_entity = []
    current_label = None

    # Map NLTK labels to internal types
    label_map = {
        'PERSON': 'person',
        'ORGANIZATION': 'organization',
        'GPE': 'location',  # Geopolitical Entity
        'LOCATION': 'location',
        'FACILITY': 'location',
        'DATE': 'date',
        'MONEY': 'currency'
    }

    # Process IOB tags to find entities
    for word, pos, ner in iob_tags:
        if ner.startswith('B-'):  # Beginning of a new entity
            if current_entity:
                # This case is unlikely if the input text is a single entity, but good to handle
                nltk_entities.append((' '.join(current_entity), current_label))
            current_entity = [word]
            current_label = ner[2:]
        elif ner.startswith('I-') and current_label == ner[2:]: # Inside the same entity
            current_entity.append(word)
        else: # Outside an entity or a different entity starts without 'B-' tag
            if current_entity:
                nltk_entities.append((' '.join(current_entity), current_label))
            current_entity = []
            current_label = None

    # Add the last entity if it exists
    if current_entity:
        nltk_entities.append((' '.join(current_entity), current_label))

    # If NLTK found an entity, use its type
    if nltk_entities:
        # Assuming the most prominent entity in the text is the correct one
        # For a short text that is supposed to be one entity, there should ideally be only one.
        # We take the first one found.
        _, nltk_label = nltk_entities[0]
        
        # Map the NLTK label to our internal type system
        confirmed_type = label_map.get(nltk_label, type_)
        
        # If NLTK's type is different, prefer NLTK's classification.
        if confirmed_type != type_:
            return confirmed_type

    # If NLTK did not find any entity or confirmed the type, return the original type
    return type_






@dataclass
class Entity:
    """
    An entity extracted from documents for knowledge graph construction, structured as a dataclass.

    An entity is a distinct object, concept, person, organization, or location
    identified within text chunks during the document processing pipeline.

    Attributes:
        id (str): Unique identifier for the entity within the knowledge graph.
        name (str): The canonical name or primary label of the entity.
        type (str): Category classification of the entity. Common types include:
            - 'person': Individual people
            - 'organization': Companies, institutions, groups
            - 'concept': Abstract ideas, topics, themes
            - 'location': Geographic places, addresses
            - 'event': Occurrences, incidents, activities
            - 'object': Physical items, products, artifacts
        description (str): Detailed textual description providing context and 
            additional information about the entity.
        confidence (float): Confidence score (0.0-1.0) indicating the reliability
            of the entity extraction and classification.
        source_chunks (List[str]): List of chunk identifiers where this entity
            appears, enabling traceability back to source documents.
        properties (Dict[str, Any]): Additional metadata and attributes specific
            to the entity type (e.g., dates, relationships, custom fields).
        embedding (Optional[Any]): High-dimensional vector representation
            of the entity for semantic similarity calculations (numpy array when 
            available). Defaults to None if not computed.

    Example:
        >>> entity = Entity(
        ...     id="ent_001",
        ...     name="John Smith",
        ...     type="person",
        ...     description="Software engineer at Tech Corp",
        ...     confidence=0.95,
        ...     source_chunks=["chunk_1", "chunk_3"],
        ...     properties={"role": "engineer", "company": "Tech Corp"}
        ... )
    """
    id: str # NOTE Should be CID
    name: str
    type: str  # 'person', 'organization', 'concept', 'location', etc.
    description: str
    confidence: float
    source_chunks: List[str]  # Chunk IDs where entity appears
    properties: Dict[str, Any]
    embedding: Optional[Any] = None  # np.ndarray when numpy is available
    gateway_url: str = "ipfs_datasets_py.com"

    @property
    def ipfs_uri(self):
        """
        IPFS uri for the entity
        Immutable pointer to the resources itself.
        """
        uri_string = f"<https://{self.gateway_url}/ipfs/{self.id}/{self.name}>"
        return uri_string

    @property
    def ipns_uri(self): # TODO
        """
        IPNS uri for the entity. Basically a mutable pointer to the IPFS uri.
        See: https://docs.ipfs.tech/concepts/ipns/#how-ipns-works
        """
        pass

from enum import StrEnum

class OwlFamily(StrEnum):
    """
    From: https://en.wikipedia.org/wiki/Web_Ontology_Language, accessed 9/8/2025
    """
    OWL2_FUNCTIONAL_SYNTAX = "OWL2 Functional Syntax"
    OWL2_XML_STYLE = "OWL2 XML Syntax"
    MANCHESTER_SYNTAX = "Manchester Syntax"
    RDF_XML_SYNTAX = "RDF/XML Syntax"
    RDF_TURTLE = "RDF/Turtle"


@dataclass
class Owl:
    """
    See: https://en.wikipedia.org/wiki/Web_Ontology_Language
    """
    entity: Entity
    spec: OwlFamily = OwlFamily.MANCHESTER_SYNTAX

    def __str__(self):
        match self.spec.value:
            case OwlFamily.MANCHESTER_SYNTAX:
                owl_string = f"""
Ontology: {self.entity.ipfs_uri}
Class: {self.entity.name}


"""
            case _:
                raise NotImplementedError("This ontology style is not yet supported")
        return owl_string


@dataclass
class Relationship:
    """
    Represents a relationship between two entities in a knowledge graph.

    This dataclass encapsulates the complete information about a relationship,
    including its participants, type, confidence metrics, and supporting evidence.

    Attributes:
        id (str): Unique identifier for this relationship instance.
        source_entity_id (str): Identifier of the entity that is the source/subject 
            of the relationship.
        target_entity_id (str): Identifier of the entity that is the target/object 
            of the relationship.
        relationship_type (str): The type or category of relationship (e.g., 
            "works_for", "located_in", "related_to").
        description (str): Human-readable description providing context and details 
            about the relationship.
        confidence (float): Confidence score indicating the reliability of this 
            relationship, typically in the range [0.0, 1.0].
        source_chunks (List[str]): List of source text chunks or document sections 
            that provide evidence for this relationship.
        properties (Dict[str, Any]): Additional metadata and properties associated 
            with the relationship, allowing for flexible extension of relationship 
            attributes.

    Example:
        >>> relationship = Relationship(
        ...     id="rel_001",
        ...     source_entity_id="person_123",
        ...     target_entity_id="company_456",
        ...     relationship_type="works_for",
        ...     description="John Doe is employed by Acme Corp as a software engineer",
        ...     confidence=0.95,
        ...     source_chunks=["chunk_1", "chunk_5"],
        ...     properties={"role": "software_engineer", "start_date": "2023-01-15"}
        ... )
    """
    id: str
    source_entity_id: str
    target_entity_id: str
    relationship_type: str
    description: str
    confidence: float
    source_chunks: List[str]
    properties: Dict[str, Any]


@dataclass
class KnowledgeGraph:
    """
    Complete knowledge graph representation containing entities, relationships, and document chunks.

    This class represents a comprehensive knowledge graph extracted from a document,
    including all entities, their relationships, the original text chunks, and associated
    metadata. It serves as the primary data structure for storing and managing
    knowledge graphs within the IPFS datasets system.

    Attributes:
        graph_id (str): Unique identifier for this knowledge graph instance.
        document_id (str): Identifier of the source document from which this graph was extracted.
        entities (List[Entity]): Collection of all entities identified in the document.
        relationships (List[Relationship]): Collection of relationships between entities.
        chunks (List[LLMChunk]): Original text chunks used for entity and relationship extraction.
        metadata (Dict[str, Any]): Additional metadata about the graph generation process,
            including extraction parameters, model information, and processing statistics.
        creation_timestamp (str): ISO 8601 timestamp indicating when the graph was created.
        ipld_cid (Optional[str]): Content identifier for IPFS/IPLD storage, set when the
            graph is stored in a distributed system. Defaults to None for newly created graphs.

    Example:
        >>> kg = KnowledgeGraph(
        ...     graph_id="kg_001",
        ...     document_id="doc_123",
        ...     entities=[entity1, entity2],
        ...     relationships=[rel1, rel2],
        ...     chunks=[chunk1, chunk2],
        ...     metadata={"model": "gpt-4", "confidence": 0.95},
        ...     creation_timestamp="2024-01-01T12:00:00Z"
        ... )
    """
    graph_id: str
    document_id: str
    entities: List[Entity]
    relationships: List[Relationship]
    chunks: List[LLMChunk]
    metadata: Dict[str, Any]
    creation_timestamp: str
    ipld_cid: Optional[str] = None


@dataclass
class CrossDocumentRelationship:
    """
    Represents a relationship between entities that spans across multiple documents.

    This dataclass captures relationships discovered between entities from different
    source documents, enabling cross-document knowledge discovery and connection
    mining within the knowledge graph system.

    Attributes:
        id (str): Unique identifier for this cross-document relationship instance.
        source_document_id (str): Identifier of the document containing the source entity.
        target_document_id (str): Identifier of the document containing the target entity.
        source_entity_id (str): Identifier of the entity in the source document that
            participates in this relationship.
        target_entity_id (str): Identifier of the entity in the target document that
            participates in this relationship.
        relationship_type (str): Type of cross-document relationship discovered.
            Common types include:
            - 'same_entity': Same entity mentioned across documents
            - 'similar_entity': Similar or related entities
            - 'references': One entity references another across documents
            - 'related_concept': Conceptually related entities
        confidence (float): Confidence score (0.0-1.0) indicating the reliability
            of the cross-document relationship discovery.
        evidence_chunks (List[str]): List of text chunk identifiers from both
            documents that provide evidence supporting this relationship.

    Example:
        >>> cross_rel = CrossDocumentRelationship(
        ...     id="cross_rel_001",
        ...     source_document_id="doc_123",
        ...     target_document_id="doc_456",
        ...     source_entity_id="entity_abc",
        ...     target_entity_id="entity_def",
        ...     relationship_type="same_entity",
        ...     confidence=0.95,
        ...     evidence_chunks=["chunk_1", "chunk_2", "chunk_10"]
        ... )
    """
    id: str
    source_document_id: str
    target_document_id: str
    source_entity_id: str
    target_entity_id: str
    relationship_type: str
    confidence: float
    evidence_chunks: List[str]

class GraphRAGIntegrator:
    """
    GraphRAG Integrator for PDF Content Processing
    The GraphRAGIntegrator class provides comprehensive functionality for integrating PDF content
    into GraphRAG (Graph Retrieval-Augmented Generation) knowledge structures. It processes
    LLM-optimized documents, extracts entities and relationships, creates knowledge graphs,
    and enables sophisticated querying capabilities across document collections.
    This class serves as the core component for building knowledge graphs from PDF documents,
    supporting both single-document analysis and cross-document relationship discovery.

    Key Features:
    - Entity extraction using pattern matching and NLP techniques
    - Relationship inference based on co-occurrence and context analysis
    - Cross-document entity linking and relationship discovery
    - IPLD (InterPlanetary Linked Data) storage integration
    - NetworkX graph representations for advanced analysis
    - Natural language querying capabilities
    - Entity neighborhood exploration

    Attributes:
        storage (IPLDStorage): IPLD storage instance for persistent graph storage
        similarity_threshold (float): Threshold for entity similarity matching (0.0-1.0)
        entity_extraction_confidence (float): Minimum confidence for entity extraction (0.0-1.0)
        knowledge_graphs (Dict[str, KnowledgeGraph]): Collection of document knowledge graphs
        global_entities (Dict[str, Entity]): Global entity registry across all documents
        cross_document_relationships (List[CrossDocumentRelationship]): Inter-document relationships
        document_graphs (Dict[str, nx.DiGraph]): NetworkX representations per document
        global_graph (nx.DiGraph): Global NetworkX graph combining all documents

    Public Methods:
        integrate_document(llm_document: LLMDocument) -> KnowledgeGraph:
            Extracts entities, relationships, creates knowledge graph, stores in IPLD,
            and updates global graph structures.
        query_graph(query: str, graph_id: Optional[str] = None, max_results: int = 10) -> Dict[str, Any]:
            Query the knowledge graph using natural language queries.
            Supports both document-specific and global graph querying with keyword-based
            and semantic search capabilities.
        get_entity_neighborhood(entity_id: str, depth: int = 2) -> Dict[str, Any]:
            Retrieve the neighborhood of a specific entity within the graph.
            Returns subgraph containing all nodes and edges within specified depth
            from the target entity.

    Private Methods:
        _extract_entities_from_chunks(chunks: List[LLMChunk]) -> List[Entity]:
            Extract and consolidate entities from document chunks using pattern matching
            and confidence filtering.
        _extract_entities_from_text(text: str, chunk_id: str) -> List[Dict[str, Any]]:
            Extract entities from individual text chunks using regex patterns for
            persons, organizations, locations, dates, and currency.
        _extract_relationships(entities: List[Entity], chunks: List[LLMChunk]) -> List[Relationship]:
            Extract relationships between entities within and across chunks using
            co-occurrence analysis and context inference.
        _extract_chunk_relationships(entities: List[Entity], chunk: LLMChunk) -> List[Relationship]:
            Extract relationships between entities within a single chunk based on
            co-occurrence and contextual analysis.
        _extract_cross_chunk_relationships(entities: List[Entity], chunks: List[LLMChunk]) -> List[Relationship]:
            Extract relationships between entities across different chunks using
            narrative sequence analysis.
        _infer_relationship_type(entity1: Entity, entity2: Entity, context: str) -> Optional[str]:
            Infer relationship type between two entities based on contextual keywords
            and entity types (e.g., 'works_for', 'founded', 'partners_with').
        _find_chunk_sequences(chunks: List[LLMChunk]) -> List[List[str]]:
            Identify sequences of related chunks (e.g., same page, sequential order)
            for narrative relationship extraction.
        _create_networkx_graph(knowledge_graph: KnowledgeGraph) -> nx.DiGraph:
            Create NetworkX directed graph representation from knowledge graph
            with entities as nodes and relationships as edges.
        _merge_into_global_graph(knowledge_graph: KnowledgeGraph):
            Merge document-specific knowledge graph into global graph structure,
            updating entity registry and NetworkX representation.
        _discover_cross_document_relationships(knowledge_graph: KnowledgeGraph):
            Discover and create relationships between entities across different documents
            using entity similarity and matching algorithms.
        _find_similar_entities(entity: Entity) -> List[Entity]:
            Find entities similar to a given entity across all documents using
            name similarity and type matching.
        _calculate_text_similarity(text1: str, text2: str) -> float:
            Calculate Jaccard similarity between two text strings based on
            word-level intersection and union.
        _store_knowledge_graph_ipld(knowledge_graph: KnowledgeGraph) -> str:
            Store knowledge graph in IPLD format with JSON serialization,
            handling numpy array conversion for embeddings.

    Examples:
        integrator = GraphRAGIntegrator(
            similarity_threshold=0.8,
            entity_extraction_confidence=0.6
        # Process document
        knowledge_graph = await integrator.integrate_document(llm_document)
        # Query the graph
        results = await integrator.query_graph("companies founded by John Smith")
        # Explore entity relationships
        neighborhood = await integrator.get_entity_neighborhood("entity_12345", depth=2)

    Notes:
        - Entity extraction uses regex patterns and can be enhanced with advanced NLP models
        - Relationship inference is based on co-occurrence and keyword matching
        - Cross-document relationships enable knowledge discovery across document collections
        - IPLD storage provides content-addressable persistence for knowledge graphs
        - NetworkX integration enables advanced graph analysis and algorithms
    """
    def __init__(self,
                 similarity_threshold: float = 0.8,
                 entity_extraction_confidence: float = 0.6,
                 logger: logging.Logger = logging.getLogger(__name__),
                 storage: Optional[IPLDStorage] = None,
                 ) -> None:
        """
        This class integrates Knowledge Graphs with Retrieval-Augmented Generation (RAG)
        for enhanced document processing and analysis capabilities.

        Args:
            storage (Optional[IPLDStorage], optional): IPLD storage instance for data persistence.
            Defaults to a new IPLDStorage instance if not provided.
            similarity_threshold (float, optional): Threshold for entity similarity matching.
            Values between 0.0 and 1.0, where higher values require more similarity.
            Defaults to 0.8.
            entity_extraction_confidence (float, optional): Minimum confidence score for 
            entity extraction. Values between 0.0 and 1.0, where higher values require
            more confidence. Defaults to 0.6.

        Attributes initialized:
            storage (IPLDStorage): IPLD storage instance for data persistence.
            similarity_threshold (float): Threshold for entity similarity matching.
            entity_extraction_confidence (float): Minimum confidence for entity extraction.
            knowledge_graphs (Dict[str, KnowledgeGraph]): Storage for document-specific 
            knowledge graphs, keyed by document identifier.
            global_entities (Dict[str, Entity]): Global registry of entities across all
            documents, keyed by entity identifier.
            cross_document_relationships (List[CrossDocumentRelationship]): List of 
            relationships that span across multiple documents.
            document_graphs (Dict[str, nx.DiGraph]): NetworkX directed graphs for each
            document, keyed by document identifier.
            global_graph (nx.DiGraph): Global NetworkX directed graph containing all
            entities and relationships across documents.

        Examples:
            Basic usage with default settings:

            >>> integrator = GraphRAGIntegrator()
            >>> print(f"Similarity threshold: {integrator.similarity_threshold}")
            Similarity threshold: 0.8

            Custom configuration with higher confidence requirements:

            >>> custom_storage = IPLDStorage()
            >>> integrator = GraphRAGIntegrator(
            ...     storage=custom_storage,
            ...     similarity_threshold=0.9,
            ...     entity_extraction_confidence=0.8
            ... )

            Processing a document and querying the knowledge graph:

            >>> # Process a document
            >>> llm_doc = LLMDocument(document_id="doc123", title="Research Paper", chunks=[...])
            >>> kg = await integrator.integrate_document(llm_doc)
            >>> print(f"Created graph with {len(kg.entities)} entities")

            >>> # Query for specific information
            >>> results = await integrator.query_graph("artificial intelligence companies")
            >>> for entity in results['entities']:
            ...     print(f"Found: {entity['name']} ({entity['type']})")

            >>> # Explore entity relationships
            >>> neighborhood = await integrator.get_entity_neighborhood("entity_123", depth=2)
            >>> print(f"Neighborhood contains {neighborhood['node_count']} nodes")

        Raises:
            TypeError: If storage is not an IPLDStorage instance (when provided)
                or if similarity_threshold or entity_extraction_confidence is not a number
            ValueError: If similarity_threshold or entity_extraction_confidence
              is not between 0.0 and 1.0
        """
        self._initialized = False
        # Validate storage parameter
        if storage is not None and not isinstance(storage, IPLDStorage):
            for required_attr in ['store', 'retrieve']:
                if not hasattr(storage, required_attr):
                    raise TypeError(f"storage must implement '{required_attr}' method")

        # Validate similarity_threshold and entity_extraction_confidence parameters
        type_check_dict = {
            "similarity_threshold": similarity_threshold, 
            "entity_extraction_confidence": entity_extraction_confidence
        }
        for key, value in type_check_dict.items():
            if not isinstance(value, (int, float)):
                raise TypeError(f"{key} must be an int or float, got {type(value).__name__}")
            if not (0.0 <= value <= 1.0):
                raise ValueError(f"{key} must be between 0.0 and 1.0, got {value}")

        self.logger = logger or module_logger
        self.storage = storage or IPLDStorage()

        self.similarity_threshold = similarity_threshold
        self.entity_extraction_confidence = entity_extraction_confidence

        for attr_name, type_ in [("storage", IPLDStorage), ("logger", logging.Logger)]:
            attr_value = getattr(self, attr_name)
            if not isinstance(attr_value, type_):
                raise TypeError(f"{attr_name} must be an instance of {type_.__name__}, got {type(attr_value).__name__}")

        # Graph storage
        self.knowledge_graphs: Dict[str, KnowledgeGraph] = {}
        self.global_entities: Dict[str, Entity] = {}
        self.cross_document_relationships: List[CrossDocumentRelationship] = []

        # NetworkX graphs for analysis
        self.document_graphs: Dict[str, nx.DiGraph] = {}
        self.global_graph = nx.DiGraph()
        self._initialized = True

    @property
    def initialized(self) -> bool:
        """Indicates if the integrator has been properly initialized."""
        return self._initialized

    async def integrate_document(self, llm_document: LLMDocument) -> KnowledgeGraph:
        """
        Integrate an LLM-optimized document into the GraphRAG system.

        This method performs end-to-end integration of a processed document into the GraphRAG
        knowledge graph system. It extracts entities and relationships from document chunks,
        creates a comprehensive knowledge graph, stores it in IPLD for distributed access,
        and merges it with the global knowledge graph to enable cross-document reasoning.

        Args:
            llm_document (LLMDocument): Pre-processed document containing optimized chunks,
                                       embeddings, and metadata from LLM processing pipeline.
                                       Must include document_id, title, and processed chunks.
            KnowledgeGraph: Comprehensive knowledge graph object containing:
                           - Extracted entities with types and attributes
                           - Discovered relationships with confidence scores
                           - Document chunks with semantic mappings
                           - IPLD CID for distributed storage
                           - Processing metadata and timestamps
                           - Unique graph identifier for tracking

        Returns:
            KnowledgeGraph: The created knowledge graph containing entities, relationships,
                            and metadata for the integrated document.

        Raises:
            ValueError: If llm_document is invalid or missing required fields
            IPLDStorageError: If knowledge graph cannot be stored in IPLD
            GraphProcessingError: If entity/relationship extraction fails
            NetworkError: If cross-document relationship discovery fails

        Example:
            >>> document = LLMDocument(document_id="doc123", title="Research Paper", chunks=[...])
            >>> kg = await integrator.integrate_document(document)

            >>> print(f"Created knowledge graph with {len(kg.entities)} entities")

        Note:
            This is an expensive operation that involves multiple AI model calls for entity
            and relationship extraction. Consider batching documents or using async processing
            for large document sets. The resulting knowledge graph is automatically merged
            with existing graphs to maintain global consistency.
        """
        debug_timer_start = time.time()
        def _print_time(step: str = ""):
            elapsed = time.time() - debug_timer_start
            string = f"integrate_document elapsed time: {elapsed:.2f} seconds"
            string = f"{step} - {string}" if step else string
            print(string)

        # Input validation
        if llm_document is None:
            raise TypeError("llm_document cannot be None")

        if not isinstance(llm_document, LLMDocument):
            raise TypeError("llm_document must be an instance of LLMDocument")
        
        if llm_document.document_id is None:
            raise ValueError("document_id is required")
        
        if llm_document.title is None:
            raise ValueError("title is required")
        
        if llm_document.chunks is not None:
            for chunk in llm_document.chunks:
                if not hasattr(chunk, 'chunk_id'):  # Basic check for LLMChunk-like object
                    raise TypeError("All chunks must be LLMChunk instances")
        
        # Check for duplicate document and warn if replacing
        existing_graphs = [kg for kg in self.knowledge_graphs.values() 
                          if kg.document_id == llm_document.document_id]
        if existing_graphs:
            self.logger.warning(f"Document {llm_document.document_id} already exists in knowledge graphs. "
                          f"Overwriting existing knowledge graph.")
        
        self.logger.info(f"Starting GraphRAG integration for document: {llm_document.document_id}")
        _print_time(step="Start integration")

        # Extract entities from chunks
        entities = await self._extract_entities_from_chunks(llm_document.chunks)
        _print_time(step="Entity extraction complete")

        # Extract relationships
        relationships = await self._extract_relationships(entities, llm_document.chunks)

        # Create deterministic graph ID based on document content
        document_content = "".join(chunk.content.strip() for chunk in llm_document.chunks)

        graph_id_hash = get_cid(document_content)

        # Create knowledge graph
        knowledge_graph = KnowledgeGraph(
            graph_id=f"kg_{llm_document.document_id}_{graph_id_hash}",
            document_id=llm_document.document_id,
            entities=entities,
            relationships=relationships,
            chunks=llm_document.chunks,
            metadata={
                'document_title': llm_document.title,
                'entity_count': len(entities),
                'relationship_count': len(relationships),
                'chunk_count': len(llm_document.chunks),
                'similarity_threshold': self.similarity_threshold,
                'entity_extraction_confidence': getattr(self, 'entity_extraction_confidence', 0.8),
                'processing_timestamp': datetime.now().isoformat()
            },
            creation_timestamp=datetime.now().isoformat() + 'Z'
        )
        self.logger.debug(f"knowledge_graph: {knowledge_graph}")

        # Store in IPLD
        ipld_cid = await self._store_knowledge_graph_ipld(knowledge_graph)
        knowledge_graph.ipld_cid = ipld_cid

        # Update internal storage
        self.knowledge_graphs[knowledge_graph.graph_id] = knowledge_graph

        # Create NetworkX representation
        nx_graph = await self._create_networkx_graph(knowledge_graph)
        self.document_graphs[llm_document.document_id] = nx_graph

        # Merge with global graph
        await self._merge_into_global_graph(knowledge_graph)

        # Discover cross-document relationships
        await self._discover_cross_document_relationships(knowledge_graph)

        self.logger.info(f"GraphRAG integration complete: {len(entities)} entities, {len(relationships)} relationships")
        return knowledge_graph
    
    async def _extract_entities_from_chunks(self, chunks: List[LLMChunk]) -> List[Entity]:
        """Extract and consolidate entities from a list of LLM chunks.

        This method processes text chunks to identify and extract named entities, then
        consolidates duplicate entities across chunks to create a unified entity list.
        The extraction process includes entity deduplication, confidence scoring, and
        property merging.

        Args:
            chunks (List[LLMChunk]): List of text chunks to process for entity extraction.
                Each chunk should contain content and a unique chunk_id.

        Returns:
            List[Entity]: A filtered list of unique entities extracted from all chunks.
                Only entities meeting the minimum confidence threshold are included.
                Each entity contains:
                - Unique ID generated from name and type hash
                - Consolidated properties from all mentions
                - Maximum confidence score across all mentions
                - List of source chunk IDs where the entity was found

        Raises:
            TypeError: If chunks is not a list or contains non-LLMChunk instances.

            Exception: May raise exceptions from the underlying entity extraction service
                or if chunk processing fails.

        Note:
            - Entities are deduplicated based on case-insensitive name and type matching
            - Entity confidence scores are maximized across multiple mentions
            - Properties from different mentions are merged (first occurrence wins for conflicts)
            - Only entities with confidence >= self.entity_extraction_confidence are returned
        """
        debug_timer_start = time.time()
        def _print_time(step: str = ""):
            elapsed = time.time() - debug_timer_start
            string = f"integrate_document elapsed time: {elapsed:.2f} seconds"
            string = f"{step} - {string}" if step else string
            print(string)

        # Validate input types
        if not isinstance(chunks, list):
            raise TypeError("chunks must be a list")

        for chunk in chunks:
            if not isinstance(chunk, LLMChunk):
                raise TypeError(f"All chunks must be LLMChunk instances, got {type(chunk).__name__}")
            if not hasattr(chunk, 'content') or not hasattr(chunk, 'chunk_id'):
                raise AttributeError("LLMChunk must have 'content' and 'chunk_id' attributes")

        entity_mentions = {}  # Track entity mentions across chunks
        chunk_entity_queue = asyncio.Queue()
        _print_time(step="Start entity extraction from chunks")
        for idx, chunk in enumerate(chunks, start=1):
            # Extract entities from chunk content
            try:
                chunk_entities = await self._extract_entities_from_text(
                    chunk.content, 
                    chunk.chunk_id
                )
            except Exception as e:
                self.logger.error(f"Failed to extract entities for chunk {chunk.chunk_id}: {e}")
                raise RuntimeError(f"Entity extraction service for chunk {chunk.chunk_id}: {e}") from e
            else:
                self.logger.debug(f"chunk_entities: {chunk_entities}")
                _print_time(step=f"Extracted entities from chunk {idx}/{len(chunks)}")
                chunk_entity_queue.put_nowait((chunk, chunk_entities))

        while not chunk_entity_queue.empty():
            chunk, chunk_entities = await chunk_entity_queue.get()
            for entity_data in chunk_entities:

                assert isinstance(entity_data, dict), \
                    f"expected entity_data to be dict, got {type(entity_data).__name__} instead"

                entity_key = (entity_data['name'].lower(), entity_data['type'])

                if entity_key in entity_mentions:
                    # Update existing entity
                    existing_entity = entity_mentions[entity_key]
                    if chunk.chunk_id not in existing_entity.source_chunks:
                        existing_entity.source_chunks.append(chunk.chunk_id)
                    existing_entity.confidence = max(existing_entity.confidence, entity_data['confidence'])

                    # Merge properties (first occurrence wins for conflicts)
                    for key, value in entity_data.get('properties', {}).items():
                        if key not in existing_entity.properties:
                            existing_entity.properties[key] = value
                else:
                    # Create new entity
                    entity_key_for_id = f"{entity_data['name']}_{entity_data['type']}"
                    entity_id = f"entity_{hashlib.md5(entity_key_for_id.encode()).hexdigest()[:8]}"
                    
                    entity = Entity(
                        id=entity_id,
                        name=entity_data['name'],
                        type=entity_data['type'],
                        description=entity_data.get('description', ''),
                        confidence=entity_data['confidence'],
                        source_chunks=[chunk.chunk_id],
                        properties=entity_data.get('properties', {}),
                        embedding=entity_data.get('embedding')
                    )
                    entity_mentions[entity_key] = entity
            _print_time(step=f"Processed chunk {idx}/{len(chunks)} for entity consolidation")
        _print_time(step="Entity extraction from chunks complete")

        # Get all unique entities
        entities = list(entity_mentions.values())

        # Filter entities by confidence
        filtered_entities = [
            entity for entity in entities 
            if entity.confidence >= self.entity_extraction_confidence
        ]
        _print_time(step="Entity filtering complete")
        
        self.logger.info(f"Extracted {len(filtered_entities)} entities from {len(chunks)} chunks")
        return filtered_entities
    
    async def _extract_entities_from_text(self, text: str, chunk_id: str) -> List[Dict[str, Any]]:
        """Extract named entities from a text chunk using pattern matching.

        This method identifies various types of entities (persons, organizations, locations,
        dates, and currency amounts) from the input text using regular expression patterns.
        It provides a foundation for entity extraction that can be enhanced with more
        sophisticated NLP models.

        Args:
            text (str): The input text chunk from which to extract entities.
            chunk_id (str): Unique identifier for the text chunk, used for tracking
                           and linking entities back to their source.

        Returns:
            List[Dict[str, Any]]: A list of unique entities found in the text, where each
                                 entity is represented as a dictionary containing:
                                 - 'name': The extracted entity text
                                 - 'type': Entity category. 
                                 - 'description': Human-readable description of the entity
                                 - 'confidence': Confidence score (0.7 for pattern matching)
                                 - 'properties': Additional metadata including extraction method and source chunk

        Entity Types Supported:
            - person: Names with titles (Dr. John Smith) or standard format (John Smith)
            - organization: Companies, corporations, universities with common suffixes
            - location: Addresses and city/state combinations
            - date: Various date formats (MM/DD/YYYY, Month DD, YYYY)
            - currency: Dollar amounts and currency expressions

        Raises:
            TypeError: If text or chunk_id is not a string.
            re.error: If any of the regex patterns are malformed (unlikely with static patterns).
        """
        # Input validation
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        if not isinstance(chunk_id, str):
            raise TypeError("chunk_id must be a string")
        
        # Handle empty or whitespace-only text
        if not text.strip():
            return []
        
        entities = []

        # results = _extract_entity_names_from_query(text)
        # self.logger.debug(f"results:\n{results}")
        # for result in results:
        #     output = get_continuous_chunks(result, 'GPE')
        #     self.logger.debug(f"output:\n{output}")

        # Named Entity Recognition patterns (can be enhanced with NLP models)
        # TODO Replace with NLTK or other NLP library for better accuracy.
        # Process organizations first to avoid conflicts with person patterns
        patterns = {
            'organization': [
                r'\b[A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*)*\s+(?:Inc\.?|Corp\.?|LLC|Ltd\.?|Company|Corporation)\b',  # Apple Inc., Microsoft Corporation
                r'\b[A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*)*\s+University\b',  # Harvard University
                r'\b[A-Z]{2,}(?:\s+[A-Z][a-zA-Z]+)*\b',  # IBM, NASA (all caps acronyms)
            ],
            'person': [
                r'\b(?:Dr|Mr|Ms|Mrs|Prof)\.?\s+[A-Z][a-zA-Z]+\s+[A-Z][a-zA-Z]+\b',  # Dr. John Smith (titles first)
                r'\b[A-Z][a-zA-Z]+\s+[A-Z][a-zA-Z]+\b(?!\s+(?:Inc\.?|Corp\.?|LLC|Ltd\.?|Company|Corporation|University))',  # John Smith (not followed by company suffixes)
            ],
            'location': [
                r'\b[A-Z][a-zA-Z]+(?:,\s*[A-Z][a-zA-Z]+)*,\s*[A-Z]{2}\b',  # San Francisco, CA
                r'\b\d+\s+[A-Z][a-zA-Z]+\s+(?:Street|Avenue|Road|Boulevard|Drive|St|Ave|Rd|Blvd|Dr)\b',  # 123 Main Street
            ],
            'date': [
                r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b',  # 12/25/2023
                r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b'  # January 15, 2024
            ],
            'currency': [
                r'\$\d{1,3}(?:,\d{3})*(?:\.\d{2})?\b',  # $50,000
                r'\b\d{1,3}(?:,\d{3})*(?:\.\d{2})?\s+(?:dollars?|USD|cents?)\b'  # 25000 dollars
            ]
        }

        # Track all matches to avoid overlaps
        all_matches = []

        for entity_type, type_patterns in patterns.items():
            for pattern in type_patterns:
                for match in re.finditer(pattern, text):
                    match_text = match.group().strip()
                    if len(match_text) > 2:  # Minimum length filter
                        all_matches.append({
                            'text': match_text,
                            'type': entity_type,
                            'start': match.start(),
                            'end': match.end()
                        })

        # Sort by start position and remove overlaps (prefer longer matches)
        all_matches.sort(key=lambda x: (x['start'], -(x['end'] - x['start'])))
        self.logger.debug(f"all_matches:\n{all_matches}")

        # Remove overlapping matches
        non_overlapping = []
        for match in all_matches:
            # Check if this match overlaps with any already accepted match
            overlaps = False
            for accepted in non_overlapping:
                if not (match['end'] <= accepted['start'] or match['start'] >= accepted['end']):
                    overlaps = True
                    break

            if not overlaps:
                non_overlapping.append(match)
        self.logger.debug(f"non_overlapping:\n{non_overlapping}")

        # Convert to entity format
        for match in non_overlapping:

            type_ = _confirm_match_with_nltk(match['text'], match['type'])

            entities.append({
                'name': match['text'],
                'type': type_,
                'description': f'{match["type"].capitalize()} found in chunk {chunk_id}',
                'confidence': 0.7,  # Base confidence for pattern matching
                'properties': {
                    'extraction_method': 'regex_pattern_matching',
                    'source_chunk': chunk_id
                }
            })

        # Remove duplicates by name (case-insensitive)
        unique_entities = []
        seen_names = set()
        for entity in entities:
            name_key = entity['name'].lower()
            if name_key not in seen_names:
                seen_names.add(name_key)
                unique_entities.append(entity)

        return unique_entities

    async def _extract_relationships(self, 
                                   entities: List[Entity], 
                                   chunks: List[LLMChunk]) -> List[Relationship]:
        """Extract relationships between entities from text chunks.

        This method performs a two-phase relationship extraction process:
        1. Intra-chunk relationships: Identifies relationships between entities that
            appear together within the same text chunk
        2. Cross-chunk relationships: Discovers relationships between entities that
            span across different chunks within the same document

        The method builds an entity index for efficient lookup and processes
        relationships at both the local (chunk-level) and document-level scope
        to ensure comprehensive relationship mapping.

        Args:
            entities (List[Entity]): List of extracted entities with their source
                chunk references
            chunks (List[LLMChunk]): List of text chunks to analyze for relationships

        Returns:
            List[Relationship]: Combined list of all discovered relationships,
                including both intra-chunk and cross-chunk relationships

        Raises:
            TypeError: If entities or chunks are not lists
            AttributeError: If any entity is missing 'source_chunks' attribute or
            any chunk is missing 'chunk_id' attribute
            - Returns empty list if either entities or chunks are empty

        Example:
            

        Note:
            - Chunks with fewer than 2 entities are skipped for intra-chunk processing
            - Cross-chunk relationship extraction considers entity co-occurrence patterns
            - The total count of extracted relationships is logged for monitoring
        """
        # Input validation
        if not isinstance(entities, list):
            raise TypeError("entities must be a list")
        if not isinstance(chunks, list):
            raise TypeError("chunks must be a list")
        
        # Handle empty inputs
        if not entities or not chunks:
            return []

        # Validate entity attributes
        for entity in entities:
            if not hasattr(entity, 'source_chunks'):
                raise AttributeError("Entity missing required 'source_chunks' attribute")
        
        # Validate chunk attributes  
        for chunk in chunks:
            if not hasattr(chunk, 'chunk_id'):
                raise AttributeError("Chunk missing required 'chunk_id' attribute")

        relationships = []
        
        # Build entity index for quick lookup
        entity_by_chunk = {}
        for entity in entities:
            for chunk_id in entity.source_chunks:
                if chunk_id not in entity_by_chunk:
                    entity_by_chunk[chunk_id] = []
                entity_by_chunk[chunk_id].append(entity)
        
        # Extract relationships within chunks
        for chunk in chunks:
            chunk_entities = entity_by_chunk.get(chunk.chunk_id, [])
            if len(chunk_entities) >= 2:
                chunk_relationships = await self._extract_chunk_relationships(
                    chunk_entities, chunk
                )
                relationships.extend(chunk_relationships)
        
        # Extract cross-chunk relationships (same document)
        cross_chunk_relationships = await self._extract_cross_chunk_relationships(
            entities, chunks
        )
        relationships.extend(cross_chunk_relationships)
        
        self.logger.info(f"Extracted {len(relationships)} relationships")
        return relationships
    
    async def _extract_chunk_relationships(self, 
                                         entities: List[Entity], 
                                         chunk: LLMChunk,
                                         confidence_threshold: float = 0.6
                                         ) -> List[Relationship]:
        """Extract relationships between entities found within a single text chunk.

        This method identifies potential relationships by analyzing co-occurrence patterns
        of entities within the same chunk of text. It creates relationship objects based
        on contextual analysis and assigns confidence scores.

        Args:
            entities (List[Entity]): List of entities previously extracted from the chunk.
                Each entity should have 'id', 'name', and other relevant attributes.
            chunk (LLMChunk): The text chunk containing the entities. Must have 'content'
                and 'chunk_id' attributes for relationship extraction and tracking.
            confidence_threshold (float): Minimum confidence score for relationships to be included.
                Defaults to 0.6, which is the base confidence for co-occurrence relationships.

        Returns:
            List[Relationship]: A list of relationship objects connecting pairs of entities.
                Each relationship includes:
                - Unique identifier and source/target entity IDs
                - Inferred relationship type and descriptive text
                - Confidence score (base 0.6 for co-occurrence)
                - Source chunk reference and extraction metadata
                - Context snippet for relationship validation
        Notes:
            - Uses case-insensitive entity name matching within chunk content
            - Generates relationships for all entity pairs that co-occur in the text
            - Relationship types are inferred using contextual analysis
            - Only creates relationships when a valid type can be determined
            - Assigns MD5-based unique IDs to prevent duplicates
            - Includes extraction method metadata for traceability
        Example:
            If entities ["Apple Inc.", "iPhone"] are found in a chunk about product launches,
            this might generate a relationship with type "manufactures" connecting them.
        """
        # Type validation
        if not isinstance(entities, list):
            raise TypeError(f"Expected entities to be a list, got {type(entities).__name__}")
        
        relationships = []
        
        # Simple co-occurrence based relationships
        for i, entity1 in enumerate(entities):
            for entity2 in entities[i+1:]:
                # Check if entities co-occur in the chunk
                text_lower = chunk.content.lower()
                if (entity1.name.lower() in text_lower and 
                    entity2.name.lower() in text_lower):
                    
                    # Determine relationship type based on context
                    relationship_type = self._infer_relationship_type(
                        entity1, entity2, chunk.content
                    )
                    
                    if relationship_type:
                        rel_id = f"rel_{hashlib.md5(f'{entity1.id}_{entity2.id}_{relationship_type}'.encode()).hexdigest()[:8]}"
                        
                        relationship = Relationship(
                            id=rel_id,
                            source_entity_id=entity1.id,
                            target_entity_id=entity2.id,
                            relationship_type=relationship_type,
                            description=f"{entity1.name} {relationship_type} {entity2.name}",
                            confidence=confidence_threshold,
                            source_chunks=[chunk.chunk_id],
                            properties={
                                'extraction_method': 'co_occurrence',
                                'context_snippet': chunk.content[:200] + '...' if len(chunk.content) > 200 else chunk.content
                            }
                        )
                        relationships.append(relationship)

        return relationships

    def _infer_relationship_type(self, entity1: Entity, entity2: Entity, context: str) -> Optional[str]:
        """
        Infer the relationship type between two entities based on contextual information.

        This method analyzes the context string to determine the most appropriate relationship
        type between two entities by examining keywords and entity types. It supports various
        relationship categories including professional, organizational, and personal connections.

        Args:
            entity1 (Entity): The first entity in the relationship
            entity2 (Entity): The second entity in the relationship  
            context (str): The textual context containing information about the relationship

        Returns:
            Optional[str]: The inferred relationship type, 
                or None if no relationship can be determined.
                Possible return values include:
                - Person-Organization: 'leads', 'works_for', 'founded', 'associated_with'
                - Organization-Organization: 'acquired', 'partners_with', 'competes_with', 'related_to'
                - Person-Person: 'collaborates_with', 'manages', 'knows'
                - Location-based: 'located_in'
                - Default: 'related_to'
        Raises:
            TypeError: If entity1 or entity2 is None, or if context is not a string
            ValueError: If context is empty or whitespace-only
            AttributeError: If entity1 or entity2 does not have a 'type' attribute

        Examples:
            >>> _infer_relationship_type(person_entity, org_entity, "John is the CEO of ACME Corp")
            'leads'
            >>> _infer_relationship_type(org1_entity, org2_entity, "Microsoft acquired GitHub")
            'acquired'
            >>> _infer_relationship_type(person1_entity, person2_entity, "They work as colleagues")
            'collaborates_with'

        Note:
            The method performs case-insensitive keyword matching and prioritizes more specific
            relationships over generic ones. The relationship direction is implied by the order
            of entities (entity1 -> entity2).
        """
        # Input validation - check for None first
        for entity in (entity1, entity2):
            if entity is None:
                raise TypeError("Entity cannot be None")
            if not isinstance(entity, Entity):
                raise TypeError("Expected Entity instance")
            if not hasattr(entity, 'type'):
                raise AttributeError("Entity must have a 'type' attribute")

        if not isinstance(context, str):
            raise TypeError("Context must be a string")
        if not context.strip():
            raise ValueError("Context cannot be empty")

        context_lower = context.lower()
        
        # Helper function for flexible keyword matching (handles abbreviations and word boundaries)
        def contains_keyword(text, keywords):
            for keyword in keywords:
                # For abbreviations like "C.E.O.", use simple substring matching
                if '.' in keyword:
                    if keyword.lower() in text.lower():
                        return True
                # For regular words, use word boundary matching
                else:
                    pattern = r'\b' + re.escape(keyword.lower()) + r'\b'
                    if re.search(pattern, text.lower()):
                        return True
            return False

        # Check for location-based relationships first (higher priority for specific patterns)
        if contains_keyword(context_lower, ['located in', 'based in', 'headquarters']):
            return 'located_in'

        # Person-Organization relationships
        if entity1.type == 'person' and entity2.type == 'organization':
            # Leadership relationships (highest priority)
            if contains_keyword(context_lower, ['ceo', 'c.e.o.', 'leads', 'director']):
                return 'leads'
            # Employment relationships
            elif contains_keyword(context_lower, ['works for', 'employee', 'employed']):
                return 'works_for'
            # Founding relationships
            elif contains_keyword(context_lower, ['founded', 'established', 'created']):
                return 'founded'
            # Partnership relationships
            elif contains_keyword(context_lower, ['partnership']):
                return 'associated_with'
            else:
                return 'associated_with'
        
        # Organization-Person relationships (symmetric handling)
        elif entity1.type == 'organization' and entity2.type == 'person':
            # For partnership, maintain symmetry
            if contains_keyword(context_lower, ['partnership']):
                return 'associated_with'  # Same as person-org for partnerships
            else:
                return 'related_to'  # Default for org-person
        
        # Organization-Organization relationships
        elif entity1.type == 'organization' and entity2.type == 'organization':
            if contains_keyword(context_lower, ['acquired', 'bought', 'purchased']):
                return 'acquired'
            elif contains_keyword(context_lower, ['partners', 'partnership', 'collaboration']):
                return 'partners_with'
            elif contains_keyword(context_lower, ['competes', 'competitor', 'rival', 'rivals']):
                return 'competes_with'
            else:
                return 'related_to'
        
        # Person-Person relationships
        elif entity1.type == 'person' and entity2.type == 'person':
            # Management relationships (highest priority)
            if contains_keyword(context_lower, ['manages', 'supervises', 'reports to']):
                return 'manages'
            # Collaboration relationships
            elif contains_keyword(context_lower, ['collaborates', 'works together', 'colleagues']):
                return 'collaborates_with'
            else:
                return 'knows'
        
        # Location relationships (only for unhandled cases with location entities)
        elif 'location' in [entity1.type, entity2.type]:
            # Don't override specific location patterns already handled above
            # This is for cases where we have location entities but no specific location keywords
            return 'related_to'
        
        # Default relationship for all other cases
        return 'related_to'
    
    async def _extract_cross_chunk_relationships(self, 
                                               entities: List[Entity], 
                                               chunks: List[LLMChunk]) -> List[Relationship]:
        """Extract relationships between entities that span across multiple document chunks.

        This method identifies and creates relationships between entities based on their
        co-occurrence in sequential document chunks, establishing narrative connections
        that may not be explicitly stated but are implied by document structure.

        Args:
            entities (List[Entity]): List of extracted entities from the document,
                each containing source chunk information and entity metadata.
            chunks (List[LLMChunk]): List of document chunks in sequential order,
                used to determine narrative flow and proximity relationships.

        Returns:
            List[Relationship]: List of relationship objects representing cross-chunk
                connections. Each relationship includes:
                - Unique identifier and entity references
                - Relationship type ('narrative_sequence')
                - Confidence score (0.4 for narrative relationships)
                - Source chunks where both entities appear
                - Extraction metadata and sequence information

        Note:
            - Relationships are only created between different entities (entity1.id != entity2.id)
            - Confidence is set to 0.4 as these are inferred rather than explicit relationships
            - All combinations of entities within a sequence are connected (n*(n-1)/2 relationships)
            - Relationship IDs are generated using MD5 hash of entity ID pairs for consistency
        """
        relationships = []
        
        # Group entities by type for more efficient processing
        entities_by_type = {}
        for entity in entities:
            if entity.type not in entities_by_type:
                entities_by_type[entity.type] = []
            entities_by_type[entity.type].append(entity)
        
        # Find entities that appear in sequential chunks (narrative relationships)
        chunk_sequences = self._find_chunk_sequences(chunks)
        for seq in chunk_sequences:
            seq_entities = []
            for chunk_id in seq:
                chunk_entities = [e for e in entities if chunk_id in e.source_chunks]
                seq_entities.extend(chunk_entities)
            
            # Create narrative relationships
            if len(seq_entities) >= 2:
                for i, entity1 in enumerate(seq_entities):
                    for entity2 in seq_entities[i+1:]:
                        if entity1.id != entity2.id:
                            rel_id = f"rel_seq_{hashlib.md5(f'{entity1.id}_{entity2.id}'.encode()).hexdigest()[:8]}"
                            
                            relationship = Relationship(
                                id=rel_id,
                                source_entity_id=entity1.id,
                                target_entity_id=entity2.id,
                                relationship_type='narrative_sequence',
                                description=f"{entity1.name} appears in narrative sequence with {entity2.name}",
                                confidence=0.4,
                                source_chunks=list(set(entity1.source_chunks + entity2.source_chunks)),
                                properties={
                                    'extraction_method': 'narrative_sequence',
                                    'sequence_length': len(seq)
                                }
                            )
                            relationships.append(relationship)
        
        return relationships
    
    def _find_chunk_sequences(self, chunks: List[LLMChunk]) -> List[List[str]]:
        """Find sequences of related chunks based on their source page.
    
        Groups chunks that belong to the same page and returns sequences containing
        multiple chunks. Single-chunk pages are filtered out as they don't form
        meaningful sequences for processing.

        Args:
            chunks (List[LLMChunk]): List of LLM chunks to analyze for sequences.
                Each chunk must have a source_page and chunk_id attribute.

        Returns:
            List[List[str]]: List of sequences, where each sequence is a list of
                chunk IDs that belong to the same page. Only includes sequences
                with 2 or more chunks.

        Raises:
            TypeError: If chunks is not a list or if any chunk is not an LLMChunk instance.

        Example:
            >>> chunks = [chunk1(page=1), chunk2(page=1), chunk3(page=2)]
            >>> sequences = self._find_chunk_sequences(chunks)
            >>> # Returns: [['chunk1_id', 'chunk2_id']] (page 2 filtered out)
        """
        sequences = []
        
        # Group chunks by page
        chunks_by_page = {}
        for chunk in chunks:
            page = chunk.source_page
            if page not in chunks_by_page:
                chunks_by_page[page] = []
            chunks_by_page[page].append(chunk.chunk_id)
        
        # Each page is a sequence
        for page, chunk_ids in chunks_by_page.items():
            if len(chunk_ids) > 1:
                sequences.append(chunk_ids)
        
        return sequences
    
    async def _create_networkx_graph(self, knowledge_graph: KnowledgeGraph) -> nx.DiGraph:
        """Create a NetworkX directed graph representation from a knowledge graph.

        Converts a KnowledgeGraph object into a NetworkX DiGraph where:
        - Entities become nodes with their properties as node attributes
        - Relationships become directed edges with their properties as edge attributes

        Args:
            knowledge_graph (KnowledgeGraph): The knowledge graph containing entities 
                and relationships to convert into NetworkX format.

        Returns:
            nx.DiGraph: A directed graph where:
                - Nodes represent entities with attributes: name, type, confidence, 
                  source_chunks, and any additional properties
                - Edges represent relationships with attributes: relationship_type, 
                  confidence, source_chunks, and any additional properties

        Note:
            The resulting NetworkX graph maintains all metadata from the original
            knowledge graph structure.
        """
        graph = nx.DiGraph()
        
        # Add entities as nodes
        for entity in knowledge_graph.entities:
            graph.add_node(
                entity.id,
                name=entity.name,
                type=entity.type,
                confidence=entity.confidence,
                source_chunks=entity.source_chunks,
                **entity.properties
            )
        
        # Add relationships as edges
        for relationship in knowledge_graph.relationships:
            graph.add_edge(
                relationship.source_entity_id,
                relationship.target_entity_id,
                relationship_type=relationship.relationship_type,
                confidence=relationship.confidence,
                source_chunks=relationship.source_chunks,
                **relationship.properties
            )
        
        return graph
    
    async def _merge_into_global_graph(self, knowledge_graph: KnowledgeGraph) -> None:
        """
        Merge a document-specific knowledge graph into the global knowledge graph.

        This method performs a two-phase merge operation:
        1. Merges entities from the document graph into the global entity collection,
           handling conflicts by combining source chunks and taking maximum confidence scores
        2. Composes the document's NetworkX graph structure with the global graph

        Args:
            knowledge_graph (KnowledgeGraph): The document-specific knowledge graph
                containing entities and relationships to be merged into the global graph.

        Side Effects:
            - Updates self.global_entities with new entities or merges existing ones
            - Modifies self.global_graph by composing it with the document graph
            - Deduplicates source chunks for entities that already exist globally
            - Updates entity confidence scores to reflect the maximum confidence seen

        Note:
            This is an asynchronous method that modifies the global graph state in-place.
            The merge operation preserves all nodes and edges from both graphs, with
            NetworkX handling any overlapping nodes automatically.
        """
        # Update global entities
        for entity in knowledge_graph.entities:
            if entity.id not in self.global_entities:
                self.global_entities[entity.id] = entity
            else:
                # Merge entity information
                existing = self.global_entities[entity.id]
                existing.source_chunks.extend(entity.source_chunks)
                existing.source_chunks = list(set(existing.source_chunks))
                existing.confidence = max(existing.confidence, entity.confidence)
        
        # Merge into global NetworkX graph
        doc_graph = self.document_graphs[knowledge_graph.document_id]
        self.global_graph = nx.compose(self.global_graph, doc_graph)
    
    async def _discover_cross_document_relationships(self, knowledge_graph: KnowledgeGraph):
        """Discover and establish relationships between entities across different documents.

        This method identifies entities that appear in multiple documents and creates
        cross-document relationships to connect related information. It analyzes entity
        similarity and determines whether entities represent the same concept or are
        merely similar across document boundaries.

        Args:
            knowledge_graph (KnowledgeGraph): The knowledge graph containing entities
                to analyze for cross-document relationships.

        Returns:
            None: The method updates self.cross_document_relationships in-place.

        Side Effects:
            - Extends self.cross_document_relationships with newly discovered relationships
            - Logs the number of relationships discovered

        Process:
            1. Iterates through all entities in the provided knowledge graph
            2. For each entity, finds similar entities from other documents using similarity matching
            3. Verifies that entities belong to different documents by checking source chunks
            4. Creates CrossDocumentRelationship objects with appropriate confidence scores:
               - 0.8 confidence for exact name matches (same_entity type)
               - 0.6 confidence for similar but not identical entities (similar_entity type)
            5. Includes evidence chunks from both entities to support the relationship

        Note:
            - Requires self.global_entities to be populated before execution
            - Returns early if no global entities are available
            - Assumes chunk IDs contain document information for proper cross-document detection
        """
        if not self.global_entities:
            return
        
        new_relationships = []
        
        for entity in knowledge_graph.entities:
            # Find similar entities in other documents
            similar_entities = await self._find_similar_entities(entity)
            
            for similar_entity in similar_entities:
                if similar_entity.id != entity.id:
                    # Check if they're from different documents
                    entity_docs = set()
                    similar_docs = set()
                    
                    for chunk_id in entity.source_chunks:
                        # Extract document ID from chunk (assuming chunk format includes doc info)
                        entity_docs.add(knowledge_graph.document_id)
                    
                    for chunk_id in similar_entity.source_chunks:
                        # Find document for this chunk
                        for kg in self.knowledge_graphs.values():
                            if any(c.chunk_id == chunk_id for c in kg.chunks):
                                similar_docs.add(kg.document_id)
                                break
                    
                    if entity_docs.intersection(similar_docs) == set():
                        # Different documents
                        cross_rel = CrossDocumentRelationship(
                            id=f"cross_{uuid.uuid4().hex[:8]}",
                            source_document_id=knowledge_graph.document_id,
                            target_document_id=list(similar_docs)[0] if similar_docs else 'unknown',
                            source_entity_id=entity.id,
                            target_entity_id=similar_entity.id,
                            relationship_type='same_entity' if entity.name.lower() == similar_entity.name.lower() else 'similar_entity',
                            confidence=0.8 if entity.name.lower() == similar_entity.name.lower() else 0.6,
                            evidence_chunks=entity.source_chunks + similar_entity.source_chunks
                        )
                        new_relationships.append(cross_rel)
        
        self.cross_document_relationships.extend(new_relationships)
        self.logger.info(f"Discovered {len(new_relationships)} cross-document relationships")
    
    async def _find_similar_entities(self, entity: Entity) -> List[Entity]:
        """Find entities similar to the given entity across all documents in the graph.

        This method searches through all global entities to identify those that are similar
        to the input entity based on name similarity and type matching. Entities are considered
        similar if they have the same type and their names exceed the configured similarity
        threshold.

        Args:
            entity (Entity): The reference entity to find similar matches for. Must have
                            'id', 'name', and 'type' attributes.

        Returns:
            List[Entity]: A list of entities that are similar to the input entity.
                         The list excludes the input entity itself and only includes
                         entities of the same type whose names have similarity scores
                         above the threshold.

        Note:
            - Uses the instance's similarity_threshold for determining matches
            - Relies on _calculate_text_similarity() for name comparison
            - Only considers entities with exact type matches
            - The input entity is automatically excluded from results
        """
        similar_entities = []
        
        for other_entity in self.global_entities.values():
            if other_entity.id == entity.id:
                continue
            
            # Name similarity
            name_similarity = self._calculate_text_similarity(entity.name, other_entity.name)
            
            # Type must match
            if entity.type == other_entity.type and name_similarity > self.similarity_threshold:
                similar_entities.append(other_entity)
        
        return similar_entities
    
    def _calculate_text_similarity(self, text1: str, text2: str) -> float:
        """Calculate the Jaccard similarity coefficient between two text strings.

        This method implements the Jaccard similarity algorithm, which measures
        similarity between two sets of words by calculating the ratio of their
        intersection to their union. The similarity score ranges from 0.0 (no
        common words) to 1.0 (identical word sets).
        The method performs case-insensitive comparison and treats each unique
        word as a single element in the set, regardless of word frequency.

        Args:
            text1 (str): The first text string to compare.
            text2 (str): The second text string to compare.
        Returns:
            float: The Jaccard similarity coefficient between 0.0 and 1.0, where:
                - 0.0 indicates no common words between the texts
                - 1.0 indicates identical word sets (after normalization)
                - Values closer to 1.0 indicate higher similarity
        Note:
            This is a simple implementation that:
            - Converts text to lowercase for case-insensitive comparison
            - Splits text on whitespace only (no advanced tokenization)
            - Treats punctuation as part of words
            - Does not account for word frequency or semantic meaning

        Example:
            >>> similarity = self._calculate_text_similarity("hello world", "world hello")
            >>> # Returns 1.0 (identical word sets)
            >>> similarity = self._calculate_text_similarity("hello world", "hello universe")
            >>> # Returns 0.33 (1 common word out of 3 total unique words)
        """
        # Simple Jaccard similarity
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        if not union:
            return 0.0
        
        return len(intersection) / len(union)
    
    async def _store_knowledge_graph_ipld(self, knowledge_graph: KnowledgeGraph) -> str:
        """Store a knowledge graph in IPLD (InterPlanetary Linked Data) format.

        This method serializes a KnowledgeGraph object into a JSON-compatible format,
        handles numpy array conversion for embeddings, and stores the data in IPLD
        using the configured storage backend.

        Args:
            knowledge_graph (KnowledgeGraph): The knowledge graph object containing
                entities, relationships, chunks, and metadata to be stored.

        Returns:
            str: The Content Identifier (CID) of the stored knowledge graph in IPLD.
                 Returns an empty string if storage fails.

        Note:
            - Errors during storage are logged and result in an empty string return

        Raises:
            Exception: Catches and logs any storage-related exceptions, returning
                      empty string instead of propagating the error.
        """
        # Convert to serializable format
        kg_data = {
            'graph_id': knowledge_graph.graph_id,
            'document_id': knowledge_graph.document_id,
            'entities': [asdict(entity) for entity in knowledge_graph.entities],
            'relationships': [asdict(rel) for rel in knowledge_graph.relationships],
            'chunks': [chunk.model_dump() for chunk in knowledge_graph.chunks],
            'metadata': knowledge_graph.metadata,
            'creation_timestamp': knowledge_graph.creation_timestamp
        }

        # Remove numpy arrays from entities for JSON serialization
        for entity_data in kg_data['entities']:
            if 'embedding' in entity_data and entity_data['embedding'] is not None:
                entity_data['embedding'] = entity_data['embedding'].tolist()
        
        # Remove numpy arrays from chunks
        for chunk_data in kg_data['chunks']:
            if 'embedding' in chunk_data and chunk_data['embedding'] is not None:
                chunk_data['embedding'] = chunk_data['embedding'].tolist()

        assert isinstance(self.storage, IPLDStorage), \
            f"Storage backend must be IPLDStorage, got {type(self.storage).__name__}"

        try:
            # Store in IPLD
            cid = self.storage.store_json(kg_data)
            self.logger.info(f"Stored knowledge graph in IPLD: {cid}")
            return cid
        except Exception as e:
            if self.logger.level == logging.DEBUG:
                self.logger.exception(f"Failed to store knowledge graph in IPLD: {e}")
            else:
                self.logger.error(f"Failed to store knowledge graph in IPLD: {e}")
            return ""

    async def query_graph(self, 
                         query: str, 
                         graph_id: Optional[str] = None,
                         max_results: int = 10) -> Dict[str, Any]:
        """Query the knowledge graph using natural language to retrieve relevant entities and relationships.

        This method performs intelligent search across the knowledge graph(s) to find entities
        that match the given query. It uses both keyword-based matching and entity extraction
        to identify relevant entities and their relationships. The search algorithm scores
        matches based on name similarity, type matching, and description relevance.

        Args:
            query (str): Natural language query string to search for in the knowledge graph.
                The search is case-insensitive and matches against entity names, types, and descriptions.
                Can include entity names like "John Smith" or concepts like "artificial intelligence companies".
            graph_id (Optional[str], optional): Specific knowledge graph identifier to query.
                If None, searches across the global merged graph containing all entities and relationships.
                Defaults to None.
            max_results (int, optional): Maximum number of top-scoring entities to return.
                Results are ranked by relevance score and limited to this number. Defaults to 10.

        Returns:
            Dict[str, Any]: A dictionary containing query results with the following structure:
            - 'query' (str): The original query string
            - 'entities' (List[Dict]): List of matching entities serialized as dictionaries,
                ordered by relevance score (highest first)
            - 'relationships' (List[Dict]): List of relationships connected to the matching entities,
                serialized as dictionaries
            - 'total_matches' (int): Total number of entities that matched the query before limiting
            - 'extracted_entities' (List[str]): Entity names extracted from the query using NLP
            - 'timestamp' (str): ISO format timestamp of when the query was executed

        Raises:
            TypeError: If query is not a string or max_results is not an integer.
            ValueError: If query is empty/whitespace-only or max_results is less than or equal to 0.
            KeyError: If graph_id is provided but does not exist in the knowledge graphs.

        Example:
            >>> results = await integrator.query_graph("companies founded by John Smith", max_results=5)
            >>> print(f"Found {results['total_matches']} matches")
            >>> print(f"Extracted entities: {results['extracted_entities']}")
            >>> for entity in results['entities']:
            ...     print(f"- {entity['name']} ({entity['type']}) - Score: {entity.get('_score', 0)}")

        Note:
            - Uses NLP-based entity extraction to identify potential entity names in the query
            - Scoring system: exact name matches (score +3), entity name in query (+2), 
              type matches (+1), description matches (+1)
            - Related relationships are automatically included for all matching entities
            - Empty queries return empty results rather than all entities
        """
        # Input validation
        type_dict = {
            query: str,
            max_results: int
        }
        for key, type_ in type_dict.items():
            if not isinstance(key, type_):
                raise TypeError(f"{key} parameter must be of type {type_.__name__}, got {type(key).__name__}")

        if not query.strip():
            raise ValueError("query must be a non-empty string.")

        if max_results <= 0:
            raise ValueError("max_results must be greater than 0")

        if graph_id and graph_id not in self.knowledge_graphs:
            raise KeyError(f"Knowledge graph '{graph_id}' not found")

        if graph_id and graph_id in self.knowledge_graphs:
            kg = self.knowledge_graphs[graph_id]
            entities = kg.entities
            relationships = kg.relationships
        else:
            # Query global graph
            entities = list(self.global_entities.values())
            relationships = []
            for kg in self.knowledge_graphs.values():
                relationships.extend(kg.relationships)
        
        # Handle empty query - return no results
        if not query.strip():
            return {
                'query': query,
                'entities': [],
                'relationships': [],
                'total_matches': 0,
                'timestamp': datetime.now().isoformat()
            }
        
        # Simple keyword-based search (can be enhanced with semantic search)
        query_lower = query.lower()
        matching_entities = []
        
        for entity in entities:
            score = 0
            
            # Name match
            if query_lower in entity.name.lower():
                score += 2
            
            # Type match
            if query_lower in entity.type.lower():
                score += 1
            
            # Description match
            if query_lower in entity.description.lower():
                score += 1
            
            if score > 0:
                matching_entities.append((entity, score))
        
        # Sort by score and limit results
        matching_entities.sort(key=lambda x: x[1], reverse=True)
        top_entities = [entity for entity, score in matching_entities[:max_results]]
        
        # Find related relationships
        entity_ids = {entity.id for entity in top_entities}
        related_relationships = [
            rel for rel in relationships
            if rel.source_entity_id in entity_ids or rel.target_entity_id in entity_ids
        ]
        
        return {
            'query': query,
            'entities': [asdict(entity) for entity in top_entities],
            'relationships': [asdict(rel) for rel in related_relationships],
            'total_matches': len(matching_entities),
            'timestamp': datetime.now().isoformat()
        }
    
    async def get_entity_neighborhood(self, 
                                    entity_id: str, 
                                    depth: int = 2) -> Dict[str, Any]:
        """Get the neighborhood of an entity in the graph within a specified depth.

        This method extracts a subgraph centered around a given entity, including all nodes
        and edges within the specified depth from the center entity. The method performs
        breadth-first traversal to collect neighboring nodes at each depth level, considering
        both incoming and outgoing relationships.

        Args:
            entity_id (str): The unique identifier of the center entity to analyze.
            Must be a valid entity ID that exists in the global entity registry.
            depth (int, optional): The maximum depth to traverse from the center entity.
            Defaults to 2. Must be a non-negative integer where:
            - depth=0: Only the center entity
            - depth=1: Center entity and direct neighbors
            - depth=2: Center entity, direct neighbors, and their neighbors
            - etc.

        Returns:
            Dict[str, Any]: A dictionary containing the neighborhood analysis results:
            Success case:
            - 'center_entity_id' (str): The ID of the center entity
            - 'depth' (int): The depth used for traversal
            - 'nodes' (List[Dict]): List of node data dictionaries, each containing
                all node attributes plus an 'id' field
            - 'edges' (List[Dict]): List of edge data dictionaries, each containing
                all edge attributes plus 'source' and 'target' fields
            - 'node_count' (int): Total number of nodes in the subgraph
            - 'edge_count' (int): Total number of edges in the subgraph
            
            Error cases:
            - {'error': 'Entity not found'}: If entity_id is not in global_entities
            - {'error': 'Entity not in graph'}: If entity_id is not in global_graph

        Raises:
            TypeError: If entity_id is not a string or depth is not an integer.
            ValueError: If entity_id is empty or depth is negative.

        Examples:
            >>> neighborhood = await integrator.get_entity_neighborhood("entity_123", depth=1)
            >>> print(f"Found {neighborhood['node_count']} nodes and {neighborhood['edge_count']} edges")
            
            >>> # Get deeper neighborhood
            >>> deep_neighborhood = await integrator.get_entity_neighborhood("entity_123", depth=3)
            >>> print(f"3-depth neighborhood has {deep_neighborhood['node_count']} nodes")

        Note:
            - Uses the global graph (self.global_graph) for comprehensive analysis
            - Considers both incoming (predecessors) and outgoing (successors) edges
            - The returned subgraph includes all nodes within the specified depth, not just
              those at exactly that depth
            - All data is converted to serializable format for JSON compatibility
            - Performance scales with graph size and depth - use smaller depths for large graphs
        """
        if not isinstance(entity_id, str):
            raise TypeError(f"entity_id must be a string, got {type(entity_id).__name__} instead.")
        if not entity_id:
            raise ValueError("entity_id must be a non-empty string.")
        
        if not isinstance(depth, int):
            raise TypeError(f"depth must be an integer, got {type(depth).__name__} instead.")
        if depth < 0:
            raise ValueError("depth must be a non-negative integer")

        if entity_id not in self.global_entities:
            return {'error': 'Entity not found'}
        
        # Use global graph for neighborhood analysis
        if entity_id not in self.global_graph:
            return {'error': 'Entity not in graph'}
        
        # Get subgraph within specified depth
        subgraph_nodes = set([entity_id])
        
        for d in range(depth):
            new_nodes = set()
            for node in subgraph_nodes:
                # Add neighbors
                new_nodes.update(self.global_graph.neighbors(node))
                new_nodes.update(self.global_graph.predecessors(node))
            subgraph_nodes.update(new_nodes)
        
        # Extract subgraph
        subgraph = self.global_graph.subgraph(subgraph_nodes)
        
        # Convert to serializable format
        nodes_data = []
        for node in subgraph.nodes():
            node_data = dict(subgraph.nodes[node])
            node_data['id'] = node
            nodes_data.append(node_data)
        
        edges_data = []
        for source, target in subgraph.edges():
            edge_data = dict(subgraph.edges[source, target])
            edge_data['source'] = source
            edge_data['target'] = target
            edges_data.append(edge_data)
        
        return {
            'center_entity_id': entity_id,
            'depth': depth,
            'nodes': nodes_data,
            'edges': edges_data,
            'node_count': len(nodes_data),
            'edge_count': len(edges_data)
        }


def make_graphrag_integrator(mock_dict: Optional[dict[str, Any]] = None) -> GraphRAGIntegrator:
    """Factory function to create a GraphRAGIntegrator instance with default configuration."""
    instance = GraphRAGIntegrator(
        storage=IPLDStorage(),
        entity_extraction_confidence=0.6,
        similarity_threshold=0.8,
    )
    if isinstance(mock_dict, dict):
        for key, value in mock_dict.items():
            setattr(instance, key, value)
    return instance

