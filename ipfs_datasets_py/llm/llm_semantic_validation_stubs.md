# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/llm/llm_semantic_validation.py'

Files last updated: 1748635923.4413795

Stub file last updated: 2025-07-07 02:15:51

## SPARQLValidator

```python
class SPARQLValidator:
    """
    Validates knowledge graphs against SPARQL endpoints.

This class provides advanced validation of knowledge graphs against SPARQL
endpoints like Wikidata, enabling verification of extracted knowledge against
established knowledge bases and detection of inconsistencies or missing information.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SchemaRegistry

```python
class SchemaRegistry:
    """
    Registry for maintaining schemas for different domains and tasks.

This class provides a central registry for schemas used in validating
LLM outputs, organized by domain, task, and version.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SchemaValidator

```python
class SchemaValidator:
    """
    Validator for LLM outputs against predefined schemas.

This class validates LLM outputs against JSON schemas, with support for
different validation strategies and domain-specific schema selection.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SemanticAugmenter

```python
class SemanticAugmenter:
    """
    Augments validated data with additional semantic information.

This class enriches validated LLM outputs with domain-specific semantic
information, such as entity linking, relation enhancement, and contextual
information.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SemanticValidator

```python
class SemanticValidator:
    """
    Combines schema validation and semantic augmentation.

This class provides a unified interface for validating LLM outputs against
schemas and augmenting them with semantic information.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ValidationResult

```python
class ValidationResult(Generic[T]):
    """
    Result of a validation operation.

This class represents the result of validating an LLM output against a schema,
including validation status, errors, and the validated/transformed data.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __bool__

```python
def __bool__(self) -> bool:
    """
    Boolean representation (True if valid).
    """
```
* **Async:** False
* **Method:** True
* **Class:** ValidationResult

## __init__

```python
def __init__(self, is_valid: bool, data: Optional[T] = None, errors: Optional[List[str]] = None, warnings: Optional[List[str]] = None):
    """
    Initialize validation result.

Args:
    is_valid: Whether the validation was successful
    data: The validated and potentially transformed data
    errors: List of validation errors
    warnings: List of validation warnings
    """
```
* **Async:** False
* **Method:** True
* **Class:** ValidationResult

## __init__

```python
def __init__(self):
    """
    Initialize schema registry.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SchemaRegistry

## __init__

```python
def __init__(self, registry: Optional[SchemaRegistry] = None, llm_interface: Optional[LLMInterface] = None):
    """
    Initialize schema validator.

Args:
    registry: Schema registry (creates default if None)
    llm_interface: LLM interface for validation assistance (creates mock if None)
    """
```
* **Async:** False
* **Method:** True
* **Class:** SchemaValidator

## __init__

```python
def __init__(self, llm_interface: Optional[LLMInterface] = None, domain_processor: Optional[DomainSpecificProcessor] = None):
    """
    Initialize semantic augmenter.

Args:
    llm_interface: LLM interface for semantic augmentation
    domain_processor: Domain-specific processor for context
    """
```
* **Async:** False
* **Method:** True
* **Class:** SemanticAugmenter

## __init__

```python
def __init__(self, validator: Optional[SchemaValidator] = None, augmenter: Optional[SemanticAugmenter] = None):
    """
    Initialize semantic validator.

Args:
    validator: Schema validator (creates default if None)
    augmenter: Semantic augmenter (creates default if None)
    """
```
* **Async:** False
* **Method:** True
* **Class:** SemanticValidator

## __init__

```python
def __init__(self, endpoint_url: str = "https://query.wikidata.org/sparql", tracer: Optional[WikipediaKnowledgeGraphTracer] = None, llm_interface: Optional[LLMInterface] = None, cache_results: bool = True, cache_ttl: int = 3600):
    """
    Initialize SPARQL validator.

Args:
    endpoint_url: URL of the SPARQL endpoint to query
    tracer: Optional tracer for detailed tracing
    llm_interface: Optional LLM interface for explanation generation
    cache_results: Whether to cache validation results
    cache_ttl: Time-to-live for cached results in seconds
    """
```
* **Async:** False
* **Method:** True
* **Class:** SPARQLValidator

## _assess_uncertainty

```python
def _assess_uncertainty(self, text: str, confidence: float) -> Dict[str, Any]:
    """
    Assess uncertainty in reasoning.

Args:
    text: Reasoning text
    confidence: Confidence score

Returns:
    Uncertainty assessment
    """
```
* **Async:** False
* **Method:** True
* **Class:** SemanticAugmenter

## _augment_cross_document_reasoning

```python
def _augment_cross_document_reasoning(self, data: Dict[str, Any], domain: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Augment cross-document reasoning results.

Args:
    data: Validated data to augment
    domain: Domain for augmentation
    context: Additional context information

Returns:
    Augmented data
    """
```
* **Async:** False
* **Method:** True
* **Class:** SemanticAugmenter

## _augment_evidence_chain

```python
def _augment_evidence_chain(self, data: Dict[str, Any], domain: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Augment evidence chain analysis results.

Args:
    data: Validated data to augment
    domain: Domain for augmentation
    context: Additional context information

Returns:
    Augmented data
    """
```
* **Async:** False
* **Method:** True
* **Class:** SemanticAugmenter

## _check_relationship

```python
def _check_relationship(self, source_id: str, target_id: str, relationship_type: str, bidirectional: bool = False) -> Dict[str, Any]:
    """
    Check if a relationship exists between entities in Wikidata.

Args:
    source_id: Wikidata ID of source entity
    target_id: Wikidata ID of target entity
    relationship_type: Type of relationship to check
    bidirectional: Whether to check in both directions

Returns:
    Dict: Information about the relationship
    """
```
* **Async:** False
* **Method:** True
* **Class:** SPARQLValidator

## _extract_key_concepts

```python
def _extract_key_concepts(self, text: str) -> List[str]:
    """
    Extract key concepts from text.

Args:
    text: Text to extract concepts from

Returns:
    List of key concepts
    """
```
* **Async:** False
* **Method:** True
* **Class:** SemanticAugmenter

## _generate_clinical_relevance

```python
def _generate_clinical_relevance(self, data: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> str:
    """
    Generate clinical relevance for medical domain.

Args:
    data: Result data
    context: Additional context information

Returns:
    Clinical relevance string
    """
```
* **Async:** False
* **Method:** True
* **Class:** SemanticAugmenter

## _generate_legal_implications

```python
def _generate_legal_implications(self, data: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> str:
    """
    Generate legal implications for legal domain.

Args:
    data: Result data
    context: Additional context information

Returns:
    Legal implications string
    """
```
* **Async:** False
* **Method:** True
* **Class:** SemanticAugmenter

## _generate_scholarly_context

```python
def _generate_scholarly_context(self, data: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> str:
    """
    Generate scholarly context for academic domain.

Args:
    data: Result data
    context: Additional context information

Returns:
    Scholarly context string
    """
```
* **Async:** False
* **Method:** True
* **Class:** SemanticAugmenter

## _get_default_schema

```python
def _get_default_schema(self, task: str, version: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Get a default schema for a task.

Args:
    task: Task for the schema
    version: Schema version (latest if None)

Returns:
    The schema or None if not found
    """
```
* **Async:** False
* **Method:** True
* **Class:** SchemaRegistry

## _get_entity_properties

```python
def _get_entity_properties(self, entity_id: str) -> List[Dict[str, Any]]:
    """
    Get properties of a Wikidata entity.

Args:
    entity_id: Wikidata entity ID (Qxxxxx)

Returns:
    List[Dict]: List of entity properties
    """
```
* **Async:** False
* **Method:** True
* **Class:** SPARQLValidator

## _get_wikidata_entity

```python
def _get_wikidata_entity(self, entity_name: str, entity_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Get Wikidata entity by name and optional type.

Args:
    entity_name: Name of the entity
    entity_type: Optional type of the entity for better matching

Returns:
    Dict or None: Wikidata entity data
    """
```
* **Async:** False
* **Method:** True
* **Class:** SPARQLValidator

## _initialize_default_schemas

```python
def _initialize_default_schemas(self) -> None:
    """
    Initialize default schemas for common tasks.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SchemaValidator

## _match_property

```python
def _match_property(self, prop_name: str, prop_value: Any, wikidata_props: List[Dict[str, Any]]) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Match a property against Wikidata properties.

Args:
    prop_name: Property name to match
    prop_value: Property value to match
    wikidata_props: List of Wikidata properties

Returns:
    Tuple[bool, Dict]: (matched, closest_match)
    """
```
* **Async:** False
* **Method:** True
* **Class:** SPARQLValidator

## _string_similarity

```python
def _string_similarity(self, str1: str, str2: str) -> float:
    """
    Calculate string similarity using Jaccard similarity of words.

Args:
    str1: First string
    str2: Second string

Returns:
    float: Similarity score (0-1)
    """
```
* **Async:** False
* **Method:** True
* **Class:** SPARQLValidator

## augment

```python
def augment(self, data: Dict[str, Any], domain: str, task: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Augment data with semantic information.

Args:
    data: Validated data to augment
    domain: Domain for augmentation
    task: Task for augmentation
    context: Additional context information

Returns:
    Augmented data
    """
```
* **Async:** False
* **Method:** True
* **Class:** SemanticAugmenter

## execute_custom_sparql_query

```python
def execute_custom_sparql_query(self, query: str) -> Dict[str, Any]:
    """
    Execute a custom SPARQL query against the endpoint.

Args:
    query: Custom SPARQL query to execute

Returns:
    Dict: Query results
    """
```
* **Async:** False
* **Method:** True
* **Class:** SPARQLValidator

## find_entity_paths

```python
def find_entity_paths(self, source_entity: str, target_entity: str, max_path_length: int = 2) -> ValidationResult:
    """
    Find paths between two entities in Wikidata.

Args:
    source_entity: Source entity name
    target_entity: Target entity name
    max_path_length: Maximum path length (1 or 2)

Returns:
    ValidationResult: Result of the path finding
    """
```
* **Async:** False
* **Method:** True
* **Class:** SPARQLValidator

## find_similar_entities

```python
def find_similar_entities(self, entity_name: str, entity_type: Optional[str] = None, min_similarity: float = 0.5) -> ValidationResult:
    """
    Find similar entities to a given entity in Wikidata.

Args:
    entity_name: Name of the entity to find similar entities for
    entity_type: Optional type of entities to search for
    min_similarity: Minimum similarity score (0.0-1.0)

Returns:
    ValidationResult: Result with similar entities
    """
```
* **Async:** False
* **Method:** True
* **Class:** SPARQLValidator

## generate_validation_explanation

```python
def generate_validation_explanation(self, validation_result: ValidationResult, explanation_type: str = "summary") -> str:
    """
    Generate a human-readable explanation of a validation result.

Args:
    validation_result: Validation result to explain
    explanation_type: Type of explanation to generate

Returns:
    str: Human-readable explanation
    """
```
* **Async:** False
* **Method:** True
* **Class:** SPARQLValidator

## get_schema

```python
def get_schema(self, domain: str, task: str, version: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Get a schema for a domain and task.

Args:
    domain: Domain for the schema
    task: Task for the schema
    version: Schema version (latest if None)

Returns:
    The schema or None if not found
    """
```
* **Async:** False
* **Method:** True
* **Class:** SchemaRegistry

## process

```python
def process(self, data: Any, domain: str, task: str, context: Optional[Dict[str, Any]] = None, auto_repair: bool = True) -> Tuple[bool, Dict[str, Any], List[str]]:
    """
    Process data through validation and augmentation.

Args:
    data: Data to process
    domain: Domain for processing
    task: Task for processing
    context: Additional context information
    auto_repair: Whether to attempt repair of invalid data

Returns:
    Tuple of (success, processed_data, errors)
    """
```
* **Async:** False
* **Method:** True
* **Class:** SemanticValidator

## register_default_schema

```python
def register_default_schema(self, task: str, schema: Dict[str, Any], version: str = "1.0.0") -> None:
    """
    Register a default schema for a task.

Args:
    task: Task for the schema
    schema: JSON schema definition
    version: Schema version
    """
```
* **Async:** False
* **Method:** True
* **Class:** SchemaRegistry

## register_schema

```python
def register_schema(self, domain: str, task: str, schema: Dict[str, Any], version: str = "1.0.0") -> None:
    """
    Register a schema for a domain and task.

Args:
    domain: Domain for the schema (e.g., "academic", "medical")
    task: Task for the schema (e.g., "cross_document_reasoning")
    schema: JSON schema definition
    version: Schema version
    """
```
* **Async:** False
* **Method:** True
* **Class:** SchemaRegistry

## repair_and_validate

```python
async def repair_and_validate(self, data: Any, domain: str, task: str, max_attempts: int = 3) -> ValidationResult:
    """
    Attempt to repair invalid data and validate it.

Args:
    data: Data to validate and potentially repair
    domain: Domain for the schema
    task: Task for the schema
    max_attempts: Maximum number of repair attempts

Returns:
    Validation result with potentially repaired data
    """
```
* **Async:** True
* **Method:** True
* **Class:** SchemaValidator

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert result to dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ValidationResult

## validate

```python
def validate(self, data: Any, domain: str, task: str, version: Optional[str] = None, strict: bool = False) -> ValidationResult:
    """
    Validate data against a schema.

Args:
    data: Data to validate
    domain: Domain for the schema
    task: Task for the schema
    version: Schema version (latest if None)
    strict: Whether to perform strict validation

Returns:
    Validation result
    """
```
* **Async:** False
* **Method:** True
* **Class:** SchemaValidator

## validate_common_properties

```python
def validate_common_properties(self, entity_name: str, entity_type: str, entity_properties: Dict[str, Any]) -> ValidationResult:
    """
    Validate that an entity has the common properties expected for its type.

Args:
    entity_name: Name of the entity
    entity_type: Type of the entity
    entity_properties: Properties of the entity

Returns:
    ValidationResult: Result of the validation
    """
```
* **Async:** False
* **Method:** True
* **Class:** SPARQLValidator

## validate_entity

```python
def validate_entity(self, entity_name: str, entity_type: Optional[str] = None, entity_properties: Optional[Dict[str, Any]] = None) -> ValidationResult:
    """
    Validate a single entity against the SPARQL endpoint.

Args:
    entity_name: Name of the entity to validate
    entity_type: Optional type of the entity
    entity_properties: Optional properties of the entity

Returns:
    ValidationResult: Result of validation
    """
```
* **Async:** False
* **Method:** True
* **Class:** SPARQLValidator

## validate_knowledge_graph

```python
def validate_knowledge_graph(self, kg: Any, main_entity_name: Optional[str] = None, validation_depth: int = 1, min_confidence: float = 0.7) -> ValidationResult:
    """
    Validate an entire knowledge graph against the SPARQL endpoint.

Args:
    kg: Knowledge graph to validate
    main_entity_name: Optional name of the main entity to validate against
    validation_depth: Depth of validation (1 = entity properties, 2 = relationships, 3 = full graph)
    min_confidence: Minimum confidence threshold for validation

Returns:
    ValidationResult: Result of validation
    """
```
* **Async:** False
* **Method:** True
* **Class:** SPARQLValidator

## validate_relationship

```python
def validate_relationship(self, source_entity: str, relationship_type: str, target_entity: str, bidirectional: bool = False) -> ValidationResult:
    """
    Validate a relationship between entities against the SPARQL endpoint.

Args:
    source_entity: Source entity name
    relationship_type: Type of relationship
    target_entity: Target entity name
    bidirectional: Whether the relationship is bidirectional

Returns:
    ValidationResult: Result of validation
    """
```
* **Async:** False
* **Method:** True
* **Class:** SPARQLValidator
