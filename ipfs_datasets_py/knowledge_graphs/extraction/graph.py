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

from typing import Callable, Dict, List, Optional, Any, Tuple, Set, Union
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
import json
import time

from ipfs_datasets_py.knowledge_graphs.extraction.types import (
    EntityID,
    RelationshipID,
    EntityType,
    RelationshipType,
    uuid,
)
from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity
from ipfs_datasets_py.knowledge_graphs.extraction.relationships import Relationship


class GraphEventType(str, Enum):
    """Event types emitted by :class:`KnowledgeGraph` mutations.

    Implements the *real-time graph streaming* feature (v4.0+ roadmap).
    Attach a subscriber via :meth:`KnowledgeGraph.subscribe` to observe
    every structural change to the graph in real time.
    """
    ENTITY_ADDED = "entity_added"
    ENTITY_REMOVED = "entity_removed"
    ENTITY_MODIFIED = "entity_modified"
    RELATIONSHIP_ADDED = "relationship_added"
    RELATIONSHIP_REMOVED = "relationship_removed"


@dataclass
class GraphEvent:
    """A single event emitted by a :class:`KnowledgeGraph` mutation.

    Attributes:
        event_type: The type of structural change that occurred.
        timestamp: Unix timestamp (``time.time()``) when the event was emitted.
        entity_id: ID of the affected entity (if applicable).
        relationship_id: ID of the affected relationship (if applicable).
        data: Optional dict with additional context (e.g. entity_type, name).
    """
    event_type: GraphEventType
    timestamp: float
    entity_id: Optional[str] = None
    relationship_id: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


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

        # Event subscriptions (real-time graph streaming — v4.0+ roadmap)
        self._event_subscribers: Dict[int, Callable[[GraphEvent], None]] = {}
        self._next_subscriber_id: int = 0

        # Named snapshots (temporal graph versioning — v4.0+ roadmap)
        self._snapshots: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Event subscription API (real-time graph streaming — v4.0+ roadmap)
    # ------------------------------------------------------------------

    def subscribe(self, callback: Callable[[GraphEvent], None]) -> int:
        """Register a callback to receive :class:`GraphEvent` notifications.

        The callback is invoked synchronously after every structural mutation
        (entity/relationship add/remove/modify).  Exceptions raised inside the
        callback are silently suppressed so that a faulty subscriber never
        disrupts graph operations.

        Args:
            callback: A callable that accepts a single :class:`GraphEvent`
                argument.

        Returns:
            int: A handler ID that can be passed to :meth:`unsubscribe` to
                remove the subscription.

        Example::

            events = []
            hid = kg.subscribe(events.append)
            kg.add_entity("person", "Alice")
            # events[0].event_type == GraphEventType.ENTITY_ADDED
            kg.unsubscribe(hid)
        """
        handler_id = self._next_subscriber_id
        self._event_subscribers[handler_id] = callback
        self._next_subscriber_id += 1
        return handler_id

    def unsubscribe(self, handler_id: int) -> bool:
        """Remove a previously registered event subscriber.

        Args:
            handler_id (int): The ID returned by :meth:`subscribe`.

        Returns:
            bool: ``True`` if the subscriber existed and was removed,
                ``False`` if the ID was not found.
        """
        if handler_id in self._event_subscribers:
            del self._event_subscribers[handler_id]
            return True
        return False

    def _emit_event(self, event: GraphEvent) -> None:
        """Emit *event* to all registered subscribers.

        Exceptions raised by subscribers are silently ignored.

        Args:
            event (GraphEvent): The event to emit.
        """
        for cb in list(self._event_subscribers.values()):
            try:
                cb(event)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # Snapshot API (temporal graph versioning — v4.0+ roadmap)
    # ------------------------------------------------------------------

    def snapshot(self, name: Optional[str] = None) -> str:
        """Capture a named snapshot of the current graph state.

        The snapshot stores a serialized copy of all entities and
        relationships.  It can later be restored with
        :meth:`restore_snapshot`.

        Args:
            name (str, optional): A human-readable name for the snapshot.
                Defaults to a short UUID slug (``snap_<8 chars>``).

        Returns:
            str: The snapshot name (useful when *name* was not provided).

        Example::

            snap_name = kg.snapshot("before_merge")
            kg.add_entity("org", "Acme Corp")
            kg.restore_snapshot("before_merge")  # reverts the add
        """
        if name is None:
            name = f"snap_{str(uuid.uuid4())[:8]}"
        self._snapshots[name] = {
            "entities": [e.to_dict() for e in self.entities.values()],
            "relationships": [r.to_dict(include_entities=False) for r in self.relationships.values()],
        }
        return name

    def get_snapshot(self, name: str) -> Optional[Dict[str, Any]]:
        """Return a copy of a previously captured snapshot dict.

        Args:
            name (str): Snapshot name as returned by :meth:`snapshot`.

        Returns:
            Optional[Dict]: A shallow copy of the snapshot payload
                (``{"entities": [...], "relationships": [...]}``) or
                ``None`` if no snapshot with *name* exists.
        """
        snap = self._snapshots.get(name)
        if snap is None:
            return None
        return {"entities": list(snap["entities"]), "relationships": list(snap["relationships"])}

    def list_snapshots(self) -> List[str]:
        """Return a sorted list of all snapshot names.

        Returns:
            List[str]: Snapshot names in lexicographical order.
        """
        return sorted(self._snapshots.keys())

    def restore_snapshot(self, name: str) -> bool:
        """Restore the graph to a previously captured snapshot state.

        All current entities, relationships, and index data are replaced
        with the snapshot contents.  Registered event subscribers are
        **not** notified during restore (the graph state is replaced
        atomically from the caller's perspective).

        Args:
            name (str): Snapshot name as returned by :meth:`snapshot`.

        Returns:
            bool: ``True`` if the snapshot was found and applied,
                ``False`` if *name* does not match any stored snapshot.

        Example::

            snap = kg.snapshot()
            kg.add_entity("person", "Temporary")
            assert kg.restore_snapshot(snap)
            assert not kg.get_entities_by_name("Temporary")
        """
        snap = self._snapshots.get(name)
        if snap is None:
            return False

        # Replace internal state
        self.entities = {}
        self.relationships = {}
        self.entity_types = defaultdict(set)
        self.entity_names = defaultdict(set)
        self.relationship_types = defaultdict(set)
        self.entity_relationships = defaultdict(set)

        for e_dict in snap["entities"]:
            entity = Entity.from_dict(e_dict)
            self.entities[entity.entity_id] = entity
            self.entity_types[entity.entity_type].add(entity.entity_id)
            self.entity_names[entity.name].add(entity.entity_id)

        for r_dict in snap["relationships"]:
            rel = Relationship.from_dict(r_dict, entity_map=self.entities)
            if rel.source_entity and rel.target_entity:
                self.relationships[rel.relationship_id] = rel
                self.relationship_types[rel.relationship_type].add(rel.relationship_id)
                self.entity_relationships[rel.source_id].add(rel.relationship_id)
                self.entity_relationships[rel.target_id].add(rel.relationship_id)

        return True

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

        # Emit event
        self._emit_event(GraphEvent(
            event_type=GraphEventType.ENTITY_ADDED,
            timestamp=time.time(),
            entity_id=entity.entity_id,
            data={"entity_type": entity.entity_type, "name": entity.name},
        ))

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
            
            relationship_kwargs: Dict[str, Any] = {
                "relationship_type": relationship_type_or_relationship,
                "source_entity": source,
                "target_entity": target,
                "properties": properties,
                "confidence": confidence,
                "source_text": source_text,
                "bidirectional": bidirectional,
            }
            if relationship_id is not None:
                relationship_kwargs["relationship_id"] = relationship_id

            relationship = Relationship(**relationship_kwargs)

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

        # Emit event
        self._emit_event(GraphEvent(
            event_type=GraphEventType.RELATIONSHIP_ADDED,
            timestamp=time.time(),
            relationship_id=relationship.relationship_id,
            data={"relationship_type": relationship.relationship_type},
        ))

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
                if existing_entity.properties is None:
                    existing_entity.properties = {}
                for key, value in (entity.properties or {}).items():
                    if key not in existing_entity.properties:
                        existing_entity.properties[key] = value
            else:
                # Add new entity
                new_entity = self.add_entity(
                    entity_type=entity.entity_type,
                    name=entity.name,
                    properties=(entity.properties.copy() if entity.properties else {}),
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
                        rel.relationship_type,
                        source=source_entity,
                        target=target_entity,
                        properties=(rel.properties.copy() if rel.properties else {}),
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
                    case bool():
                        g.add((entity_uri, KG[key], Literal(value, datatype=XSD.boolean)))
                    case int():
                        g.add((entity_uri, KG[key], Literal(value, datatype=XSD.integer)))
                    case float():
                        g.add((entity_uri, KG[key], Literal(value, datatype=XSD.float)))
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
                    elif isinstance(value, bool):
                        g.add((rel_uri, KG[key], Literal(value, datatype=XSD.boolean)))
                    elif isinstance(value, int):
                        g.add((rel_uri, KG[key], Literal(value, datatype=XSD.integer)))
                    elif isinstance(value, float):
                        g.add((rel_uri, KG[key], Literal(value, datatype=XSD.float)))
                    else:
                        g.add((rel_uri, KG[key], Literal(str(value))))

        # Serialize to requested format
        return g.serialize(format=format)

    def diff(self, other: 'KnowledgeGraph') -> 'KnowledgeGraphDiff':
        """Compute the structural difference between this graph and another.

        Entities are matched by (entity_type, name) fingerprint; relationships
        are matched by (relationship_type, source_fingerprint, target_fingerprint).

        Args:
            other (KnowledgeGraph): The graph to compare against.

        Returns:
            KnowledgeGraphDiff: The diff describing what was added, removed, and
            modified when moving from *self* to *other*.

        Example:
            ```python
            diff = kg1.diff(kg2)
            if not diff.is_empty:
                print(diff.summary())
                kg1.apply_diff(diff)
            ```
        """
        def _entity_fp(entity: Entity) -> Tuple[str, str]:
            return (entity.entity_type or "", entity.name or "")

        def _rel_fp(
            rel: Relationship,
            entity_map: Dict[str, Entity],
        ) -> Tuple[str, Tuple[str, str], Tuple[str, str]]:
            src = entity_map.get(rel.source_id or "")
            tgt = entity_map.get(rel.target_id or "")
            src_fp = _entity_fp(src) if src else ("", rel.source_id or "")
            tgt_fp = _entity_fp(tgt) if tgt else ("", rel.target_id or "")
            return (rel.relationship_type or "", src_fp, tgt_fp)

        self_ent: Dict[Tuple[str, str], Entity] = {
            _entity_fp(e): e for e in self.entities.values()
        }
        other_ent: Dict[Tuple[str, str], Entity] = {
            _entity_fp(e): e for e in other.entities.values()
        }

        # Entities added (in other, not in self)
        added_entities = [
            e.to_dict() for fp, e in other_ent.items() if fp not in self_ent
        ]
        # Entities removed (in self, not in other)
        removed_entity_ids = [
            self_ent[fp].entity_id for fp in self_ent if fp not in other_ent
        ]
        # Entities modified (same fingerprint, different properties)
        modified_entities: List[Dict[str, Any]] = []
        for fp in self_ent:
            if fp in other_ent:
                se = self_ent[fp]
                oe = other_ent[fp]
                old_props = dict(se.properties or {})
                new_props = dict(oe.properties or {})
                if old_props != new_props:
                    modified_entities.append({
                        "entity_id": se.entity_id,
                        "fingerprint": list(fp),
                        "old_properties": old_props,
                        "new_properties": new_props,
                    })

        self_rel: Dict = {
            _rel_fp(r, self.entities): r for r in self.relationships.values()
        }
        other_rel: Dict = {
            _rel_fp(r, other.entities): r for r in other.relationships.values()
        }

        # Relationships added (in other, not in self)
        added_relationships = [
            r.to_dict(include_entities=True)
            for fp, r in other_rel.items()
            if fp not in self_rel
        ]
        # Relationships removed (in self, not in other)
        removed_relationship_ids = [
            self_rel[fp].relationship_id for fp in self_rel if fp not in other_rel
        ]

        return KnowledgeGraphDiff(
            added_entities=added_entities,
            removed_entity_ids=removed_entity_ids,
            added_relationships=added_relationships,
            removed_relationship_ids=removed_relationship_ids,
            modified_entities=modified_entities,
        )

    def apply_diff(self, diff: 'KnowledgeGraphDiff') -> None:
        """Apply a diff to this graph in-place.

        Removes entities/relationships listed in *diff.removed_entity_ids* and
        *diff.removed_relationship_ids* (entity removal cascades to its relationships),
        adds entities from *diff.added_entities*, applies property changes from
        *diff.modified_entities*, and adds relationships from *diff.added_relationships*.

        Args:
            diff (KnowledgeGraphDiff): The diff to apply (as produced by
                ``other_graph.diff(self)`` or ``self.diff(other_graph)``).

        Example:
            ```python
            diff = original.diff(updated)
            copy = KnowledgeGraph.from_dict(original.to_dict())
            copy.apply_diff(diff)
            ```
        """
        # 1. Remove entities (cascades to their relationships)
        for eid in list(diff.removed_entity_ids):
            if eid not in self.entities:
                continue
            entity = self.entities[eid]
            self.entity_types[entity.entity_type].discard(eid)
            self.entity_names[entity.name].discard(eid)
            for rid in list(self.entity_relationships.get(eid, set())):
                if rid in self.relationships:
                    rel = self.relationships.pop(rid)
                    self.relationship_types[rel.relationship_type].discard(rid)
                    other_eid = rel.target_id if rel.source_id == eid else rel.source_id
                    if other_eid and other_eid != eid:
                        self.entity_relationships[other_eid].discard(rid)
                    self._emit_event(GraphEvent(
                        event_type=GraphEventType.RELATIONSHIP_REMOVED,
                        timestamp=time.time(),
                        relationship_id=rid,
                    ))
            self.entity_relationships.pop(eid, None)
            del self.entities[eid]
            self._emit_event(GraphEvent(
                event_type=GraphEventType.ENTITY_REMOVED,
                timestamp=time.time(),
                entity_id=eid,
            ))

        # 2. Remove standalone relationships
        for rid in list(diff.removed_relationship_ids):
            if rid not in self.relationships:
                continue
            rel = self.relationships.pop(rid)
            self.relationship_types[rel.relationship_type].discard(rid)
            for eid in (rel.source_id, rel.target_id):
                if eid:
                    self.entity_relationships[eid].discard(rid)
            self._emit_event(GraphEvent(
                event_type=GraphEventType.RELATIONSHIP_REMOVED,
                timestamp=time.time(),
                relationship_id=rid,
            ))

        # 3. Add new entities; track old_id → new entity_id mapping
        entity_id_map: Dict[str, str] = {eid: eid for eid in self.entities}
        for e_dict in diff.added_entities:
            new_entity = self.add_entity(Entity.from_dict(e_dict))
            entity_id_map[e_dict.get("entity_id", new_entity.entity_id)] = (
                new_entity.entity_id
            )

        # 4. Apply property modifications
        for mod in diff.modified_entities:
            eid = mod.get("entity_id", "")
            if eid in self.entities:
                self.entities[eid].properties = dict(mod.get("new_properties") or {})
                self._emit_event(GraphEvent(
                    event_type=GraphEventType.ENTITY_MODIFIED,
                    timestamp=time.time(),
                    entity_id=eid,
                    data={"properties": self.entities[eid].properties},
                ))

        # 5. Add new relationships
        for r_dict in diff.added_relationships:
            src_data = r_dict.get("source")
            tgt_data = r_dict.get("target")

            def _resolve(data: Any) -> Optional[Entity]:
                if isinstance(data, dict):
                    mapped = entity_id_map.get(data.get("entity_id", ""), "")
                    if mapped and mapped in self.entities:
                        return self.entities[mapped]
                    # Fallback: match by name + type
                    for e in self.entities.values():
                        if (
                            e.entity_type == data.get("entity_type")
                            and e.name == data.get("name")
                        ):
                            return e
                elif isinstance(data, str):
                    mapped = entity_id_map.get(data, data)
                    return self.entities.get(mapped)
                return None

            src_entity = _resolve(src_data)
            tgt_entity = _resolve(tgt_data)
            if src_entity and tgt_entity:
                self.add_relationship(
                    r_dict.get("relationship_type", "related_to"),
                    source=src_entity,
                    target=tgt_entity,
                    properties=dict(r_dict.get("properties") or {}),
                    confidence=float(r_dict.get("confidence", 1.0)),
                    bidirectional=bool(r_dict.get("bidirectional", False)),
                )


@dataclass
class KnowledgeGraphDiff:
    """Structural difference between two :class:`KnowledgeGraph` instances.

    Produced by :meth:`KnowledgeGraph.diff`; consumed by
    :meth:`KnowledgeGraph.apply_diff`.

    Attributes:
        added_entities: Full entity dicts for entities present in *other* but
            not in *self* (matched by (entity_type, name) fingerprint).
        removed_entity_ids: entity_id values for entities present in *self*
            but not in *other*.
        added_relationships: Full relationship dicts (include_entities=True)
            for relationships present in *other* but not in *self*.
        removed_relationship_ids: relationship_id values for relationships
            present in *self* but not in *other*.
        modified_entities: Per-entity change dicts with keys ``entity_id``,
            ``fingerprint``, ``old_properties``, and ``new_properties``.

    Example:
        ```python
        diff = kg1.diff(kg2)
        print(diff.is_empty)        # True if no change
        print(diff.summary())       # Human-readable summary
        kg1.apply_diff(diff)        # Transform kg1 into kg2
        ```
    """

    added_entities: List[Dict[str, Any]] = field(default_factory=list)
    removed_entity_ids: List[str] = field(default_factory=list)
    added_relationships: List[Dict[str, Any]] = field(default_factory=list)
    removed_relationship_ids: List[str] = field(default_factory=list)
    modified_entities: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """Return True when no additions, removals, or modifications are present."""
        return not (
            self.added_entities
            or self.removed_entity_ids
            or self.added_relationships
            or self.removed_relationship_ids
            or self.modified_entities
        )

    def summary(self) -> str:
        """Return a one-line human-readable summary of this diff.

        Returns:
            str: Summary string, e.g.
                ``"+2 entities, -1 entity, +0 rels, -1 rel, ~3 modified"``.
        """
        return (
            f"+{len(self.added_entities)} entities, "
            f"-{len(self.removed_entity_ids)} entities, "
            f"+{len(self.added_relationships)} rels, "
            f"-{len(self.removed_relationship_ids)} rels, "
            f"~{len(self.modified_entities)} modified"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize this diff to a plain dictionary (JSON-safe).

        Returns:
            Dict: Serializable representation of the diff.
        """
        return {
            "added_entities": self.added_entities,
            "removed_entity_ids": self.removed_entity_ids,
            "added_relationships": self.added_relationships,
            "removed_relationship_ids": self.removed_relationship_ids,
            "modified_entities": self.modified_entities,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'KnowledgeGraphDiff':
        """Reconstruct a :class:`KnowledgeGraphDiff` from a serialized dict.

        Args:
            data (Dict): As produced by :meth:`to_dict`.

        Returns:
            KnowledgeGraphDiff: The reconstructed diff.
        """
        return cls(
            added_entities=list(data.get("added_entities") or []),
            removed_entity_ids=list(data.get("removed_entity_ids") or []),
            added_relationships=list(data.get("added_relationships") or []),
            removed_relationship_ids=list(data.get("removed_relationship_ids") or []),
            modified_entities=list(data.get("modified_entities") or []),
        )
