"""
Knowledge Graph Extraction Module

This module provides components for extracting structured knowledge graphs from
unstructured text. It handles entity and relationship extraction, confidence
scoring, and conversion to a structured graph representation. It also includes
support for Wikipedia integration, SPARQL validation against Wikidata, and
detailed tracing of the extraction and validation processes.
Supports accelerate integration for distributed LLM inference.

Main Components:
- Entity: Represents an entity in the knowledge graph
- Relationship: Represents a relationship between entities
- KnowledgeGraph: Container for entities and relationships
- KnowledgeGraphExtractor: Extracts entities and relationships from text

Key Features:
- Temperature-controlled extraction with tunable parameters
- Wikipedia integration for extracting knowledge graphs from Wikipedia pages
- SPARQL validation against Wikidata's structured data
- Detailed tracing of extraction and validation reasoning using WikipediaKnowledgeGraphTracer
- Comparison of extraction results with different temperature settings
- Visualization and explanation of extraction and validation results
- Accelerate integration for distributed inference
"""

import re
import uuid
import json
import requests
from dataclasses import dataclass, field
from typing import Dict, List, Any, Set, Optional, Tuple, Union
from collections import defaultdict

# Import the Wikipedia knowledge graph tracer for enhanced tracing capabilities
from ipfs_datasets_py.llm.llm_reasoning_tracer import WikipediaKnowledgeGraphTracer

# Try to import accelerate integration for distributed inference
try:
    from ipfs_datasets_py.accelerate_integration import (
        AccelerateManager,
        is_accelerate_available,
        get_accelerate_status
    )
    HAVE_ACCELERATE = True
except ImportError:
    HAVE_ACCELERATE = False
    AccelerateManager = None
    is_accelerate_available = lambda: False
    get_accelerate_status = lambda: {"available": False}


@dataclass
class Entity:
    """Represents an entity in a knowledge graph.

    Entities are nodes in the knowledge graph with a type, name,
    and optional properties.

    Attributes:
        entity_id (str, optional): Unique identifier for the entity
        entity_type (str): Type of the entity (e.g., "person", "organization")
        name (str): Name or label of the entity
        properties (Dict, optional): Additional properties of the entity
        confidence (float): Confidence score (0.0 to 1.0)
        source_text (str, optional): Source text from which the entity was extracted

    Methods:
        to_dict() -> Dict[str, Any]:
            Convert the entity to a dictionary representation.
        from_dict(data: Dict[str, Any]) -> 'Entity':
            Create an entity from a dictionary representation.
    """
    entity_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    entity_type: str = "entity"
    name: str = ""
    properties: Optional[Dict[str, Any]] = field(default_factory=dict)
    confidence: float = 1.0
    source_text: str = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert the entity to a dictionary representation.

        Returns:
            Dict: Dictionary representation of the entity
        """
        entity_dict = {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "name": self.name,
            "properties": self.properties,
            "confidence": self.confidence
        }

        if self.source_text:
            entity_dict["source_text"] = self.source_text

        return entity_dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Entity':
        """Create an entity from a dictionary representation.

        Args:
            data (Dict): Dictionary representation of the entity

        Returns:
            Entity: The created entity
        """
        return cls(
            entity_id=data.get("entity_id"),
            entity_type=data.get("entity_type", "entity"),
            name=data.get("name", ""),
            properties=data.get("properties", {}),
            confidence=data.get("confidence", 1.0),
            source_text=data.get("source_text")
        )


@dataclass
class Relationship:
    """Represents a relationship between entities in a knowledge graph.

    Relationships are directed edges in the knowledge graph with a type,
    source and target entities, and optional properties.

    Attributes:
        relationship_id (str): Unique identifier for the relationship
        relationship_type (str): Type of the relationship
        source_entity (Entity): Source entity (head)
        target_entity (Entity): Target entity (tail)
        properties (Dict, optional): Additional properties of the relationship
        confidence (float): Confidence score (0.0 to 1.0)
        source_text (str, optional): Source text from which the relationship was extracted
        bidirectional (bool): Whether the relationship is bidirectional

    Methods:
        to_dict(include_entities: bool = True) -> Dict[str, Any]:
            Convert the relationship to a dictionary representation.
        from_dict(data: Dict[str, Any], entity_map: Dict[str, Entity] = None) -> 'Relationship':
            Create a relationship from a dictionary representation.
    """
    relationship_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    relationship_type: str = "related_to"
    source_entity: Optional[Entity] = None
    target_entity: Optional[Entity] = None
    properties: Optional[Dict[str, Any]] = field(default_factory=dict)
    confidence: float = 1.0
    source_text: Optional[str] = None
    bidirectional: bool = False

    def __post_init__(self):
        """Handle flexible constructor patterns"""
        # If relationship_id is actually an Entity (wrong calling pattern), fix it
        if isinstance(self.relationship_id, Entity):
            # This means the call was Relationship(source, target, type)
            source_entity = self.relationship_id
            target_entity = self.relationship_type
            relationship_type = self.source_entity
            
            # Fix the fields
            self.relationship_id = str(uuid.uuid4())
            self.source_entity = source_entity
            self.target_entity = target_entity
            self.relationship_type = relationship_type

    @classmethod
    def create(cls, source: Entity, target: Entity, relationship_type: str, **kwargs) -> 'Relationship':
        """Create relationship with intuitive parameter order"""
        return cls(
            source_entity=source,
            target_entity=target,
            relationship_type=relationship_type,
            **kwargs
        )

    @property
    def source_id(self) -> Optional[str]:
        """Get the ID of the source entity."""
        return self.source_entity.entity_id if self.source_entity else None

    @property
    def target_id(self) -> Optional[str]:
        """Get the ID of the target entity."""
        return self.target_entity.entity_id if self.target_entity else None

    def to_dict(self, include_entities: bool = True) -> Dict[str, Any]:
        """Convert the relationship to a dictionary representation.

        Args:
            include_entities (bool): Whether to include full entity details

        Returns:
            Dict: Dictionary representation of the relationship
        """
        rel_dict = {
            "relationship_id": self.relationship_id,
            "relationship_type": self.relationship_type,
            "properties": self.properties,
            "confidence": self.confidence,
            "bidirectional": self.bidirectional
        }

        if self.source_text:
            rel_dict["source_text"] = self.source_text

        if include_entities:
            rel_dict["source"] = self.source_entity.to_dict() if self.source_entity else None
            rel_dict["target"] = self.target_entity.to_dict() if self.target_entity else None
        else:
            rel_dict["source"] = self.source_id
            rel_dict["target"] = self.target_id

        return rel_dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any], entity_map: Dict[str, Entity] = None) -> 'Relationship':
        """Create a relationship from a dictionary representation.

        Args:
            data (Dict): Dictionary representation of the relationship
            entity_map (Dict, optional): Map from entity IDs to Entity objects

        Returns:
            Relationship: The created relationship
        """
        entity_map = entity_map or {}

        # Handle source and target entities
        source = None
        target = None

        if isinstance(data.get("source"), dict):
            source = Entity.from_dict(data["source"])
        elif data.get("source") in entity_map:
            source = entity_map[data["source"]]

        if isinstance(data.get("target"), dict):
            target = Entity.from_dict(data["target"])
        elif data.get("target") in entity_map:
            target = entity_map[data["target"]]

        return cls(
            relationship_id=data.get("relationship_id"),
            relationship_type=data.get("relationship_type", "related_to"),
            source_entity=source,
            target_entity=target,
            properties=data.get("properties", {}),
            confidence=data.get("confidence", 1.0),
            source_text=data.get("source_text"),
            bidirectional=data.get("bidirectional", False)
        )


class KnowledgeGraph:
    """
    A knowledge graph containing entities and relationships.

    Provides methods for adding, querying, and manipulating entities
    and relationships in the knowledge graph.
    """

    def __init__(self, name: str = None):
        """Initialize a new knowledge graph.

        Args:
            name (str, optional): Name of the knowledge graph

        Attributes initialized:
            name (str): Name of the knowledge graph
            entities (Dict[str, Entity]): Dictionary of entities by ID
            relationships (Dict[str, Relationship]): Dictionary of relationships by ID
            entity_types (Dict[str, Set[str]]): Index of entities by type
            entity_names (Dict[str, Set[str]]): Index of entities by name
            relationship_types (Dict[str, Set[str]]): Index of relationships by type
            entity_relationships (Dict[str, Set[str]]): Index of relationships by entity ID
        """
        self.name = name or f"kg_{str(uuid.uuid4())[:8]}"
        self.entities: Dict[str, Entity] = {}
        self.relationships: Dict[str, Relationship] = {}

        # Indexes for efficient querying
        self.entity_types: Dict[str, Set[str]] = defaultdict(set)
        self.entity_names: Dict[str, Set[str]] = defaultdict(set)
        self.relationship_types: Dict[str, Set[str]] = defaultdict(set)
        self.entity_relationships: Dict[str, Set[str]] = defaultdict(set)

    def add_entity(
        self,
        entity_type_or_entity: Union[str, Entity],
        name: Optional[str] = None,
        properties: Optional[Dict[str, Any]] = None,
        entity_id: str = None,
        confidence: float = 1.0,
        source_text: str = None
    ) -> Entity:
        """Add an entity to the knowledge graph.

        Args:
            entity_type_or_entity: Either entity type string OR Entity object
            name (str): Name of the entity (required if first arg is string)
            properties (Dict, optional): Additional properties
            entity_id (str, optional): Unique identifier (generated if None)
            confidence (float): Confidence score
            source_text (str, optional): Source text

        Returns:
            Entity: The added entity
        """
        # Handle both calling patterns
        if isinstance(entity_type_or_entity, Entity):
            # Called with Entity object: add_entity(entity)
            entity = entity_type_or_entity
        else:
            # Called with parameters: add_entity(entity_type, name, ...)
            if name is None:
                raise ValueError("name parameter is required when first argument is entity_type string")
            
            entity = Entity(
                entity_id=entity_id,
                entity_type=entity_type_or_entity,
                name=name,
                properties=properties,
                confidence=confidence,
                source_text=source_text
            )

        # Add to graph
        self.entities[entity.entity_id] = entity

        # Update indexes
        self.entity_types[entity.entity_type].add(entity.entity_id)
        self.entity_names[entity.name].add(entity.entity_id)

        return entity

    def add_relationship(
        self,
        relationship_type_or_relationship: Union[str, 'Relationship'],
        source: Optional[Entity] = None,
        target: Optional[Entity] = None,
        properties: Optional[Dict[str, Any]] = None,
        relationship_id: str = None,
        confidence: float = 1.0,
        source_text: str = None,
        bidirectional: bool = False
    ) -> 'Relationship':
        """Add a relationship to the knowledge graph.

        Args:
            relationship_type_or_relationship: Either relationship type string OR Relationship object
            source (Entity): Source entity (required if first arg is string)
            target (Entity): Target entity (required if first arg is string)
            properties (Dict, optional): Additional properties
            relationship_id (str, optional): Unique identifier (generated if None)
            confidence (float): Confidence score
            source_text (str, optional): Source text
            bidirectional (bool): Whether the relationship is bidirectional

        Returns:
            Relationship: The added relationship
        """
        # Handle both calling patterns
        if isinstance(relationship_type_or_relationship, Relationship):
            # Called with Relationship object: add_relationship(relationship)
            relationship = relationship_type_or_relationship
        else:
            # Called with parameters: add_relationship(relationship_type, source, target, ...)
            if source is None or target is None:
                raise ValueError("source and target parameters are required when first argument is relationship_type string")
            
            relationship = Relationship(
                relationship_id=relationship_id,
                relationship_type=relationship_type_or_relationship,
                source_entity=source,
                target_entity=target,
                properties=properties,
                confidence=confidence,
                source_text=source_text,
                bidirectional=bidirectional
            )

        # Add to graph
        self.relationships[relationship.relationship_id] = relationship

        # Update indexes - handle both Entity objects and string IDs
        self.relationship_types[relationship.relationship_type].add(relationship.relationship_id)
        
        # Handle source entity
        if hasattr(relationship.source_entity, 'entity_id'):
            source_id = relationship.source_entity.entity_id
        elif isinstance(relationship.source_entity, str):
            source_id = relationship.source_entity
        else:
            source_id = str(relationship.source_entity)
        
        # Handle target entity
        if hasattr(relationship.target_entity, 'entity_id'):
            target_id = relationship.target_entity.entity_id
        elif isinstance(relationship.target_entity, str):
            target_id = relationship.target_entity
        else:
            target_id = str(relationship.target_entity)
        
        self.entity_relationships[source_id].add(relationship.relationship_id)
        self.entity_relationships[target_id].add(relationship.relationship_id)

        return relationship

    def get_entity_by_id(self, entity_id: str) -> Optional[Entity]:
        """Get an entity by its ID.

        Args:
            entity_id (str): Entity ID

        Returns:
            Optional[Entity]: The entity, or None if not found
        """
        return self.entities.get(entity_id)

    def get_relationship_by_id(self, relationship_id: str) -> Optional[Relationship]:
        """Get a relationship by its ID.

        Args:
            relationship_id (str): Relationship ID

        Returns:
            Optional[Relationship]: The relationship, or None if not found
        """
        return self.relationships.get(relationship_id)

    def get_entities_by_type(self, entity_type: str) -> List[Entity]:
        """Get all entities of a specific type.

        Args:
            entity_type (str): Entity type

        Returns:
            List[Entity]: List of entities of the specified type
        """
        entity_ids = self.entity_types.get(entity_type, set())
        return [self.entities[entity_id] for entity_id in entity_ids]

    def get_entities_by_name(self, name: str) -> List[Entity]:
        """Get all entities with a specific name.

        Args:
            name (str): Entity name

        Returns:
            List[Entity]: List of entities with the specified name
        """
        entity_ids = self.entity_names.get(name, set())
        return [self.entities[entity_id] for entity_id in entity_ids]

    def get_relationships_by_type(self, relationship_type: str) -> List[Relationship]:
        """Get all relationships of a specific type.

        Args:
            relationship_type (str): Relationship type

        Returns:
            List[Relationship]: List of relationships of the specified type
        """
        relationship_ids = self.relationship_types.get(relationship_type, set())
        return [self.relationships[rel_id] for rel_id in relationship_ids]

    def get_relationships_by_entity(self, entity: Entity) -> List[Relationship]:
        """Get all relationships involving a specific entity.

        Args:
            entity (Entity): The entity

        Returns:
            List[Relationship]: List of relationships involving the entity
        """
        relationship_ids = self.entity_relationships.get(entity.entity_id, set())
        return [self.relationships[rel_id] for rel_id in relationship_ids]

    def get_relationships_between(self, source: Entity, target: Entity) -> List[Relationship]:
        """
        Get all relationships between two entities.

        Args:
            source (Entity): Source entity
            target (Entity): Target entity

        Returns:
            List[Relationship]: List of relationships between the entities
        """
        # Get all relationships involving both entities
        source_rels = self.entity_relationships.get(source.entity_id, set())
        target_rels = self.entity_relationships.get(target.entity_id, set())
        common_rels = source_rels.intersection(target_rels)

        # Filter for relationships where source is the source and target is the target
        result = []
        for rel_id in common_rels:
            rel = self.relationships[rel_id]
            if (rel.source_id == source.entity_id and rel.target_id == target.entity_id) or \
               (rel.bidirectional and rel.source_id == target.entity_id and rel.target_id == source.entity_id):
                result.append(rel)

        return result

    def find_paths(
        self,
        source: Entity,
        target: Entity,
        max_depth: int = 3,
        relationship_types: Optional[List[str]] = None
    ) -> List[List[Tuple[Entity, Relationship, Entity]]]:
        """
        Find all paths between two entities up to a maximum depth.

        Args:
            source (Entity): Source entity
            target (Entity): Target entity
            max_depth (int): Maximum path depth
            relationship_types (List[str], optional): Types of relationships to follow

        Returns:
            List[List[Tuple[Entity, Relationship, Entity]]]: List of paths
        """
        # List to store all paths
        all_paths = []

        # Set to track visited entities
        visited = set()

        # DFS to find all paths
        def dfs(current_entity, path, depth):
            if depth > max_depth:
                return

            if current_entity.entity_id == target.entity_id:
                all_paths.append(path.copy())
                return

            visited.add(current_entity.entity_id)

            # Get all relationships involving the current entity
            rels = self.get_relationships_by_entity(current_entity)

            for rel in rels:
                # Check if relationship type is allowed
                if relationship_types and rel.relationship_type not in relationship_types:
                    continue

                # Follow outgoing relationships
                if rel.source_id == current_entity.entity_id and rel.target_id not in visited:
                    next_entity = self.entities[rel.target_id]
                    path.append((current_entity, rel, next_entity))
                    dfs(next_entity, path, depth + 1)
                    path.pop()

                # Follow incoming relationships if bidirectional
                elif rel.bidirectional and rel.target_id == current_entity.entity_id and rel.source_id not in visited:
                    next_entity = self.entities[rel.source_id]
                    path.append((current_entity, rel, next_entity))
                    dfs(next_entity, path, depth + 1)
                    path.pop()

            visited.remove(current_entity.entity_id)

        # Start DFS from source entity
        dfs(source, [], 0)

        return all_paths

    def query_by_properties(
        self,
        entity_type: Optional[str] = None,
        properties: Optional[Dict[str, Any]] = None
    ) -> List[Entity]:
        """
        Query entities by type and properties.

        Args:
            entity_type (str, optional): Entity type to filter by
            properties (Dict, optional): Properties to filter by

        Returns:
            List[Entity]: List of matching entities
        """
        # Start with all entities or entities of a specific type
        if entity_type:
            entities = self.get_entities_by_type(entity_type)
        else:
            entities = list(self.entities.values())

        # Filter by properties
        if properties:
            filtered_entities = []
            for entity in entities:
                match = True
                for key, value in properties.items():
                    if key not in entity.properties or entity.properties[key] != value:
                        match = False
                        break
                if match:
                    filtered_entities.append(entity)
            entities = filtered_entities

        return entities

    def merge(self, other: 'KnowledgeGraph') -> 'KnowledgeGraph':
        """Merge another knowledge graph into this one.

        Args:
            other (KnowledgeGraph): The knowledge graph to merge

        Returns:
            KnowledgeGraph: Self, after merging
        """
        # Create entity ID mapping for the other graph
        entity_id_map = {}

        # Add entities from the other graph
        for entity_id, entity in other.entities.items():
            # Check if entity already exists by name and type
            existing_entities = [e for e in self.get_entities_by_name(entity.name)
                               if e.entity_type == entity.entity_type]

            if existing_entities:
                # Use existing entity
                existing_entity = existing_entities[0]
                entity_id_map[entity_id] = existing_entity.entity_id

                # Merge properties
                for key, value in entity.properties.items():
                    if key not in existing_entity.properties:
                        existing_entity.properties[key] = value
            else:
                # Add new entity
                new_entity = self.add_entity(
                    entity_type=entity.entity_type,
                    name=entity.name,
                    properties=entity.properties.copy(),
                    confidence=entity.confidence,
                    source_text=entity.source_text
                )
                entity_id_map[entity_id] = new_entity.entity_id

        # Add relationships from the other graph
        for rel in other.relationships.values():
            if rel.source_id in entity_id_map and rel.target_id in entity_id_map:
                source_entity = self.entities[entity_id_map[rel.source_id]]
                target_entity = self.entities[entity_id_map[rel.target_id]]

                # Check if relationship already exists
                existing_rels = self.get_relationships_between(source_entity, target_entity)
                rel_exists = any(r.relationship_type == rel.relationship_type for r in existing_rels)

                if not rel_exists:
                    # Add new relationship
                    self.add_relationship(
                        relationship_type=rel.relationship_type,
                        source=source_entity,
                        target=target_entity,
                        properties=rel.properties.copy(),
                        confidence=rel.confidence,
                        source_text=rel.source_text,
                        bidirectional=rel.bidirectional
                    )
        return self

    def to_dict(self) -> Dict[str, Any]:
        """Convert the knowledge graph to a dictionary representation.

        Returns:
            Dict: Dictionary representation of the knowledge graph
        """
        return {
            "name": self.name,
            "entities": [entity.to_dict() for entity in self.entities.values()],
            "relationships": [rel.to_dict(include_entities=False) for rel in self.relationships.values()]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'KnowledgeGraph':
        """Create a knowledge graph from a dictionary representation.

        Args:
            data (Dict): Dictionary representation of the knowledge graph

        Returns:
            KnowledgeGraph: The created knowledge graph
        """
        # Create new knowledge graph
        kg = cls(name=data.get("name"))

        # Add entities
        for entity_data in data.get("entities", []):
            entity = Entity.from_dict(entity_data)
            kg.entities[entity.entity_id] = entity
            kg.entity_types[entity.entity_type].add(entity.entity_id)
            kg.entity_names[entity.name].add(entity.entity_id)

        # Add relationships
        for rel_data in data.get("relationships", []):
            rel = Relationship.from_dict(rel_data, entity_map=kg.entities)
            if rel.source_entity and rel.target_entity:
                kg.relationships[rel.relationship_id] = rel
                kg.relationship_types[rel.relationship_type].add(rel.relationship_id)
                kg.entity_relationships[rel.source_id].add(rel.relationship_id)
                kg.entity_relationships[rel.target_id].add(rel.relationship_id)

        return kg

    def to_json(self, indent: int = 2) -> str:
        """Convert the knowledge graph to a JSON string.

        Args:
            indent (int): Indentation level for JSON formatting

        Returns:
            str: JSON representation of the knowledge graph
        """
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, json_str: str) -> 'KnowledgeGraph':
        """Create a knowledge graph from a JSON string.

        Args:
            json_str (str): JSON representation of the knowledge graph

        Returns:
            KnowledgeGraph: The created knowledge graph
        """
        data = json.loads(json_str)
        return cls.from_dict(data)

    def export_to_rdf(self, format: str = "turtle") -> str:
        """Export the knowledge graph to RDF format.

        Args:
            format (str): RDF format ("turtle", "xml", "json-ld", "n3")

        Returns:
            str: RDF representation of the knowledge graph
        """
        try:
            from rdflib import Graph, Literal, URIRef, Namespace
            from rdflib.namespace import RDF, RDFS, XSD
        except ImportError:
            return f"Error: rdflib is required for RDF export. Install with: pip install rdflib"

        # Create RDF graph
        g = Graph()

        # Create namespaces
        KG = Namespace(f"http://example.org/kg/{self.name}/")
        ENT = Namespace(f"http://example.org/kg/{self.name}/entity/")
        REL = Namespace(f"http://example.org/kg/{self.name}/relation/")

        # Bind namespaces
        g.bind("kg", KG)
        g.bind("ent", ENT)
        g.bind("rel", REL)

        # Add entities
        for entity in self.entities.values():
            # Create entity URI
            entity_uri = ENT[entity.entity_id]

            # Add entity type
            g.add((entity_uri, RDF.type, KG[entity.entity_type]))

            # Add entity name
            g.add((entity_uri, RDFS.label, Literal(entity.name)))

            # Add entity properties
            for key, value in entity.properties.items():
                match value:
                    case str():
                        g.add((entity_uri, KG[key], Literal(value)))
                    case int():
                        g.add((entity_uri, KG[key], Literal(value, datatype=XSD.integer)))
                    case float():
                        g.add((entity_uri, KG[key], Literal(value, datatype=XSD.float)))
                    case bool():
                        g.add((entity_uri, KG[key], Literal(value, datatype=XSD.boolean)))
                    case _:
                        g.add((entity_uri, KG[key], Literal(str(value))))

        # Add relationships
        for rel in self.relationships.values():
            # Create relationship URI
            rel_uri = REL[rel.relationship_id]

            # Get source and target URIs
            source_uri = ENT[rel.source_id]
            target_uri = ENT[rel.target_id]

            # Add relationship type
            g.add((source_uri, KG[rel.relationship_type], target_uri))

            # For relationships with properties, add reification
            if rel.properties:
                g.add((rel_uri, RDF.type, RDF.Statement))
                g.add((rel_uri, RDF.subject, source_uri))
                g.add((rel_uri, RDF.predicate, KG[rel.relationship_type]))
                g.add((rel_uri, RDF.object, target_uri))

                # Add relationship properties
                for key, value in rel.properties.items():
                    if isinstance(value, str):
                        g.add((rel_uri, KG[key], Literal(value)))
                    elif isinstance(value, int):
                        g.add((rel_uri, KG[key], Literal(value, datatype=XSD.integer)))
                    elif isinstance(value, float):
                        g.add((rel_uri, KG[key], Literal(value, datatype=XSD.float)))
                    elif isinstance(value, bool):
                        g.add((rel_uri, KG[key], Literal(value, datatype=XSD.boolean)))
                    else:
                        g.add((rel_uri, KG[key], Literal(str(value))))

        # Serialize to requested format
        return g.serialize(format=format)


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


class KnowledgeGraphExtractorWithValidation:
    """
    Enhanced knowledge graph extractor with integrated validation.

    This class extends the knowledge graph extraction functionality with automated
    validation against external knowledge bases like Wikidata through SPARQL queries.
    It provides a unified interface for extracting and validating knowledge graphs,
    with options for automatic correction suggestions and continuous improvement.

    Key Features:
    - Automated validation during extraction
    - Entity property validation against Wikidata
    - Relationship validation against Wikidata
    - Suggestions for correcting invalid entities and relationships
    - Confidence scoring based on validation results
    - Detailed validation reports
    - Integrated with WikipediaKnowledgeGraphTracer for tracing
    """

    def __init__(
        self,
        use_spacy: bool = False,
        use_transformers: bool = False,
        relation_patterns: Optional[List[Dict[str, Any]]] = None,
        min_confidence: float = 0.5,
        use_tracer: bool = True,
        sparql_endpoint_url: str = "https://query.wikidata.org/sparql",
        validate_during_extraction: bool = True,
        auto_correct_suggestions: bool = False,
        cache_validation_results: bool = True
    ):
        """
        Initialize the knowledge graph extractor with validation.

        Args:
            use_spacy: Whether to use spaCy for extraction
            use_transformers: Whether to use Transformers for extraction
            relation_patterns: Custom relation extraction patterns
            min_confidence: Minimum confidence threshold for extraction
            use_tracer: Whether to use the WikipediaKnowledgeGraphTracer
            sparql_endpoint_url: URL of the SPARQL endpoint for validation
            validate_during_extraction: Whether to validate during extraction
            auto_correct_suggestions: Whether to generate correction suggestions
            cache_validation_results: Whether to cache validation results
        """
        # Initialize the base extractor
        self.extractor = KnowledgeGraphExtractor(
            use_spacy=use_spacy,
            use_transformers=use_transformers,
            relation_patterns=relation_patterns,
            min_confidence=min_confidence,
            use_tracer=use_tracer
        )

        # Initialize tracer if enabled
        self.tracer = WikipediaKnowledgeGraphTracer() if use_tracer else None

        # Initialize validator
        try:
            from ipfs_datasets_py.llm.llm_semantic_validation import SPARQLValidator
            self.validator = SPARQLValidator(
                endpoint_url=sparql_endpoint_url,
                tracer=self.tracer,
                cache_results=cache_validation_results
            )
            self.validator_available = True
        except ImportError:
            print("Warning: SPARQLValidator not available. Validation will be disabled.")
            self.validator = None
            self.validator_available = False

        # Configuration options
        self.validate_during_extraction = validate_during_extraction and self.validator_available
        self.auto_correct_suggestions = auto_correct_suggestions
        self.min_confidence = min_confidence

    def extract_knowledge_graph(
        self,
        text: str,
        extraction_temperature: float = 0.7,
        structure_temperature: float = 0.5,
        validation_depth: int = 1
    ) -> Dict[str, Any]:
        """
        Extract and validate a knowledge graph from text.

        Args:
            text: Text to extract knowledge graph from
            extraction_temperature: Controls level of detail (0.0-1.0)
            structure_temperature: Controls structural complexity (0.0-1.0)
            validation_depth: Depth of validation (1=entities, 2=relationships)

        Returns:
            Dict containing:
                - knowledge_graph: The extracted knowledge graph
                - validation_results: Validation results if enabled
                - validation_metrics: Validation metrics if enabled
                - corrections: Correction suggestions if enabled
        """
        # Create trace if tracer is enabled
        trace_id = None
        if self.tracer:
            trace_id = self.tracer.trace_extraction_and_validation(
                page_title="Custom Text",
                extraction_temperature=extraction_temperature,
                structure_temperature=structure_temperature
            )

        try:
            # Extract knowledge graph
            kg = self.extractor.extract_enhanced_knowledge_graph(
                text=text,
                use_chunking=True,
                extraction_temperature=extraction_temperature,
                structure_temperature=structure_temperature
            )

            result = {
                "knowledge_graph": kg,
                "entity_count": len(kg.entities),
                "relationship_count": len(kg.relationships)
            }

            # Perform validation if enabled
            if self.validate_during_extraction and self.validator:
                validation_result = self.validator.validate_knowledge_graph(
                    kg=kg,
                    validation_depth=validation_depth,
                    min_confidence=self.min_confidence
                )

                result["validation_results"] = validation_result.to_dict()
                result["validation_metrics"] = {
                    "entity_coverage": validation_result.data.get("entity_coverage", 0.0),
                    "relationship_coverage": validation_result.data.get("relationship_coverage", 0.0),
                    "overall_coverage": validation_result.data.get("overall_coverage", 0.0)
                }

                # Generate correction suggestions if enabled
                if self.auto_correct_suggestions:
                    corrections = {}

                    # Entity corrections
                    if "entity_validations" in validation_result.data:
                        entity_corrections = {}
                        for entity_id, validation in validation_result.data["entity_validations"].items():
                            if not validation.get("valid", False):
                                explanation = self.validator.generate_validation_explanation(
                                    validation_result,
                                    explanation_type="fix"
                                )
                                entity_corrections[entity_id] = {
                                    "entity_name": validation.get("name", ""),
                                    "suggestions": explanation
                                }

                        if entity_corrections:
                            corrections["entities"] = entity_corrections

                    # Relationship corrections
                    if "relationship_validations" in validation_result.data:
                        rel_corrections = {}
                        for rel_id, validation in validation_result.data["relationship_validations"].items():
                            if not validation.get("valid", False):
                                rel_corrections[rel_id] = {
                                    "source": validation.get("source", ""),
                                    "relationship_type": validation.get("relationship_type", ""),
                                    "target": validation.get("target", ""),
                                    "suggestions": f"Consider using '{validation.get('wikidata_match', '')}' instead"
                                }

                        if rel_corrections:
                            corrections["relationships"] = rel_corrections

                    if corrections:
                        result["corrections"] = corrections

            # Update trace if enabled
            if self.tracer and trace_id:
                self.tracer.update_extraction_and_validation_trace(
                    trace_id=trace_id,
                    status="completed",
                    knowledge_graph=kg,
                    validation_results=result.get("validation_results", {}),
                    entity_count=len(kg.entities),
                    relationship_count=len(kg.relationships),
                    coverage=result.get("validation_metrics", {}).get("overall_coverage", 0.0)
                )

            return result

        except Exception as e:
            error_result = {
                "error": f"Error extracting and validating knowledge graph: {e}",
                "knowledge_graph": None
            }

            # Update trace with error if tracer is enabled
            if self.tracer and trace_id:
                self.tracer.update_extraction_and_validation_trace(
                    trace_id=trace_id,
                    status="failed",
                    error=str(e)
                )

            return error_result

    def extract_from_wikipedia(
        self,
        page_title: str,
        extraction_temperature: float = 0.7,
        structure_temperature: float = 0.5,
        validation_depth: int = 2,
        focus_validation_on_main_entity: bool = True
    ) -> Dict[str, Any]:
        """
        Extract and validate a knowledge graph from a Wikipedia page.

        Args:
            page_title: Title of the Wikipedia page
            extraction_temperature: Controls level of detail (0.0-1.0)
            structure_temperature: Controls structural complexity (0.0-1.0)
            validation_depth: Depth of validation (1=entities, 2=relationships)
            focus_validation_on_main_entity: Whether to focus validation on main entity

        Returns:
            Dict containing:
                - knowledge_graph: The extracted knowledge graph
                - validation_results: Validation results
                - validation_metrics: Validation metrics
                - corrections: Correction suggestions if enabled
        """
        # Create trace if tracer is enabled
        trace_id = None
        if self.tracer:
            trace_id = self.tracer.trace_extraction_and_validation(
                page_title=page_title,
                extraction_temperature=extraction_temperature,
                structure_temperature=structure_temperature
            )

        try:
            # Extract knowledge graph from Wikipedia
            kg = self.extractor.extract_from_wikipedia(
                page_title=page_title,
                extraction_temperature=extraction_temperature,
                structure_temperature=structure_temperature
            )

            result = {
                "knowledge_graph": kg,
                "entity_count": len(kg.entities),
                "relationship_count": len(kg.relationships)
            }

            # Perform validation if enabled
            if self.validate_during_extraction and self.validator:
                if focus_validation_on_main_entity:
                    # Validate with focus on main entity
                    validation_result = self.validator.validate_knowledge_graph(
                        kg=kg,
                        main_entity_name=page_title,
                        validation_depth=validation_depth,
                        min_confidence=self.min_confidence
                    )
                else:
                    # Validate entire knowledge graph
                    validation_result = self.validator.validate_knowledge_graph(
                        kg=kg,
                        validation_depth=validation_depth,
                        min_confidence=self.min_confidence
                    )

                result["validation_results"] = validation_result.to_dict()

                # Extract validation metrics
                if "entity_name" in validation_result.data:
                    # Single entity focus validation
                    result["validation_metrics"] = {
                        "property_coverage": validation_result.data.get("property_coverage", 0.0),
                        "relationship_coverage": validation_result.data.get("relationship_coverage", 0.0),
                        "overall_coverage": validation_result.data.get("overall_coverage", 0.0)
                    }
                else:
                    # Full knowledge graph validation
                    result["validation_metrics"] = {
                        "entity_coverage": validation_result.data.get("entity_coverage", 0.0),
                        "relationship_coverage": validation_result.data.get("relationship_coverage", 0.0),
                        "overall_coverage": validation_result.data.get("overall_coverage", 0.0)
                    }

                # Generate correction suggestions if enabled
                if self.auto_correct_suggestions:
                    explanation = self.validator.generate_validation_explanation(
                        validation_result,
                        explanation_type="fix"
                    )
                    result["corrections"] = explanation

                # Perform path finding between key entities
                if len(kg.entities) >= 2:
                    # Find main entity
                    main_entities = [e for e in kg.entities.values() if e.name.lower() == page_title.lower()]

                    if main_entities and validation_depth > 1:
                        main_entity = main_entities[0]

                        # Find path to at least one other important entity
                        other_entities = []
                        for entity in kg.entities.values():
                            if entity.entity_id != main_entity.entity_id and hasattr(entity, "confidence") and entity.confidence > 0.8:
                                other_entities.append(entity)

                        if other_entities:
                            # Take the entity with highest confidence
                            other_entity = max(other_entities, key=lambda e: getattr(e, "confidence", 0))

                            # Find paths between entities
                            path_result = self.validator.find_entity_paths(
                                source_entity=main_entity.name,
                                target_entity=other_entity.name,
                                max_path_length=2
                            )

                            if path_result.is_valid:
                                result["path_analysis"] = path_result.to_dict()

            # Update trace if enabled
            if self.tracer and trace_id:
                self.tracer.update_extraction_and_validation_trace(
                    trace_id=trace_id,
                    status="completed",
                    knowledge_graph=kg,
                    validation_results=result.get("validation_results", {}),
                    entity_count=len(kg.entities),
                    relationship_count=len(kg.relationships),
                    coverage=result.get("validation_metrics", {}).get("overall_coverage", 0.0)
                )

            return result

        except Exception as e:
            error_result = {
                "error": f"Error extracting and validating Wikipedia knowledge graph: {e}",
                "knowledge_graph": None
            }

            # Update trace with error if tracer is enabled
            if self.tracer and trace_id:
                self.tracer.update_extraction_and_validation_trace(
                    trace_id=trace_id,
                    status="failed",
                    error=str(e)
                )

            return error_result

    def extract_from_documents(
        self,
        documents: List[Dict[str, str]],
        text_key: str = "text",
        extraction_temperature: float = 0.7,
        structure_temperature: float = 0.5,
        validation_depth: int = 1
    ) -> Dict[str, Any]:
        """
        Extract and validate a knowledge graph from multiple documents.

        Args:
            documents: List of document dictionaries
            text_key: Key for the text field in the documents
            extraction_temperature: Controls level of detail (0.0-1.0)
            structure_temperature: Controls structural complexity (0.0-1.0)
            validation_depth: Depth of validation (1=entities, 2=relationships)

        Returns:
            Dict containing:
                - knowledge_graph: The extracted knowledge graph
                - validation_results: Validation results if enabled
                - validation_metrics: Validation metrics if enabled
                - corrections: Correction suggestions if enabled
        """
        # Create trace if tracer is enabled
        trace_id = None
        if self.tracer:
            trace_id = self.tracer.trace_extraction_and_validation(
                page_title="Multiple Documents",
                extraction_temperature=extraction_temperature,
                structure_temperature=structure_temperature
            )

        try:
            # Extract knowledge graph from documents
            kg = self.extractor.extract_from_documents(
                documents=documents,
                text_key=text_key,
                extraction_temperature=extraction_temperature,
                structure_temperature=structure_temperature
            )

            # Enrich with inferred types
            kg = self.extractor.enrich_with_types(kg)

            result = {
                "knowledge_graph": kg,
                "entity_count": len(kg.entities),
                "relationship_count": len(kg.relationships)
            }

            # Perform validation if enabled
            if self.validate_during_extraction and self.validator:
                validation_result = self.validator.validate_knowledge_graph(
                    kg=kg,
                    validation_depth=validation_depth,
                    min_confidence=self.min_confidence
                )

                result["validation_results"] = validation_result.to_dict()
                result["validation_metrics"] = {
                    "entity_coverage": validation_result.data.get("entity_coverage", 0.0),
                    "relationship_coverage": validation_result.data.get("relationship_coverage", 0.0),
                    "overall_coverage": validation_result.data.get("overall_coverage", 0.0)
                }

                # Generate correction suggestions if enabled
                if self.auto_correct_suggestions:
                    explanation = self.validator.generate_validation_explanation(
                        validation_result,
                        explanation_type="fix"
                    )
                    result["corrections"] = explanation

                # Additional validation: find entity paths
                if validation_depth > 1:
                    # Select top entities by confidence
                    top_entities = sorted(
                        [e for e in kg.entities.values() if hasattr(e, "confidence") and e.confidence > 0.8],
                        key=lambda e: getattr(e, "confidence", 0),
                        reverse=True
                    )[:5]  # Top 5 entities

                    # Find paths between pairs of top entities
                    path_results = []
                    for i in range(len(top_entities)):
                        for j in range(i + 1, len(top_entities)):
                            entity1 = top_entities[i]
                            entity2 = top_entities[j]

                            path_result = self.validator.find_entity_paths(
                                source_entity=entity1.name,
                                target_entity=entity2.name,
                                max_path_length=2
                            )

                            if path_result.is_valid:
                                path_results.append({
                                    "source": entity1.name,
                                    "target": entity2.name,
                                    "paths": path_result.data
                                })

                    if path_results:
                        result["path_analysis"] = path_results

            # Update trace if enabled
            if self.tracer and trace_id:
                self.tracer.update_extraction_and_validation_trace(
                    trace_id=trace_id,
                    status="completed",
                    knowledge_graph=kg,
                    validation_results=result.get("validation_results", {}),
                    entity_count=len(kg.entities),
                    relationship_count=len(kg.relationships),
                    coverage=result.get("validation_metrics", {}).get("overall_coverage", 0.0)
                )

            return result

        except Exception as e:
            error_result = {
                "error": f"Error extracting and validating multi-document knowledge graph: {e}",
                "knowledge_graph": None
            }

            # Update trace with error if tracer is enabled
            if self.tracer and trace_id:
                self.tracer.update_extraction_and_validation_trace(
                    trace_id=trace_id,
                    status="failed",
                    error=str(e)
                )

            return error_result

    def apply_validation_corrections(
        self,
        kg: KnowledgeGraph,
        corrections: Dict[str, Any]
    ) -> KnowledgeGraph:
        """
        Apply correction suggestions to a knowledge graph.

        Args:
            kg: Knowledge graph to correct
            corrections: Correction suggestions from validation

        Returns:
            KnowledgeGraph: Corrected knowledge graph
        """
        # Create a copy of the knowledge graph to avoid modifying the original
        corrected_kg = KnowledgeGraph(name=kg.name)

        # Create maps for tracking corrections
        entity_corrections = {}
        relationship_type_corrections = {}

        # Parse entity corrections
        if "entities" in corrections:
            for entity_id, entity_correction in corrections["entities"].items():
                # TODO entity_name is not referenced anywhere. See if we need it.
                entity_name = entity_correction.get("entity_name", "")
                suggestions = entity_correction.get("suggestions", "")

                # Process suggestions to extract corrections
                # # TODO This is simplified - in a real implementation, more sophisticated . SO WE'RE GUNNA MAKE IT MORE SOPHISTICATED DAMNIT!
                # parsing of the suggestion text would be needed
                if isinstance(suggestions, dict):
                    # Structured suggestions
                    entity_corrections[entity_id] = suggestions
                elif isinstance(suggestions, str) and ":" in suggestions:
                    # Simple text parsing
                    correction_map = {}
                    for line in suggestions.split("\n"):
                        if ":" in line:
                            key, value = line.split(":", 1)
                            correction_map[key.strip()] = value.strip()
                    entity_corrections[entity_id] = correction_map

        # Parse relationship corrections
        if "relationships" in corrections:
            for rel_id, rel_correction in corrections["relationships"].items():
                rel_type = rel_correction.get("relationship_type", "")
                suggestions = rel_correction.get("suggestions", "")

                # Extract suggested relationship type
                if "instead" in suggestions and "'" in suggestions:
                    import re
                    match = re.search(r"'([^']+)'", suggestions)
                    if match:
                        relationship_type_corrections[rel_type] = match.group(1)

        # Apply entity corrections
        for original_entity_id, entity in kg.entities.items():
            # Create a copy of the entity
            entity_properties = entity.properties.copy() if hasattr(entity, "properties") else {}

            # Apply property corrections if available
            if original_entity_id in entity_corrections:
                for prop, correction in entity_corrections[original_entity_id].items():
                    if prop in entity_properties:
                        entity_properties[prop] = correction

            # Add the corrected entity
            # TODO corrected_entity is not reference anywhere. See if we need it.
            corrected_entity = corrected_kg.add_entity(
                entity_type=entity.entity_type if hasattr(entity, "entity_type") else "entity",
                name=entity.name if hasattr(entity, "name") else "Unknown",
                properties=entity_properties,
                entity_id=original_entity_id,
                confidence=entity.confidence if hasattr(entity, "confidence") else 1.0,
                source_text=entity.source_text if hasattr(entity, "source_text") else None
            )

        # Apply relationship corrections
        for rel_id, rel in kg.relationships.items():
            # Get source and target entities
            source_entity = corrected_kg.get_entity_by_id(rel.source_id)
            target_entity = corrected_kg.get_entity_by_id(rel.target_id)

            if source_entity and target_entity:
                # Correct relationship type if needed
                rel_type = rel.relationship_type if hasattr(rel, "relationship_type") else "related_to"
                if rel_type in relationship_type_corrections:
                    rel_type = relationship_type_corrections[rel_type]

                # Create the corrected relationship
                corrected_kg.add_relationship(
                    relationship_type=rel_type,
                    source=source_entity,
                    target=target_entity,
                    properties=rel.properties.copy() if hasattr(rel, "properties") else {},
                    relationship_id=rel_id,
                    confidence=rel.confidence if hasattr(rel, "confidence") else 1.0,
                    source_text=rel.source_text if hasattr(rel, "source_text") else None,
                    bidirectional=rel.bidirectional if hasattr(rel, "bidirectional") else False
                )

        return corrected_kg


############# HELPER FUNCTIONS #############

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