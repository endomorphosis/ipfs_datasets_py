# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/ipld/knowledge_graph.py'

Files last updated: 1748635923.4313796

Stub file last updated: 2025-07-07 02:17:30

## Entity

```python
class Entity:
    """
    Represents an entity in a knowledge graph.

Entities are nodes in the knowledge graph with a type, name,
and optional properties.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## IPLDKnowledgeGraph

```python
class IPLDKnowledgeGraph:
    """
    Knowledge graph using IPLD for storage.

This class provides a knowledge graph implementation that uses IPLD for
content-addressed storage of entities and relationships. It supports graph
traversal, vector-augmented queries, and cross-document reasoning.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## Relationship

```python
class Relationship:
    """
    Represents a relationship between entities in a knowledge graph.

Relationships are edges in the knowledge graph connecting entities
with a specific relationship type and optional properties.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, entity_id: EntityID = None, entity_type: str = "entity", name: str = "", properties: Optional[Dict[str, Any]] = None, confidence: float = 1.0, source_text: str = None):
    """
    Initialize an entity.

Args:
    entity_id: Optional ID for the entity (auto-generated if None)
    entity_type: Type of the entity
    name: Name of the entity
    properties: Optional properties for the entity
    confidence: Confidence score for the entity (0.0 to 1.0)
    source_text: Optional source text from which the entity was extracted
    """
```
* **Async:** False
* **Method:** True
* **Class:** Entity

## __init__

```python
def __init__(self, relationship_id: RelationshipID = None, relationship_type: str = "related_to", source: Union[Entity, EntityID] = None, target: Union[Entity, EntityID] = None, properties: Optional[Dict[str, Any]] = None, confidence: float = 1.0, source_text: str = None):
    """
    Initialize a relationship.

Args:
    relationship_id: Optional ID for the relationship (auto-generated if None)
    relationship_type: Type of the relationship
    source: Source entity or entity ID
    target: Target entity or entity ID
    properties: Optional properties for the relationship
    confidence: Confidence score for the relationship (0.0 to 1.0)
    source_text: Optional source text from which the relationship was extracted
    """
```
* **Async:** False
* **Method:** True
* **Class:** Relationship

## __init__

```python
def __init__(self, name: str = "knowledge_graph", storage: Optional[IPLDStorage] = None, vector_store: Optional[IPLDVectorStore] = None):
    """
    Initialize knowledge graph.

Args:
    name: Name of the knowledge graph
    storage: Optional IPLD storage to use
    vector_store: Optional vector store for vector-augmented queries
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDKnowledgeGraph

## __str__

```python
def __str__(self) -> str:
    """
    Get string representation of the entity.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Entity

## __str__

```python
def __str__(self) -> str:
    """
    Get string representation of the relationship.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Relationship

## __str__

```python
def __str__(self) -> str:
    """
    Get string representation of the knowledge graph.
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDKnowledgeGraph

## _get_connected_entities

```python
def _get_connected_entities(self, entity_id: EntityID, max_hops: int = 1, relationship_types: Optional[List[str]] = None) -> Set[EntityID]:
    """
    Get entities connected to the given entity.

Args:
    entity_id: ID of the entity
    max_hops: Maximum number of hops
    relationship_types: Optional list of relationship types to filter by

Returns:
    Set of entity IDs connected to the given entity
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDKnowledgeGraph

## _store_entity

```python
def _store_entity(self, entity: Entity) -> str:
    """
    Store entity in IPLD.

Args:
    entity: Entity to store

Returns:
    CID of the stored entity
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDKnowledgeGraph

## _store_relationship

```python
def _store_relationship(self, relationship: Relationship) -> str:
    """
    Store relationship in IPLD.

Args:
    relationship: Relationship to store

Returns:
    CID of the stored relationship
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDKnowledgeGraph

## _update_root_cid

```python
def _update_root_cid(self):
    """
    Update the root CID of the knowledge graph.
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDKnowledgeGraph

## add_entity

```python
def add_entity(self, entity_type: str = "entity", name: str = "", entity_id: Optional[EntityID] = None, properties: Optional[Dict[str, Any]] = None, confidence: float = 1.0, source_text: str = None, vector: Optional[np.ndarray] = None) -> Entity:
    """
    Add entity node to graph.

Args:
    entity_type: Type of the entity
    name: Name of the entity
    entity_id: Optional ID for the entity (auto-generated if None)
    properties: Optional properties for the entity
    confidence: Confidence score for the entity (0.0 to 1.0)
    source_text: Optional source text from which the entity was extracted
    vector: Optional embedding vector for the entity

Returns:
    Entity object that was added
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDKnowledgeGraph

## add_relationship

```python
def add_relationship(self, relationship_type: str, source: Union[Entity, EntityID], target: Union[Entity, EntityID], properties: Optional[Dict[str, Any]] = None, confidence: float = 1.0, source_text: str = None, relationship_id: Optional[RelationshipID] = None) -> Relationship:
    """
    Add relationship between entities.

Args:
    relationship_type: Type of the relationship
    source: Source entity or entity ID
    target: Target entity or entity ID
    properties: Optional properties for the relationship
    confidence: Confidence score for the relationship (0.0 to 1.0)
    source_text: Optional source text from which the relationship was extracted
    relationship_id: Optional ID for the relationship (auto-generated if None)

Returns:
    Relationship object that was added
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDKnowledgeGraph

## cross_document_reasoning

```python
def cross_document_reasoning(self, query: str, query_vector: np.ndarray, document_node_types: List[str] = ['document', 'paper'], max_hops: int = 2, min_relevance: float = 0.6, max_documents: int = 5, reasoning_depth: str = "moderate") -> Dict[str, Any]:
    """
    Reason across multiple documents using entity-mediated connections.

This method goes beyond simple document retrieval by connecting information
across multiple documents, identifying complementary or contradictory information,
and generating synthesized answers with confidence scores.

Args:
    query: Natural language query to reason about
    query_vector: Query embedding vector
    document_node_types: Types of nodes representing documents
    max_hops: Maximum number of hops between documents
    min_relevance: Minimum relevance score for documents
    max_documents: Maximum number of documents to reason across
    reasoning_depth: Reasoning depth ('basic', 'moderate', or 'deep')

Returns:
    Dict with the following keys:
    - answer: Synthesized answer to the query
    - documents: Relevant documents used
    - evidence_paths: Paths connecting information
    - confidence: Confidence score for the answer
    - reasoning_trace: Step-by-step reasoning process
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDKnowledgeGraph

## entity_count

```python
@property
def entity_count(self) -> int:
    """
    Get the number of entities in the graph.
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDKnowledgeGraph

## export_to_car

```python
def export_to_car(self, output_path: str) -> str:
    """
    Export knowledge graph to CAR file.

Args:
    output_path: Path to output CAR file

Returns:
    Root CID of the exported graph
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDKnowledgeGraph

## from_car

```python
@classmethod
def from_car(cls, car_path: str, storage: Optional[IPLDStorage] = None, vector_store: Optional[IPLDVectorStore] = None) -> "IPLDKnowledgeGraph":
    """
    Load knowledge graph from CAR file.

Args:
    car_path: Path to CAR file
    storage: Optional IPLD storage to use
    vector_store: Optional vector store to use

Returns:
    Loaded knowledge graph
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDKnowledgeGraph

## from_cid

```python
@classmethod
def from_cid(cls, cid: str, storage: Optional[IPLDStorage] = None, vector_store: Optional[IPLDVectorStore] = None) -> "IPLDKnowledgeGraph":
    """
    Load knowledge graph from IPFS by CID.

Args:
    cid: Root CID of the knowledge graph
    storage: Optional IPLD storage to use
    vector_store: Optional vector store to use

Returns:
    Loaded knowledge graph
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDKnowledgeGraph

## from_dict

```python
@classmethod
def from_dict(cls, data: Dict[str, Any]) -> "Entity":
    """
    Create entity from dictionary representation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Entity

## from_dict

```python
@classmethod
def from_dict(cls, data: Dict[str, Any]) -> "Relationship":
    """
    Create relationship from dictionary representation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Relationship

## get_entities_by_type

```python
def get_entities_by_type(self, entity_type: str) -> List[Entity]:
    """
    Get entities by type.

Args:
    entity_type: Type of entities to retrieve

Returns:
    List of entities of the specified type
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDKnowledgeGraph

## get_entities_by_vector_ids

```python
def get_entities_by_vector_ids(self, vector_ids: List[str]) -> List[Entity]:
    """
    Get entities that reference the given vector IDs.

Args:
    vector_ids: List of vector IDs (CIDs)

Returns:
    List of entities referencing these vectors
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDKnowledgeGraph

## get_entity

```python
def get_entity(self, entity_id: EntityID) -> Optional[Entity]:
    """
    Get entity by ID.

Args:
    entity_id: ID of the entity

Returns:
    Entity if found, None otherwise
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDKnowledgeGraph

## get_entity_relationships

```python
def get_entity_relationships(self, entity_id: EntityID, direction: str = "both", relationship_types: Optional[List[str]] = None) -> List[Relationship]:
    """
    Get relationships for an entity.

Args:
    entity_id: ID of the entity
    direction: Direction of relationships ('outgoing', 'incoming', or 'both')
    relationship_types: Optional list of relationship types to filter by

Returns:
    List of relationships for the entity
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDKnowledgeGraph

## get_relationship

```python
def get_relationship(self, relationship_id: RelationshipID) -> Optional[Relationship]:
    """
    Get relationship by ID.

Args:
    relationship_id: ID of the relationship

Returns:
    Relationship if found, None otherwise
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDKnowledgeGraph

## get_relationships_by_type

```python
def get_relationships_by_type(self, relationship_type: str) -> List[Relationship]:
    """
    Get relationships by type.

Args:
    relationship_type: Type of relationships to retrieve

Returns:
    List of relationships of the specified type
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDKnowledgeGraph

## query

```python
def query(self, start_entity: Union[Entity, EntityID], relationship_path: List[str], max_results: int = 100, min_confidence: float = 0.0) -> List[Dict[str, Any]]:
    """
    Query graph following relationship paths.

Args:
    start_entity: Starting entity or entity ID
    relationship_path: Path of relationship types to follow
    max_results: Maximum number of results to return
    min_confidence: Minimum confidence score for entities and relationships

Returns:
    List of matching entities and relationships
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDKnowledgeGraph

## relationship_count

```python
@property
def relationship_count(self) -> int:
    """
    Get the number of relationships in the graph.
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDKnowledgeGraph

## slugify

```python
def slugify(text):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert entity to dictionary representation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Entity

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert relationship to dictionary representation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Relationship

## traverse_from_entities

```python
def traverse_from_entities(self, entities: List[Union[Entity, EntityID]], relationship_types: Optional[List[str]] = None, max_depth: int = 2) -> List[Entity]:
    """
    Traverse graph from seed entities.

Args:
    entities: List of starting entities or entity IDs
    relationship_types: Optional list of relationship types to follow
    max_depth: Maximum traversal depth

Returns:
    List of entities reached through traversal
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDKnowledgeGraph

## vector_augmented_query

```python
def vector_augmented_query(self, query_vector: np.ndarray, relationship_constraints: Optional[List[Dict[str, Any]]] = None, top_k: int = 10, max_hops: int = 2, min_confidence: float = 0.0) -> List[Dict[str, Any]]:
    """
    GraphRAG query combining vector similarity and graph traversal.

Args:
    query_vector: Query vector for similarity search
    relationship_constraints: Optional constraints on traversal
    top_k: Number of results to return
    max_hops: Maximum number of hops from seed nodes
    min_confidence: Minimum confidence score for entities and relationships

Returns:
    List of ranked results with entity and relationship data
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDKnowledgeGraph
