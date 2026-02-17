"""
Knowledge Graph Container Module.

This module contains the KnowledgeGraph class which provides a container
for entities and relationships with efficient querying, indexing, and
manipulation capabilities.

Example:
    ```python
    from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph, Entity, Relationship
    
    # Create a knowledge graph
    kg = KnowledgeGraph(name="my_graph")
    
    # Add entities
    person1 = kg.add_entity("person", "Alice", properties={"age": 30})
    person2 = kg.add_entity("person", "Bob", properties={"age": 25})
    
    # Add relationship
    kg.add_relationship("knows", person1, person2, confidence=0.9)
    
    # Query
    people = kg.get_entities_by_type("person")
    knows_rels = kg.get_relationships_by_type("knows")
    
    # Serialize
    kg_dict = kg.to_dict()
    kg_json = kg.to_json()
    ```

Phase: Phase 3 Task 3.4 - KnowledgeGraph class extraction
"""

from typing import Dict, List, Optional, Any, Tuple, Set, Union
from collections import defaultdict
import json

from ipfs_datasets_py.knowledge_graphs.extraction.types import (
    EntityID,
    RelationshipID,
    EntityType,
    RelationshipType,
    uuid,
)
from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity
from ipfs_datasets_py.knowledge_graphs.extraction.relationships import Relationship


class KnowledgeGraph:
    """
    A knowledge graph containing entities and relationships.

    Provides methods for adding, querying, and manipulating entities
    and relationships in the knowledge graph.
    
    Attributes:
        name (str): Name of the knowledge graph
        entities (Dict[str, Entity]): Dictionary of entities by ID
        relationships (Dict[str, Relationship]): Dictionary of relationships by ID
        entity_types (Dict[str, Set[str]]): Index of entities by type
        entity_names (Dict[str, Set[str]]): Index of entities by name
        relationship_types (Dict[str, Set[str]]): Index of relationships by type
        entity_relationships (Dict[str, Set[str]]): Index of relationships by entity ID
    
    Example:
        ```python
        kg = KnowledgeGraph(name="example")
        entity1 = kg.add_entity("person", "Alice")
        entity2 = kg.add_entity("person", "Bob")
        rel = kg.add_relationship("knows", entity1, entity2)
        ```
    """

    def __init__(self, name: str = None):
        """Initialize a new knowledge graph.

        Args:
            name (str, optional): Name of the knowledge graph. Generated if None.
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
        entity_type_or_entity: Union[str, Entity, None] = None,
        name: Optional[str] = None,
        properties: Optional[Dict[str, Any]] = None,
        entity_id: str = None,
        confidence: float = 1.0,
        source_text: str = None,
        entity_type: Optional[str] = None,
        **_ignored_kwargs: Any,
    ) -> Entity:
        """Add an entity to the knowledge graph.

        Supports two calling patterns:
        1. add_entity(entity_object) - Add an existing Entity
        2. add_entity(entity_type, name, ...) - Create and add new Entity

        Args:
            entity_type_or_entity: Either entity type string OR Entity object
            name (str): Name of the entity (required if first arg is string)
            properties (Dict, optional): Additional properties
            entity_id (str, optional): Unique identifier (generated if None)
            confidence (float): Confidence score
            source_text (str, optional): Source text

        Returns:
            Entity: The added entity
        
        Example:
            ```python
            # Pattern 1: Add existing entity
            entity = Entity(entity_type="person", name="Alice")
            kg.add_entity(entity)
            
            # Pattern 2: Create and add
            entity = kg.add_entity("person", "Bob", properties={"age": 30})
            ```
        """
        # Backward-compatible alias: allow keyword `entity_type=`
        if entity_type_or_entity is None and entity_type is not None:
            entity_type_or_entity = entity_type

        # Handle both calling patterns
        if isinstance(entity_type_or_entity, Entity):
            # Called with Entity object: add_entity(entity)
            entity = entity_type_or_entity
        else:
            # Called with parameters: add_entity(entity_type, name, ...)
            if name is None:
                raise ValueError("name parameter is required when first argument is entity_type string")

            entity_kwargs: Dict[str, Any] = {
                "entity_type": entity_type_or_entity,
                "name": name,
                "properties": properties,
                "confidence": confidence,
                "source_text": source_text,
            }
            if entity_id is not None:
                entity_kwargs["entity_id"] = entity_id

            entity = Entity(**entity_kwargs)

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

        Supports two calling patterns:
        1. add_relationship(relationship_object) - Add an existing Relationship
        2. add_relationship(relationship_type, source, target, ...) - Create and add new

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
        
        Example:
            ```python
            # Pattern 1: Add existing relationship
            rel = Relationship.create(entity1, entity2, "knows")
            kg.add_relationship(rel)
            
            # Pattern 2: Create and add
            rel = kg.add_relationship("knows", entity1, entity2, confidence=0.9)
            ```
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
                    entity_id=entity.entity_id,
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
