# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/knowledge_graph_extraction.py'

Files last updated: 1751446633.0082855

Stub file last updated: 2025-07-07 02:11:02

## Entity

```python
@dataclass
class Entity:
    """
    Represents an entity in a knowledge graph.

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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## KnowledgeGraph

```python
class KnowledgeGraph:
    """
    A knowledge graph containing entities and relationships.

Provides methods for adding, querying, and manipulating entities
and relationships in the knowledge graph.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## KnowledgeGraphExtractor

```python
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## KnowledgeGraphExtractorWithValidation

```python
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## Relationship

```python
@dataclass
class Relationship:
    """
    Represents a relationship between entities in a knowledge graph.

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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, name: str = None):
    """
    Initialize a new knowledge graph.

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
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraph

## __init__

```python
def __init__(self, use_spacy: bool = False, use_transformers: bool = False, relation_patterns: Optional[List[Dict[str, Any]]] = None, min_confidence: float = 0.5, use_tracer: bool = True):
    """
    Initialize the knowledge graph extractor.

Args:
    use_spacy (bool): Whether to use spaCy for extraction
    use_transformers (bool): Whether to use Transformers for extraction
    relation_patterns (List[Dict], optional): Custom relation extraction patterns
    min_confidence (float): Minimum confidence threshold for extraction
    use_tracer (bool): Whether to use the WikipediaKnowledgeGraphTracer
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraphExtractor

## __init__

```python
def __init__(self, use_spacy: bool = False, use_transformers: bool = False, relation_patterns: Optional[List[Dict[str, Any]]] = None, min_confidence: float = 0.5, use_tracer: bool = True, sparql_endpoint_url: str = "https://query.wikidata.org/sparql", validate_during_extraction: bool = True, auto_correct_suggestions: bool = False, cache_validation_results: bool = True):
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
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraphExtractorWithValidation

## _default_relation_patterns

```python
def _default_relation_patterns() -> List[Dict[str, Any]]:
    """
    Create default relation extraction patterns.

Returns:
    List[Dict]: List of relation patterns
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _find_best_entity_match

```python
def _find_best_entity_match(self, text: str, entity_map: Dict[str, Entity]) -> Optional[Entity]:
    """
    Find the best matching entity for a text.

Args:
    text (str): Text to match
    entity_map (Dict): Map from entity names to Entity objects

Returns:
    Optional[Entity]: Best matching entity, or None if no match
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraphExtractor

## _get_wikidata_id

```python
def _get_wikidata_id(self, entity_name: str) -> Optional[str]:
    """
    Get the Wikidata ID for an entity name.

Args:
    entity_name (str): Name of the entity

Returns:
    str: Wikidata ID (Qxxxxx) or None if not found
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraphExtractor

## _get_wikidata_statements

```python
def _get_wikidata_statements(self, entity_id: str) -> List[Dict[str, Any]]:
    """
    Get structured statements for a Wikidata entity.

Args:
    entity_id (str): Wikidata entity ID (Qxxxxx)

Returns:
    List[Dict]: List of simplified statements
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraphExtractor

## _map_spacy_entity_type

```python
def _map_spacy_entity_type(spacy_type: str) -> str:
    """
    Map spaCy entity types to our entity types.

Args:
    spacy_type (str): spaCy entity type

Returns:
    str: Mapped entity type
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _map_transformers_entity_type

```python
def _map_transformers_entity_type(self, transformers_type: str) -> str:
    """
    Map Transformers entity types to our entity types.

Args:
    transformers_type (str): Transformers entity type

Returns:
    str: Mapped entity type
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _rule_based_entity_extraction

```python
def _rule_based_entity_extraction(text: str) -> List[Entity]:
    """
    Extract entities using rule-based patterns.

Args:
    text (str): Text to extract entities from

Returns:
    List[Entity]: List of extracted entities
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _rule_based_relationship_extraction

```python
def _rule_based_relationship_extraction(self, text: str, entity_map: Dict[str, Entity]) -> List[Relationship]:
    """
    Extract relationships using rule-based patterns.

Args:
    text (str): Text to extract relationships from
    entity_map (Dict): Map from entity names to Entity objects

Returns:
    List[Relationship]: List of extracted relationships
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraphExtractor

## _string_similarity

```python
def _string_similarity(str1: str, str2: str) -> float:
    """
    Calculate similarity between two strings.

Args:
    str1 (str): First string
    str2 (str): Second string

Returns:
    float: Similarity score (0-1)
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## add_entity

```python
def add_entity(self, entity_type: str, name: str, properties: Optional[Dict[str, Any]] = None, entity_id: str = None, confidence: float = 1.0, source_text: str = None) -> Entity:
    """
    Add an entity to the knowledge graph.

Args:
    entity_type (str): Type of the entity
    name (str): Name of the entity
    properties (Dict, optional): Additional properties
    entity_id (str, optional): Unique identifier (generated if None)
    confidence (float): Confidence score
    source_text (str, optional): Source text

Returns:
    Entity: The added entity
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraph

## add_relationship

```python
def add_relationship(self, relationship_type: str, source: Entity, target: Entity, properties: Optional[Dict[str, Any]] = None, relationship_id: str = None, confidence: float = 1.0, source_text: str = None, bidirectional: bool = False) -> Relationship:
    """
    Add a relationship to the knowledge graph.

Args:
    relationship_type (str): Type of the relationship
    source (Entity): Source entity
    target (Entity): Target entity
    properties (Dict, optional): Additional properties
    relationship_id (str, optional): Unique identifier (generated if None)
    confidence (float): Confidence score
    source_text (str, optional): Source text
    bidirectional (bool): Whether the relationship is bidirectional

Returns:
    Relationship: The added relationship
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraph

## apply_validation_corrections

```python
def apply_validation_corrections(self, kg: KnowledgeGraph, corrections: Dict[str, Any]) -> KnowledgeGraph:
    """
    Apply correction suggestions to a knowledge graph.

Args:
    kg: Knowledge graph to correct
    corrections: Correction suggestions from validation

Returns:
    KnowledgeGraph: Corrected knowledge graph
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraphExtractorWithValidation

## dfs

```python
def dfs(current_entity, path, depth):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## enrich_with_types

```python
@staticmethod
def enrich_with_types(kg: KnowledgeGraph) -> KnowledgeGraph:
    """
    Enrich a knowledge graph with inferred entity types.

Args:
    kg (KnowledgeGraph): Knowledge graph to enrich

Returns:
    KnowledgeGraph: Enriched knowledge graph
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraphExtractor

## export_to_rdf

```python
def export_to_rdf(self, format: str = "turtle") -> str:
    """
    Export the knowledge graph to RDF format.

Args:
    format (str): RDF format ("turtle", "xml", "json-ld", "n3")

Returns:
    str: RDF representation of the knowledge graph
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraph

## extract_and_validate_wikipedia_graph

```python
def extract_and_validate_wikipedia_graph(self, page_title: str, extraction_temperature: float = 0.7, structure_temperature: float = 0.5) -> Dict[str, Any]:
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
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraphExtractor

## extract_enhanced_knowledge_graph

```python
def extract_enhanced_knowledge_graph(self, text: str, use_chunking: bool = True, extraction_temperature: float = 0.7, structure_temperature: float = 0.5) -> KnowledgeGraph:
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
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraphExtractor

## extract_entities

```python
def extract_entities(self, text: str) -> List[Entity]:
    """
    Extract entities from text.

Args:
    text (str): Text to extract entities from

Returns:
    List[Entity]: List of extracted entities
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraphExtractor

## extract_from_documents

```python
def extract_from_documents(self, documents: List[Dict[str, str]], text_key: str = "text", extraction_temperature: float = 0.7, structure_temperature: float = 0.5) -> KnowledgeGraph:
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
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraphExtractor

## extract_from_documents

```python
def extract_from_documents(self, documents: List[Dict[str, str]], text_key: str = "text", extraction_temperature: float = 0.7, structure_temperature: float = 0.5, validation_depth: int = 1) -> Dict[str, Any]:
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
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraphExtractorWithValidation

## extract_from_wikipedia

```python
def extract_from_wikipedia(self, page_title: str, extraction_temperature: float = 0.7, structure_temperature: float = 0.5) -> KnowledgeGraph:
    """
    Extract a knowledge graph from a Wikipedia page with tunable parameters.

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
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraphExtractor

## extract_from_wikipedia

```python
def extract_from_wikipedia(self, page_title: str, extraction_temperature: float = 0.7, structure_temperature: float = 0.5, validation_depth: int = 2, focus_validation_on_main_entity: bool = True) -> Dict[str, Any]:
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
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraphExtractorWithValidation

## extract_knowledge_graph

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraphExtractor

## extract_knowledge_graph

```python
def extract_knowledge_graph(self, text: str, extraction_temperature: float = 0.7, structure_temperature: float = 0.5, validation_depth: int = 1) -> Dict[str, Any]:
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
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraphExtractorWithValidation

## extract_relationships

```python
def extract_relationships(self, text: str, entities: List[Entity]) -> List[Relationship]:
    """
    Extract relationships between entities from text.

Args:
    text (str): Text to extract relationships from
    entities (List[Entity]): List of entities to consider

Returns:
    List[Relationship]: List of extracted relationships
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraphExtractor

## find_paths

```python
def find_paths(self, source: Entity, target: Entity, max_depth: int = 3, relationship_types: Optional[List[str]] = None) -> List[List[Tuple[Entity, Relationship, Entity]]]:
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
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraph

## from_dict

```python
@classmethod
def from_dict(cls, data: Dict[str, Any]) -> "Entity":
    """
    Create an entity from a dictionary representation.

Args:
    data (Dict): Dictionary representation of the entity

Returns:
    Entity: The created entity
    """
```
* **Async:** False
* **Method:** True
* **Class:** Entity

## from_dict

```python
@classmethod
def from_dict(cls, data: Dict[str, Any], entity_map: Dict[str, Entity] = None) -> "Relationship":
    """
    Create a relationship from a dictionary representation.

Args:
    data (Dict): Dictionary representation of the relationship
    entity_map (Dict, optional): Map from entity IDs to Entity objects

Returns:
    Relationship: The created relationship
    """
```
* **Async:** False
* **Method:** True
* **Class:** Relationship

## from_dict

```python
@classmethod
def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeGraph":
    """
    Create a knowledge graph from a dictionary representation.

Args:
    data (Dict): Dictionary representation of the knowledge graph

Returns:
    KnowledgeGraph: The created knowledge graph
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraph

## from_json

```python
@classmethod
def from_json(cls, json_str: str) -> "KnowledgeGraph":
    """
    Create a knowledge graph from a JSON string.

Args:
    json_str (str): JSON representation of the knowledge graph

Returns:
    KnowledgeGraph: The created knowledge graph
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraph

## get_entities_by_name

```python
def get_entities_by_name(self, name: str) -> List[Entity]:
    """
    Get all entities with a specific name.

Args:
    name (str): Entity name

Returns:
    List[Entity]: List of entities with the specified name
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraph

## get_entities_by_type

```python
def get_entities_by_type(self, entity_type: str) -> List[Entity]:
    """
    Get all entities of a specific type.

Args:
    entity_type (str): Entity type

Returns:
    List[Entity]: List of entities of the specified type
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraph

## get_entity_by_id

```python
def get_entity_by_id(self, entity_id: str) -> Optional[Entity]:
    """
    Get an entity by its ID.

Args:
    entity_id (str): Entity ID

Returns:
    Optional[Entity]: The entity, or None if not found
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraph

## get_relationship_by_id

```python
def get_relationship_by_id(self, relationship_id: str) -> Optional[Relationship]:
    """
    Get a relationship by its ID.

Args:
    relationship_id (str): Relationship ID

Returns:
    Optional[Relationship]: The relationship, or None if not found
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraph

## get_relationships_between

```python
def get_relationships_between(self, source: Entity, target: Entity) -> List[Relationship]:
    """
    Get all relationships between two entities.

Args:
    source (Entity): Source entity
    target (Entity): Target entity

Returns:
    List[Relationship]: List of relationships between the entities
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraph

## get_relationships_by_entity

```python
def get_relationships_by_entity(self, entity: Entity) -> List[Relationship]:
    """
    Get all relationships involving a specific entity.

Args:
    entity (Entity): The entity

Returns:
    List[Relationship]: List of relationships involving the entity
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraph

## get_relationships_by_type

```python
def get_relationships_by_type(self, relationship_type: str) -> List[Relationship]:
    """
    Get all relationships of a specific type.

Args:
    relationship_type (str): Relationship type

Returns:
    List[Relationship]: List of relationships of the specified type
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraph

## merge

```python
def merge(self, other: "KnowledgeGraph") -> "KnowledgeGraph":
    """
    Merge another knowledge graph into this one.

Args:
    other (KnowledgeGraph): The knowledge graph to merge

Returns:
    KnowledgeGraph: Self, after merging
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraph

## query_by_properties

```python
def query_by_properties(self, entity_type: Optional[str] = None, properties: Optional[Dict[str, Any]] = None) -> List[Entity]:
    """
    Query entities by type and properties.

Args:
    entity_type (str, optional): Entity type to filter by
    properties (Dict, optional): Properties to filter by

Returns:
    List[Entity]: List of matching entities
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraph

## source_id

```python
@property
def source_id(self) -> Optional[str]:
    """
    Get the ID of the source entity.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Relationship

## target_id

```python
@property
def target_id(self) -> Optional[str]:
    """
    Get the ID of the target entity.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Relationship

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert the entity to a dictionary representation.

Returns:
    Dict: Dictionary representation of the entity
    """
```
* **Async:** False
* **Method:** True
* **Class:** Entity

## to_dict

```python
def to_dict(self, include_entities: bool = True) -> Dict[str, Any]:
    """
    Convert the relationship to a dictionary representation.

Args:
    include_entities (bool): Whether to include full entity details

Returns:
    Dict: Dictionary representation of the relationship
    """
```
* **Async:** False
* **Method:** True
* **Class:** Relationship

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert the knowledge graph to a dictionary representation.

Returns:
    Dict: Dictionary representation of the knowledge graph
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraph

## to_json

```python
def to_json(self, indent: int = 2) -> str:
    """
    Convert the knowledge graph to a JSON string.

Args:
    indent (int): Indentation level for JSON formatting

Returns:
    str: JSON representation of the knowledge graph
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraph

## validate_against_wikidata

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraphExtractor
