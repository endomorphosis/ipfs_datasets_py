# Optimizers API Reference (Auto-generated)

This file is generated from type hints and docstrings.
Do not edit manually; update source code/docstrings and regenerate.

## ipfs_datasets_py/optimizers/common/base_optimizer.py

Base optimizer class for all optimizer types.

### Classes

#### `OptimizationStrategy`

Strategy for optimization.

#### `OptimizerConfig`

Configuration for optimizer.

#### `OptimizationContext`

Context for optimization session.

#### `BaseOptimizer`

Base class for all optimizer types.

Methods:
- `generate(input_data: Any, context: OptimizationContext) -> Any`
  - Generate initial artifact from input data.
- `critique(artifact: Any, context: OptimizationContext) -> Tuple[float, List[str]]`
  - Evaluate quality of artifact.
- `optimize(artifact: Any, score: float, feedback: List[str], context: OptimizationContext) -> Any`
  - Improve artifact based on critique feedback.
- `validate(artifact: Any, context: OptimizationContext) -> bool`
  - Validate that artifact meets requirements.
- `run_session(input_data: Any, context: OptimizationContext) -> OptimizerResult`
  - Run complete optimization session.
- `get_capabilities() -> Dict[str, Any]`
  - Get optimizer capabilities.
- `dry_run(input_data: Any, context: OptimizationContext) -> OptimizerResult`
  - Validate optimization setup without full optimization.
- `state_checksum() -> str`
  - Compute a checksum of the optimizer's current configuration state.

## ipfs_datasets_py/optimizers/graphrag/ontology_generator.py

Ontology Generator for GraphRAG Optimization.

### Classes

#### `ExtractionStrategy`

Ontology extraction strategies.

#### `DataType`

Supported data types for ontology generation.

#### `ExtractionConfig`

Typed configuration for the extraction pipeline.

Methods:
- `to_dict() -> Dict[str, Any]`
  - Return a plain-dict representation (legacy compatibility).
- `from_dict(d: Dict[str, Any]) -> 'ExtractionConfig'`
  - Construct from a plain dict (backwards-compat with old callers).
- `from_env(prefix: str = 'EXTRACTION_') -> 'ExtractionConfig'`
  - Construct an :class:`ExtractionConfig` from environment variables.
- `validate() -> None`
  - Validate field values; raise :class:`ValueError` on invalid combinations.
- `merge(other: 'ExtractionConfig') -> 'ExtractionConfig'`
  - Merge *other* into this config; *other* values take precedence on conflict.
- `to_yaml() -> str`
  - Serialise this config to a YAML string.
- `to_json() -> str`
  - Serialise this config to a JSON string.
- `to_json_pretty(indent: int = 2) -> str`
  - Serialise this config to a formatted JSON string.
- `from_json(json_str: str) -> 'ExtractionConfig'`
  - Deserialise an :class:`ExtractionConfig` from a JSON string.
- `from_yaml(yaml_str: str) -> 'ExtractionConfig'`
  - Deserialise an :class:`ExtractionConfig` from a YAML string.
- `diff(other: 'ExtractionConfig') -> Dict[str, Any]`
  - Return a mapping of fields that differ between ``self`` and *other*.
- `to_toml() -> str`
  - Serialise this config to a TOML string.
- `from_toml(toml_str: str) -> 'ExtractionConfig'`
  - Construct an :class:`ExtractionConfig` from a TOML string.
- `to_json() -> str`
  - Serialise this config to a JSON string.
- `copy() -> 'ExtractionConfig'`
  - Return a shallow copy of this config.
- `clone() -> 'ExtractionConfig'`
  - Return a deep copy of this config.
- `scale_thresholds(factor: float) -> 'ExtractionConfig'`
  - Return a new config with confidence-related thresholds scaled by *factor*.
- `apply_defaults_for_domain(domain: str) -> None`
  - Mutate this config in-place with sensible defaults for *domain*.
- `is_strict() -> bool`
  - Return ``True`` if this config uses a strict confidence threshold (>= 0.8).
- `summary() -> str`
  - Return a one-line human-readable description of this config.
- `with_threshold(threshold: float) -> 'ExtractionConfig'`
  - Return a copy of this config with *threshold* as the confidence threshold.
- `is_default() -> bool`
  - Return ``True`` if this config has all default field values.
- `merge(other: 'ExtractionConfig') -> 'ExtractionConfig'`
  - Return a new config merging *self* with *other*, *other* taking priority.
- `relaxed(delta: float = 0.1) -> 'ExtractionConfig'`
  - Return a copy of this config with ``confidence_threshold`` decreased by *delta*.
- `tightened(delta: float = 0.1) -> 'ExtractionConfig'`
  - Return a copy of this config with ``confidence_threshold`` increased by *delta*.
- `describe() -> str`
  - Return a human-readable one-line summary of this config.
- `threshold_distance(other: 'ExtractionConfig') -> float`
  - Return the absolute difference between this and *other*'s thresholds.
- `is_stricter_than(other: 'ExtractionConfig') -> bool`
  - Return ``True`` if this config has a higher confidence threshold.
- `is_looser_than(other: 'ExtractionConfig') -> bool`
  - Return ``True`` if this config has a lower confidence threshold.
- `combined_score() -> float`
  - Return a composite score combining ``confidence_threshold`` and
- `similarity_to(other: 'ExtractionConfig') -> float`
  - Return a similarity score between this config and *other* in [0.0, 1.0].
- `describe() -> str`
  - Return a human-readable one-line summary of this configuration.
- `for_domain(domain: str) -> 'ExtractionConfig'`
  - Create a domain-optimized :class:`ExtractionConfig` based on benchmarked recommendations.

#### `OntologyGenerationContext`

Context information for ontology generation.

Methods:
- `extraction_config() -> ExtractionConfig`
  - Typed alias for :attr:`config`.
- `to_unified_context(session_id: str = 'graphrag-session') -> Any`
  - Convert this context to a shared ``GraphRAGContext`` representation.

#### `Entity`

Represents an extracted entity.

Methods:
- `to_dict() -> Dict[str, Any]`
  - Serialise this entity to a plain dictionary.
- `from_dict(d: Dict[str, Any]) -> 'Entity'`
  - Reconstruct an :class:`Entity` from a plain dictionary.
- `to_json(**kwargs: Any) -> str`
  - Serialise this entity to a JSON string.
- `copy_with(**overrides: Any) -> 'Entity'`
  - Return a modified copy of this entity.
- `to_text() -> str`
  - Return a compact human-readable summary of this entity.
- `apply_confidence_decay(current_time: Optional[float] = None, half_life_days: float = 30.0, min_confidence: float = 0.1) -> 'Entity'`
  - Apply time-based confidence decay to this entity.

#### `Relationship`

Represents a relationship between entities.

Methods:
- `to_dict() -> Dict[str, Any]`
  - Serialise this relationship to a plain dictionary.
- `from_dict(d: Dict[str, Any]) -> 'Relationship'`
  - Reconstruct a :class:`Relationship` from a plain dictionary.
- `to_json(**kwargs: Any) -> str`
  - Serialise this relationship to a JSON string.

#### `EntityExtractionResult`

Result of entity extraction from data.

Methods:
- `to_dataframe() -> Any`
  - Convert extracted entities to a :class:`pandas.DataFrame`.
- `to_json() -> str`
  - Serialise the full extraction result to a JSON string.
- `filter_by_type(entity_type: str) -> 'EntityExtractionResult'`
  - Return a new result containing only entities matching *entity_type*.
- `filter_by_confidence(threshold: float = 0.5) -> 'EntityExtractionResult'`
  - Return a new result containing only entities above a confidence threshold.
- `merge(other: 'EntityExtractionResult') -> 'EntityExtractionResult'`
  - Merge *other* into this result, deduplicating by normalised entity text.
- `apply_semantic_dedup(semantic_deduplicator, threshold: float = 0.85, max_suggestions: Optional[int] = None) -> 'EntityExtractionResult'`
  - Apply semantic deduplication to merge similar entities.
- `to_csv() -> str`
  - Return a flat CSV representation of the extracted entities.
- `summary() -> str`
  - Return a concise human-readable summary of this extraction result.
- `confidence_histogram(bins: int = 10) -> List[int]`
  - Return a frequency histogram of entity confidence scores.
- `to_dict() -> Dict[str, Any]`
  - Return a plain-dict representation of this result.
- `validate() -> List[str]`
  - Validate basic structural invariants of this extraction result.
- `entity_type_counts() -> Dict[str, int]`
  - Return a frequency count of entity types in this result.
- `highest_confidence_entity() -> Optional['Entity']`
  - Return the entity with the highest confidence score.
- `filter_by_span(start: int, end: int) -> 'EntityExtractionResult'`
  - Return a copy with only entities whose ``source_span`` overlaps [start, end).
- `random_sample(n: int) -> 'EntityExtractionResult'`
  - Return a new result containing *n* randomly selected entities.
- `span_coverage(text_length: int) -> float`
  - Compute the fraction of source text characters covered by entity spans.
- `unique_types() -> List[str]`
  - Return a sorted list of distinct entity type strings in this result.
- `avg_confidence() -> float`
  - Return the mean confidence across all entities.
- `by_id(eid: str) -> Optional['Entity']`
  - Look up an entity by its id string.
- `has_entity(text: str, case_sensitive: bool = False) -> bool`
  - Return ``True`` if any entity in this result matches *text*.
- `filter_by_type(etype: str, case_sensitive: bool = False) -> 'EntityExtractionResult'`
  - Return a new result keeping only entities whose ``type`` matches *etype*.
- `relationships_for(entity_id: str) -> List['Relationship']`
  - Return all relationships that involve *entity_id* as source or target.
- `merge(other: 'EntityExtractionResult') -> 'EntityExtractionResult'`
  - Return a new result combining entities and relationships from both results.
- `entity_texts() -> List[str]`
  - Return the ``text`` value of every entity in this result.
- `confidence_histogram(bins: int = 10) -> List[int]`
  - Return a histogram of entity confidence values bucketed into *bins*.
- `sample_entities(n: int) -> List['Entity']`
  - Return up to *n* randomly sampled entities from this result.
- `entity_by_id(eid: str) -> Optional['Entity']`
  - Return the first entity with the given ``id``, or ``None``.
- `average_confidence() -> float`
  - Return the mean confidence across all entities.
- `distinct_types() -> List[str]`
  - Return a sorted list of unique entity type strings.
- `high_confidence_entities(threshold: float = 0.8) -> List['Entity']`
  - Return entities with confidence >= *threshold*.
- `low_confidence_entities(threshold: float = 0.5) -> List['Entity']`
  - Return entities with confidence < *threshold*.
- `max_confidence() -> float`
  - Return the highest confidence value among all entities.
- `min_confidence() -> float`
  - Return the lowest confidence value among all entities.
- `confidence_band(low: float = 0.0, high: float = 1.0) -> List['Entity']`
  - Return entities with confidence in [*low*, *high*] (inclusive on both ends).
- `relationship_types() -> List[str]`
  - Return a sorted list of unique relationship type strings.
- `is_empty() -> bool`
  - Return ``True`` if there are no entities AND no relationships.
- `has_relationships() -> bool`
  - Return ``True`` if the result contains at least one relationship.
- `entities_of_type(etype: str, case_sensitive: bool = False) -> List['Entity']`
  - Return entities matching the given type string.
- `confidence_stats() -> Dict[str, float]`
  - Return descriptive statistics for entity confidences in this result.
- `top_entities(n: int = 10) -> List['Entity']`
  - Return the top *n* entities by confidence in descending order.
- `top_confidence_entity() -> Optional['Entity']`
  - Return the entity with the highest confidence score.
- `entities_with_properties() -> List['Entity']`
  - Return entities that have at least one entry in their ``properties`` dict.
- `entity_ids() -> List[str]`
  - Return a list of all entity id strings in this result.
- `relationship_ids() -> List[str]`
  - Return a list of all relationship id strings in this result.
- `extraction_statistics() -> Dict[str, Any]`
  - Return comprehensive extraction statistics.
- `relationship_coherence_issues() -> Dict[str, Any]`
  - Analyze relationship coherence and identify quality issues.
- `get_entity_by_id(entity_id: str) -> Optional['Entity']`
  - Get a specific entity by its ID.
- `get_relationship_by_id(rel_id: str) -> Optional['Relationship']`
  - Get a specific relationship by its ID.
- `relationships_for_entity(entity_id: str) -> List['Relationship']`
  - Get all relationships where entity is source or target.
- `entities_by_confidence_range(min_conf: float = 0.0, max_conf: float = 1.0) -> List['Entity']`
  - Get entities within a confidence range.
- `low_confidence_entities(threshold: float = 0.5) -> List['Entity']`
  - Get all entities below confidence threshold.
- `high_confidence_entities(threshold: float = 0.8) -> List['Entity']`
  - Get all entities above confidence threshold.
- `relationships_by_type(rel_type: str) -> List['Relationship']`
  - Get all relationships of a specific type.
- `relationship_count_by_type() -> Dict[str, int]`
  - Get count of relationships grouped by type.
- `entity_count() -> int`
  - Return the number of entities in this result.
- `relationship_count() -> int`
  - Return the number of relationships in this result.
- `from_dict(data: Dict[str, Any]) -> 'EntityExtractionResult'`
  - Deserialize an EntityExtractionResult from a plain dict.

#### `OntologyGenerationResult`

Rich result wrapper for a single ontology generation run.

Methods:
- `from_ontology(ontology: Dict[str, Any], extraction_strategy: str, domain: str, metadata: Optional[Dict[str, Any]]) -> 'OntologyGenerationResult'`
  - Construct from a raw ontology dict, computing summary stats.

#### `OntologyGenerator`

Generate knowledge graph ontologies from arbitrary data.

Methods:
- `extract_entities(data: Any, context: OntologyGenerationContext) -> EntityExtractionResult`
  - Extract entities from data using configured strategy.
- `infer_relationships(entities: List[Entity], context: OntologyGenerationContext, data: Optional[Any] = None) -> List[Relationship]`
  - Infer relationships between extracted entities.
- `extract_entities_from_file(filepath: str, context: 'OntologyGenerationContext', encoding: str = 'utf-8') -> 'EntityExtractionResult'`
  - Convenience wrapper: read *filepath* and call :meth:`extract_entities`.
- `batch_extract(docs: List[Any], context: 'OntologyGenerationContext', max_workers: int = 4) -> List['EntityExtractionResult']`
  - Extract entities from multiple documents in parallel.
- `extract_entities_streaming(data: Any, context: 'OntologyGenerationContext') -> Any`
  - Yield entity extraction results one entity at a time (iterator API).
- `extract_entities_with_spans(data: str, context: 'OntologyGenerationContext') -> 'EntityExtractionResult'`
  - Extract entities and annotate each with character-offset source spans.
- `extract_with_coref(data: str, context: 'OntologyGenerationContext') -> 'EntityExtractionResult'`
  - Extract entities after a lightweight co-reference resolution pre-pass.
- `extract_with_context_windows(data: str, context: 'OntologyGenerationContext', window_size: int = 512, window_overlap: int = 64, dedup_method: str = 'highest_confidence') -> 'EntityExtractionResult'`
  - Extract entities from large texts using sliding context windows.
- `merge_provenance_report(results: List['EntityExtractionResult'], doc_labels: Optional[List[str]] = None) -> List[Dict[str, Any]]`
  - Build a provenance report mapping each entity to its source document.
- `deduplicate_entities(result: 'EntityExtractionResult') -> 'EntityExtractionResult'`
  - Merge entities with identical normalised text into a single entity.
- `filter_entities(result: 'EntityExtractionResult', min_confidence: float, allowed_types: Optional[List[str]], text_contains: Optional[str]) -> 'EntityExtractionResult'`
  - Post-extraction filter: keep only entities matching all criteria.
- `filter_by_confidence(result: 'EntityExtractionResult', threshold: float = 0.5) -> Dict[str, Any]`
  - Filter extraction result by confidence threshold with detailed stats.
- `generate_ontology(data: Any, context: OntologyGenerationContext) -> Ontology`
  - Generate complete ontology from data.
- `generate_ontology_rich(data: Any, context: OntologyGenerationContext) -> 'OntologyGenerationResult'`
  - Generate ontology and return a rich result with summary statistics.
- `generate_with_feedback(data: Any, context: OntologyGenerationContext, feedback: Optional[Dict[str, Any]] = None, critic: Optional['OntologyCritic'] = None) -> Dict[str, Any]`
  - Generate ontology with iterative feedback incorporation.
- `generate_merge_provenance_report(ontology: Dict[str, Any]) -> Dict[str, Any]`
  - Generate a detailed provenance report for a merged ontology.
- `generate_synthetic_ontology(domain: str, n_entities: int = 5) -> Dict[str, Any]`
  - Produce a sample ontology for a given *domain* without any input text.
- `deduplicate_entities(result: 'EntityExtractionResult', key: str = 'text') -> 'EntityExtractionResult'`
  - Return a new :class:`EntityExtractionResult` with duplicate entities removed.
- `anonymize_entities(result: 'EntityExtractionResult', replacement: str = '[REDACTED]') -> 'EntityExtractionResult'`
  - Return a new result with entity text replaced by *replacement*.
- `tag_entities(result: 'EntityExtractionResult', tags: Dict[str, Any]) -> 'EntityExtractionResult'`
  - Return a new result with *tags* merged into every entity's properties.
- `score_entity(entity: 'Entity') -> float`
  - Return a single-entity confidence heuristic score (0.0 – 1.0).
- `batch_extract_with_spans(documents: List[str], context: 'OntologyGenerationContext', max_workers: int = 4) -> List['EntityExtractionResult']`
  - Extract entities with character spans from multiple documents.
- `extract_keyphrases(text: str, top_k: int = 10) -> List[str]`
  - Extract the top-*k* keyphrases from *text*.
- `extract_noun_phrases(text: str) -> List[str]`
  - Extract simple noun phrases from *text* using a rule-based chunker.
- `merge_results(results: List['EntityExtractionResult']) -> 'EntityExtractionResult'`
  - Merge multiple :class:`EntityExtractionResult` objects into one.
- `dedup_by_text_prefix(result: 'EntityExtractionResult', prefix_len: int = 5) -> 'EntityExtractionResult'`
  - Deduplicate entities that share the same normalised text prefix.
- `count_entities_by_type(result: 'EntityExtractionResult') -> Dict[str, int]`
  - Return a frequency dict of entity type → count for *result*.
- `entity_count(result: 'EntityExtractionResult') -> int`
  - Return the total number of entities in *result*.
- `relationship_count(result: 'EntityExtractionResult') -> int`
  - Return the total number of relationships in *result*.
- `relationship_types(result: 'EntityExtractionResult') -> Set[str]`
  - Return unique relationship types from *result*.
- `entity_ids(result: 'EntityExtractionResult') -> List[str]`
  - Return the ``id`` of every entity in *result*.
- `split_result(result: 'EntityExtractionResult', n: int) -> List['EntityExtractionResult']`
  - Split *result* into *n* balanced non-empty chunks by entities.
- `entities_by_type(result: 'EntityExtractionResult') -> Dict[str, List['Entity']]`
  - Return a dict grouping entities in *result* by their ``type``.
- `sorted_entities(result: 'EntityExtractionResult', key: str = 'confidence', reverse: bool = True) -> List['Entity']`
  - Return entities from *result* sorted by *key*.
- `explain_entity(entity: 'Entity') -> str`
  - Return a concise one-line English description of *entity*.
- `rebuild_result(entities: List['Entity'], relationships: Optional[List['Relationship']] = None, confidence: float = 1.0, metadata: Optional[Dict[str, Any]] = None) -> 'EntityExtractionResult'`
  - Wrap *entities* (and optional *relationships*) in a new result.
- `rename_entity(result: 'EntityExtractionResult', entity_id: str, new_text: str) -> 'EntityExtractionResult'`
  - Return a copy of *result* with the entity identified by *entity_id* renamed.
- `strip_low_confidence(result: 'EntityExtractionResult', threshold: float = 0.5) -> 'EntityExtractionResult'`
  - Return a copy of *result* with low-confidence entities removed.
- `top_entities(result: 'EntityExtractionResult', n: int = 10) -> List['Entity']`
  - Return the top *n* entities by confidence in descending order.
- `filter_result_by_confidence(result: 'EntityExtractionResult', min_conf: float = 0.5) -> 'EntityExtractionResult'`
  - Alias for :meth:`strip_low_confidence` with a cleaner parameter name.
- `relationship_density(result: 'EntityExtractionResult') -> float`
  - Return the ratio of relationships to entities in *result*.
- `group_entities_by_confidence_band(result: 'EntityExtractionResult', bands: List[float]) -> Dict[str, List['Entity']]`
  - Bucket entities by confidence using ascending threshold *bands*.
- `entity_count_property(result: 'EntityExtractionResult') -> int`
  - Return ``len(result.entities)`` as a convenience alias.
- `relationships_for_entity(result: 'EntityExtractionResult', entity_id: str) -> List['Relationship']`
  - Return all relationships where *entity_id* is source or target.
- `validate_result(result: 'EntityExtractionResult') -> List[str]`
  - Return a list of validation issues found in *result*.
- `confidence_stats(result: 'EntityExtractionResult') -> Dict[str, float]`
  - Return descriptive statistics for entity confidences in *result*.
- `clone_result(result: 'EntityExtractionResult') -> 'EntityExtractionResult'`
  - Return a deep copy of *result*.
- `add_entity(result: 'EntityExtractionResult', entity: 'Entity') -> 'EntityExtractionResult'`
  - Return a new result with *entity* appended to the entities list.
- `remove_entity(result: 'EntityExtractionResult', entity_id: str) -> 'EntityExtractionResult'`
  - Return a new result without the entity identified by *entity_id*.
- `type_diversity(result: 'EntityExtractionResult') -> int`
  - Return the count of distinct entity types in *result*.
- `normalize_confidence(result: 'EntityExtractionResult') -> 'EntityExtractionResult'`
  - Return a new result with entity confidences scaled to [0, 1].
- `entity_confidence_map(result: 'EntityExtractionResult') -> Dict[str, float]`
  - Return a mapping of entity id → confidence for all entities in *result*.
- `average_confidence(result: 'EntityExtractionResult') -> float`
  - Return the mean confidence across all entities in *result*.
- `high_confidence_entities(result: 'EntityExtractionResult', threshold: float = 0.8) -> list`
  - Return entities whose confidence is >= *threshold*.
- `filter_entities_by_type(result: 'EntityExtractionResult', entity_type: str) -> list`
  - Return all entities of a specific *entity_type*.
- `deduplicate_by_id(result: 'EntityExtractionResult') -> 'EntityExtractionResult'`
  - Return a copy of *result* with duplicate entity ids removed.
- `unique_relationship_types(result: 'EntityExtractionResult') -> set`
  - Return the set of distinct relationship types in *result*.
- `filter_low_confidence(result: 'EntityExtractionResult', threshold: float = 0.5) -> 'EntityExtractionResult'`
  - Return a copy of *result* with entities below *threshold* removed.
- `apply_config(result: 'EntityExtractionResult', config: 'ExtractionConfig') -> 'EntityExtractionResult'`
  - Re-filter *result* by applying the constraints in *config*.
- `confidence_histogram(result, bins: int = 5) -> dict`
  - Return a bucket-count histogram of entity confidence scores.
- `mean_confidence(result) -> float`
  - Return the mean confidence across all entities in *result*.
- `confidence_std(result) -> float`
  - Return the standard deviation of entity confidence scores.
- `entity_type_distribution(result) -> dict`
  - Return a dict mapping each entity type to its relative frequency.
- `compact_result(result) -> 'EntityExtractionResult'`
  - Return a copy of *result* with entities that have empty properties removed.
- `top_k_entities_by_confidence(result, k: int) -> list`
  - Return the top-*k* entities sorted by descending confidence.
- `entity_count_by_type(result) -> dict`
  - Return a dict mapping entity type → count of entities of that type.
- `entity_count_per_type(result) -> dict`
  - Return a count of entities per entity type.
- `entity_avg_confidence(result) -> float`
  - Return the mean confidence across all entities in *result*.
- `avg_relationship_count(result) -> float`
  - Return average relationships per entity in *result*.
- `entity_type_ratio(result) -> dict`
  - Return fraction of each entity type in *result*.
- `relationship_type_counts(result) -> dict`
  - Return a count of each relationship type in *result*.
- `entity_text_lengths(result) -> list`
  - Return a list of text character counts for each entity.
- `entity_confidence_variance(result) -> float`
  - Return the population variance of entity confidence values.
- `describe_extraction_pipeline(config: ExtractionConfig, result: EntityExtractionResult = None) -> str`
  - Generate a human-readable summary of the extraction pipeline configuration.
- `max_confidence_entity(result) -> Any`
  - Return the entity with the highest confidence in *result*.
- `min_confidence_entity(result) -> Any`
  - Return the entity with the lowest confidence in *result*.
- `entity_confidence_std(result) -> float`
  - Return the population std-dev of entity confidence values.
- `entities_with_properties(result) -> list`
  - Return entities that have at least one non-empty property.
- `top_confidence_fraction(result, frac: float = 0.5) -> list`
  - Return the top fraction of entities sorted by confidence.
- `relationship_source_set(result) -> set`
  - Return the set of unique source entity IDs across all relationships.
- `relationship_target_set(result) -> set`
  - Return the set of unique target entity IDs across all relationships.
- `relationship_source_ids(result) -> set`
  - Return the set of unique source entity IDs across all relationships.
- `relationship_target_ids(result) -> set`
  - Return the set of unique target entity IDs across all relationships.
- `entity_id_list(result) -> list`
  - Return a sorted list of all entity IDs in the extraction result.
- `confidence_quartiles(result: Any) -> dict`
  - Return Q1, median (Q2), and Q3 confidence quartiles for entities.
- `relationship_confidence_mean(result: Any) -> float`
  - Return the mean confidence of all relationships in *result*.
- `relationship_confidence_avg(result: Any) -> float`
  - Alias for :meth:`relationship_confidence_mean`.
- `entities_above_confidence(result: Any, threshold: float = 0.7) -> list`
  - Return entities whose confidence exceeds *threshold*.
- `entity_type_entropy(result: Any) -> float`
  - Return the Shannon entropy of entity type distribution.
- `entity_confidence_skewness(result: Any) -> float`
  - Return the skewness of entity confidence scores.
- `history_kurtosis(results: List[Any]) -> float`
  - Return the kurtosis of confidence scores across multiple results.
- `score_ewma(results: List[Any], alpha: float = 0.3) -> float`
  - Calculate exponentially weighted moving average of confidence scores.
- `score_ewma_series(results: List[Any], alpha: float = 0.3) -> List[float]`
  - Calculate EWMA series showing trend over time.
- `confidence_min(results: List[Any]) -> float`
  - Return the minimum confidence score across all results.
- `confidence_max(results: List[Any]) -> float`
  - Return the maximum confidence score across all results.
- `confidence_range(results: List[Any]) -> float`
  - Return the range (max - min) of confidence scores.
- `confidence_percentile(results: List[Any], percentile: float = 50.0) -> float`
  - Return the specified percentile of confidence scores.
- `confidence_iqr(results: List[Any]) -> float`
  - Return the interquartile range (IQR) of confidence scores.
- `confidence_coefficient_of_variation(results: List[Any]) -> float`
  - Return coefficient of variation (CV) of confidence scores.
- `entity_relation_ratio(result: Any) -> float`
  - Return the ratio of entity count to relationship count.
- `relationship_confidence_std(result: Any) -> float`
  - Return the population std-dev of relationship confidence scores.
- `entity_confidence_percentile(result: Any, p: float = 50.0) -> float`
  - Return the *p*-th percentile of entity confidence scores.
- `relationship_type_frequency(result: Any) -> dict`
  - Return a dict mapping relationship types to their occurrence counts.
- `entity_id_set(result: Any) -> set`
  - Return the set of all entity IDs in *result*.
- `entity_source_span_coverage(result: Any) -> float`
  - Return the fraction of entities that have a non-None source_span.
- `relationship_density(result: Any) -> float`
  - Return edges / nodes ratio (density proxy).
- `relationship_coverage(result: Any) -> float`
  - Return fraction of entities that appear in at least one relationship.
- `entity_confidence_variance(result: Any) -> float`
  - Return the variance of entity confidence scores.
- `entity_property_count(result: Any) -> int`
  - Return the total count of all property key-value pairs across all entities.
- `entity_types_set(result: Any) -> set`
  - Return the set of distinct entity type strings in *result*.
- `entity_confidence_iqr(result: Any) -> float`
  - Return the IQR of entity confidence scores.
- `avg_entity_confidence(result: Any) -> float`
  - Return the average confidence across all entities.
- `relationship_bidirectionality_rate(result: Any) -> float`
  - Return the fraction of unordered entity pairs linked in both directions.
- `entity_text_length_mean(result: Any) -> float`
  - Return the mean length of entity text strings.
- `entity_confidence_mode(result: Any) -> float`
  - Return the most common entity confidence (approximate bin mode).
- `relationship_types_count(result: Any) -> int`
  - Return the number of distinct relationship types in *result*.
- `entity_confidence_std(result: Any) -> float`
  - Return the standard deviation of entity confidence scores.
- `entity_avg_property_count(result: Any) -> float`
  - Return the average number of properties per entity.
- `entity_min_confidence(result: 'EntityExtractionResult') -> float`
  - Return the minimum confidence score across all entities.
- `entity_max_confidence(result: 'EntityExtractionResult') -> float`
  - Return the maximum confidence score across all entities.
- `entity_with_most_properties(result: 'EntityExtractionResult') -> str`
  - Return the ID of the entity with the most properties.
- `relationship_max_weight(result: 'EntityExtractionResult') -> float`
  - Return the maximum weight among all relationships.
- `entity_count_with_confidence_above(result: 'EntityExtractionResult', threshold: float = 0.7) -> int`
  - Return count of entities whose confidence exceeds *threshold*.
- `relationship_avg_confidence(result: 'EntityExtractionResult') -> float`
  - Return the average confidence across all relationships.
- `entity_confidence_range(result: 'EntityExtractionResult') -> float`
  - Return the range (max - min) of entity confidence values.
- `relationship_min_confidence(result: 'EntityExtractionResult') -> float`
  - Return the minimum confidence across all relationships.
- `entity_avg_text_length(result: 'EntityExtractionResult') -> float`
  - Return the mean character length of entity text strings.
- `relationship_confidence_range(result: 'EntityExtractionResult') -> float`
  - Return the range (max - min) of relationship confidence values.
- `entity_property_keys(result: 'EntityExtractionResult') -> set`
  - Return the union of all property keys across entities.
- `entity_text_max_length(result: 'EntityExtractionResult') -> int`
  - Return the maximum character length of entity text strings.
- `relationship_type_diversity(result: 'EntityExtractionResult') -> int`
  - Return the count of distinct relationship types.
- `relationship_avg_weight(result: 'EntityExtractionResult') -> float`
  - Return the average weight across all relationships.
- `entity_confidence_sum(result: 'EntityExtractionResult') -> float`
  - Return the sum of confidence scores across all entities.
- `relationship_source_ids(result: 'EntityExtractionResult') -> set`
  - Return the set of source entity IDs from all relationships.
- `relationship_target_ids(result: 'EntityExtractionResult') -> set`
  - Return the set of target entity IDs from all relationships.
- `entity_confidence_histogram(result: 'EntityExtractionResult', bins: int = 5) -> list`
  - Bucket entity confidence values into *bins* equal-width buckets and return counts.
- `entity_avg_id_length(result: 'EntityExtractionResult') -> float`
  - Return the average character length of entity IDs.
- `relationship_isolated_ids(result: 'EntityExtractionResult') -> set`
  - Return entity IDs that appear only once across all relationships.
- `entity_max_property_count(result: 'EntityExtractionResult') -> int`
  - Return the maximum number of properties across all entities.
- `entity_min_confidence_above(result: 'EntityExtractionResult', threshold: float = 0.5) -> float`
  - Return the minimum confidence among entities with confidence > threshold.
- `relationship_avg_type_length(result: 'EntityExtractionResult') -> float`
  - Return the average character length of relationship type names.
- `entity_unique_types(result: 'EntityExtractionResult') -> set`
  - Return the set of unique entity type strings in the result.
- `relationship_bidirectional_count(result: 'EntityExtractionResult') -> int`
  - Return the number of bidirectional relationship pairs.
- `entity_text_word_count_avg(result: 'EntityExtractionResult') -> float`
  - Return the average word count in entity text fields.
- `relationship_symmetry_ratio(result: 'EntityExtractionResult') -> float`
  - Return the fraction of relationships that have a reverse counterpart.
- `entity_confidence_entropy(result: 'EntityExtractionResult') -> float`
  - Return the Shannon entropy of entity confidence values (bucketed in 0.1 bins).
- `entity_type_gini_coefficient(result: 'EntityExtractionResult') -> float`
  - Return the Gini coefficient of entity type counts.
- `entity_with_longest_text(result: 'EntityExtractionResult') -> Any`
  - Return the entity with the longest text field.
- `relationship_weight_entropy(result: 'EntityExtractionResult') -> float`
  - Return the Shannon entropy of relationship weights (bucketed in 0.1 bins).
- `entity_property_value_types(result: 'EntityExtractionResult') -> set`
  - Return the set of Python type names of all property values across entities.
- `relationship_types_sorted(result: 'EntityExtractionResult') -> list`
  - Return a sorted list of unique relationship type strings.
- `entity_diversity_score(result: 'EntityExtractionResult') -> float`
  - Return a diversity score for entity types: unique_types / total_entities.
- `entity_type_diversity_index(result: 'EntityExtractionResult') -> float`
  - Return the Simpson diversity index over entity types.
- `relationship_density_by_type(result: 'EntityExtractionResult') -> dict`
  - Return a dict of {type: fraction_of_all_relationships} for each relationship type.
- `entity_id_prefix_groups(result: 'EntityExtractionResult', prefix_len: int = 1) -> dict`
  - Group entities by the first *prefix_len* characters of their ID.
- `relationship_cross_type_count(result: 'EntityExtractionResult') -> int`
  - Count relationships that connect entities of different types.
- `entity_multi_property_count(result: 'EntityExtractionResult') -> int`
  - Return the count of entities that have more than one property.
- `relationship_avg_id_pair_length(result: 'EntityExtractionResult') -> float`
  - Return the average combined length of (source_id + target_id) per relationship.
- `entity_confidence_cv(result: 'EntityExtractionResult') -> float`
  - Return the coefficient of variation (std/mean) of entity confidence values.
- `relationship_unique_endpoints(result: 'EntityExtractionResult') -> int`
  - Return the count of unique node IDs that appear in any relationship.
- `entity_with_highest_confidence(result) -> object`
  - Return the entity with the highest confidence, or None.
- `relationship_source_degree_distribution(result) -> dict`
  - Return a dict mapping each source_id to how many relationships it starts.
- `entity_confidence_below_mean_count(result) -> int`
  - Return how many entities have confidence below the mean.
- `relationship_self_loop_ids(result) -> list`
  - Return the IDs of relationships where source == target.
- `entity_text_length_median(result) -> float`
  - Return the median text length (characters) across all entities.
- `relationship_type_entropy(result) -> float`
  - Return the Shannon entropy of relationship type distribution.
- `describe_result(result: Any) -> str`
  - Return a one-line English summary of the extraction result.
- `relationship_confidence_bounds(result: Any) -> tuple`
  - Return (min, max) confidence scores across all relationships.
- `is_result_empty(result: Any) -> bool`
  - Check if result contains no entities and no relationships.
- `result_summary_dict(result: Any) -> dict`
  - Return a structured dictionary summarizing the extraction result.
- `extract_entities_async(data: Any, context: OntologyGenerationContext) -> EntityExtractionResult`
  - Asynchronously extract entities from data using configured strategy.
- `extract_batch_async(data_items: List[Any], contexts: Union[OntologyGenerationContext, List[OntologyGenerationContext]], max_concurrent: int = 5, timeout_per_item: Optional[float] = None) -> List[EntityExtractionResult]`
  - Asynchronously extract entities from multiple data items concurrently.
- `infer_relationships_async(entities: List[Entity], context: OntologyGenerationContext) -> List[Relationship]`
  - Asynchronously infer relationships between entities.
- `extract_with_streaming_async(data: Any, context: OntologyGenerationContext, chunk_size: int = 1000) -> Any`
  - Asynchronously extract entities with streaming results.
- `entity_confidence_geometric_mean(result: 'EntityExtractionResult') -> float`
  - Return the geometric mean of entity confidence scores.
- `entity_confidence_harmonic_mean(result: 'EntityExtractionResult') -> float`
  - Return the harmonic mean of entity confidence scores.
- `relationship_confidence_iqr(result: 'EntityExtractionResult') -> float`
  - Return the IQR of relationship confidence scores.
- `entity_confidence_kurtosis(result: 'EntityExtractionResult') -> float`
  - Return the excess kurtosis of entity confidence scores.
- `entity_text_length_std(result: 'EntityExtractionResult') -> float`
  - Return the standard deviation of entity text lengths.
- `entity_confidence_gini(result: 'EntityExtractionResult') -> float`
  - Return the Gini coefficient of entity confidence scores.
- `relationship_type_count(result: 'EntityExtractionResult') -> int`
  - Return the number of distinct relationship types in *result*.
- `avg_relationship_confidence(result: 'EntityExtractionResult') -> float`
  - Return the mean confidence score across all relationships.
- `entity_type_count(result: 'EntityExtractionResult') -> int`
  - Return the number of distinct entity types in *result*.
- `relationship_density(result: 'EntityExtractionResult') -> float`
  - Return the directed relationship density of *result*.
- `entity_confidence_weighted_mean(result: 'EntityExtractionResult', weights: 'Dict[str, float] | None' = None) -> float`
  - Return the type-weighted mean confidence of all entities.
- `entity_confidence_trimmed_mean(result, trim_pct: float = 10.0) -> float`
  - Return the trimmed mean of entity confidence values.
- `relationship_avg_length(result: 'EntityExtractionResult') -> float`
  - Return the average length of the relationship *type* text field.
- `entity_avg_degree(result: 'EntityExtractionResult') -> float`
  - Return the average number of relationships per entity in *result*.
- `entity_confidence_below_threshold(result: 'EntityExtractionResult', threshold: float = 0.5) -> int`
  - Count entities whose confidence score is strictly below *threshold*.
- `entity_confidence_above_threshold(result: 'EntityExtractionResult', threshold: float = 0.5) -> int`
  - Count entities whose confidence score is at or above *threshold*.

## ipfs_datasets_py/optimizers/graphrag/ontology_critic.py

Ontology Critic for GraphRAG Optimization.

### Classes

#### `BackendConfig`

Typed configuration for the LLM backend used by OntologyCritic.

Methods:
- `from_dict(d: Dict[str, Any]) -> 'BackendConfig'`
- `to_dict() -> Dict[str, Any]`

#### `CriticScore`

Structured ontology quality score.

Methods:
- `overall() -> float`
  - Calculate weighted overall score.
- `to_dict() -> Dict[str, Any]`
  - Convert score to dictionary representation.
- `to_list() -> List[float]`
  - Return dimension values as a flat list.
- `is_passing(threshold: float = 0.6) -> bool`
  - Return ``True`` if ``overall`` is at or above *threshold*.
- `from_dict(d: Dict[str, Any]) -> 'CriticScore'`
  - Reconstruct a :class:`CriticScore` from a dictionary.
- `to_radar_chart_data() -> Dict[str, Any]`
  - Return data suitable for rendering a radar / spider chart.
- `weighted_overall(weights: Dict[str, float]) -> float`
  - Compute an overall score using *caller-supplied* dimension weights.
- `to_html_report() -> str`
  - Render this :class:`CriticScore` as a simple HTML table.
- `to_json() -> str`
  - Return JSON representation of this score.

#### `OntologyCritic`

LLM-based critic for evaluating ontology quality.

Methods:
- `clear_shared_cache() -> None`
  - Clear the class-level evaluation cache shared across all instances.
- `shared_cache_size() -> int`
  - Return the number of entries in the shared evaluation cache.
- `save_shared_cache(filepath: str) -> None`
  - Save the shared evaluation cache to disk.
- `load_shared_cache(filepath: str, merge: bool = False) -> int`
  - Load the shared evaluation cache from disk.
- `explain_score(score: 'CriticScore') -> Dict[str, str]`
  - Return human-readable explanations for each dimension score.
- `score_dimension_range(score: 'CriticScore') -> float`
  - Return the range (max - min) across the dimension scores.
- `dimension_weights() -> Dict[str, float]`
  - Return the scoring weights for each evaluation dimension (read-only copy).
- `evaluate(artifact: Any, context: Any, source_data: Optional[Any]) -> CriticResult`
  - Satisfy the :class:`~ipfs_datasets_py.optimizers.common.BaseCritic` interface.
- `evaluate_ontology(ontology: Dict[str, Any], context: Any, source_data: Optional[Any] = None, timeout: Optional[float] = None, on_evaluation_complete: Optional[Callable[[CriticScore], None]] = None) -> CriticScore`
  - Evaluate ontology across all quality dimensions.
- `evaluate_batch(ontologies: List[Dict[str, Any]], context: Any, source_data: Optional[Any] = None, progress_callback: Optional[Any] = None) -> Dict[str, Any]`
  - Evaluate a list of ontologies and return aggregated statistics.
- `evaluate_batch_parallel(ontologies: List[Dict[str, Any]], context: Any, source_data: Optional[Any] = None, progress_callback: Optional[Any] = None, max_workers: int = 4) -> Dict[str, Any]`
  - Evaluate a list of ontologies in parallel using ThreadPoolExecutor.
- `calibrate_thresholds(scores: List['CriticScore'], percentile: float = 75.0) -> Dict[str, float]`
  - Compute recommended per-dimension thresholds from a history of scores.
- `score_trend(scores: List['CriticScore']) -> str`
  - Determine the trend direction across a sequence of scores.
- `emit_dimension_histogram(scores: List['CriticScore'], bins: int = 5) -> Dict[str, List[int]]`
  - Compute a frequency histogram for each quality dimension.
- `compare_with_baseline(ontology: Dict[str, Any], baseline: Dict[str, Any], context: Any, source_data: Optional[Any] = None) -> Dict[str, Any]`
  - Compare *ontology* against a *baseline* and return the deltas.
- `summarize_batch_results(batch_result: List[Dict[str, Any]], context: Optional[Any] = None, source_data: Optional[Any] = None) -> List[str]`
  - Return a one-line summary string for each ontology in *batch_result*.
- `compare_batch(ontologies: List[Dict[str, Any]], context: Any, source_data: Optional[Any] = None) -> List[Dict[str, Any]]`
  - Rank a list of ontologies by overall score (descending).
- `weighted_overall(score: 'CriticScore', weights: Optional[Dict[str, float]] = None) -> float`
  - Compute a weighted overall score with caller-supplied dimension weights.
- `evaluate_with_rubric(ontology: Dict[str, Any], context: Any, rubric: Dict[str, float], source_data: Optional[Any] = None) -> 'CriticScore'`
  - Evaluate an ontology with caller-supplied dimension weights.
- `compare_ontologies(ontology1: Dict[str, Any], ontology2: Dict[str, Any], context: Optional[Any] = None) -> Dict[str, Any]`
  - Compare two ontologies and identify improvements.
- `compare_versions(v1: Dict[str, Any], v2: Dict[str, Any], context: Optional[Any] = None) -> Dict[str, Any]`
  - Compare two ontology versions and return per-dimension score diffs.
- `score_batch_summary(scores: List['CriticScore']) -> Dict[str, Any]`
  - Return descriptive statistics for a list of :class:`CriticScore` objects.
- `dimension_report(score: 'CriticScore') -> str`
  - Return a multi-line human-readable breakdown of all five dimensions.
- `score_delta(score_a: 'CriticScore', score_b: 'CriticScore') -> Dict[str, float]`
  - Return per-dimension delta (score_b - score_a) for two CriticScores.
- `critical_weaknesses(score: 'CriticScore', threshold: float = 0.5) -> Dict[str, float]`
  - Return dimensions whose value is below *threshold*.
- `top_dimension(score: 'CriticScore') -> str`
  - Return the name of the dimension with the highest value.
- `bottom_dimension(score: 'CriticScore') -> str`
  - Return the name of the dimension with the lowest value.
- `score_range(scores: List['CriticScore']) -> tuple`
  - Return the (min, max) ``overall`` values from a list of CriticScores.
- `improve_score_suggestion(score: 'CriticScore') -> str`
  - Return the name of the dimension most needing improvement.
- `dimension_gap(score: 'CriticScore', target: float = 1.0) -> Dict[str, float]`
  - Return how far each dimension is from *target*.
- `dimension_z_scores(score: 'CriticScore') -> Dict[str, float]`
  - Return z-scores for each dimension relative to their history/baseline.
- `worst_score(scores: List['CriticScore']) -> Optional['CriticScore']`
  - Return the :class:`CriticScore` with the lowest ``overall`` value.
- `best_score(scores: List['CriticScore']) -> Optional['CriticScore']`
  - Return the :class:`CriticScore` with the highest ``overall`` value.
- `score_mean(scores: List['CriticScore']) -> float`
  - Return the mean ``overall`` value across *scores*.
- `score_std(scores: List['CriticScore']) -> float`
  - Return the standard deviation of ``overall`` values across *scores*.
- `dimension_scores(score: 'CriticScore') -> Dict[str, float]`
  - Return a dict mapping each dimension name to its score value.
- `passes_all(scores: List['CriticScore'], threshold: float = 0.6) -> bool`
  - Return ``True`` if every score in *scores* passes *threshold*.
- `all_pass(scores: List['CriticScore'], threshold: float = 0.6) -> bool`
  - Strict variant of :meth:`passes_all` using ``overall > threshold``.
- `score_range(scores: List['CriticScore']) -> tuple`
  - Return a ``(min, max)`` tuple of ``overall`` values from *scores*.
- `score_improvement(score_a: 'CriticScore', score_b: 'CriticScore') -> float`
  - Return the improvement in ``overall`` from *score_a* to *score_b*.
- `above_threshold_count(scores: List['CriticScore'], threshold: float = 0.6) -> int`
  - Return the count of scores with ``overall >= threshold``.
- `top_n_scores(scores: List['CriticScore'], n: int = 5) -> List['CriticScore']`
  - Return the top *n* :class:`CriticScore` objects by ``overall`` value.
- `evaluate_list(ontologies: List[Dict[str, Any]], context: Any) -> List['CriticScore']`
  - Evaluate each ontology in *ontologies* and return a list of scores.
- `score_distribution(scores: List['CriticScore']) -> Dict[str, float]`
  - Return summary statistics for a list of :class:`CriticScore` overall values.
- `score_gap(scores: List['CriticScore']) -> float`
  - Return the difference between the highest and lowest ``overall`` values.
- `median_score(scores: List['CriticScore']) -> float`
  - Return the median ``overall`` value across *scores*.
- `scores_above_threshold(scores: List['CriticScore'], threshold: float = 0.6) -> List['CriticScore']`
  - Return all scores whose ``overall`` value exceeds *threshold*.
- `best_dimension(score: 'CriticScore') -> str`
  - Return the name of the highest-scoring dimension in *score*.
- `worst_dimension(score: 'CriticScore') -> str`
  - Return the name of the lowest-scoring dimension in *score*.
- `get_worst_entity(ontology: Dict[str, Any]) -> Optional[str]`
  - Return the ID of the entity with the lowest confidence score.
- `failing_scores(scores: List['CriticScore'], threshold: float = 0.6) -> List['CriticScore']`
  - Return scores whose ``overall`` value does NOT exceed *threshold*.
- `average_dimension(scores: List['CriticScore'], dim: str) -> float`
  - Return the mean value of dimension *dim* across *scores*.
- `score_summary(scores: List['CriticScore']) -> dict`
  - Return a compact summary dict for a list of critic scores.
- `percentile_overall(scores: List['CriticScore'], p: float) -> float`
  - Return the *p*-th percentile of ``overall`` values across *scores*.
- `normalize_scores(scores: List['CriticScore']) -> List['CriticScore']`
  - Return a list of scores with ``overall``-equivalent values scaled to [0, 1].
- `compare_runs(score_a: 'CriticScore', score_b: 'CriticScore') -> Dict[str, Any]`
  - Return a comparison dict showing how *score_b* differs from *score_a*.
- `dimension_rankings(score: 'CriticScore') -> List[str]`
  - Return dimension names sorted from best (highest) to worst (lowest).
- `weakest_scores(scores: List['CriticScore'], n: int = 3) -> List['CriticScore']`
  - Return the bottom *n* :class:`CriticScore` objects by overall value.
- `score_delta_between(a: 'CriticScore', b: 'CriticScore') -> float`
  - Return the signed difference ``b.overall - a.overall``.
- `all_pass(scores: list, threshold: float = 0.6) -> bool`
  - Return ``True`` if every score's ``overall`` value is >= *threshold*.
- `score_variance(scores: list) -> float`
  - Return the population variance of the ``overall`` values.
- `best_score(scores: list) -> 'CriticScore | None'`
  - Return the :class:`CriticScore` with the highest ``overall`` value.
- `worst_score(scores: list) -> 'CriticScore | None'`
  - Return the :class:`CriticScore` with the lowest ``overall`` value.
- `average_overall(scores: list) -> float`
  - Return the mean ``overall`` across all scores.
- `count_failing(scores: list, threshold: float = 0.6) -> int`
  - Return the count of scores with ``overall <= threshold``.
- `passing_rate(scores: list, threshold: float = 0.6) -> float`
  - Return the fraction of scores with ``overall > threshold``.
- `failing_scores(scores: list, threshold: float = 0.6) -> list`
  - Return only scores that do NOT pass *threshold*.
- `score_spread(scores: list) -> float`
  - Return the range (max - min) of ``overall`` values.
- `top_k_scores(scores: list, k: int = 3) -> list`
  - Return the top-*k* ``CriticScore`` objects sorted by overall score.
- `below_threshold_count(scores: list, threshold: float = 0.5) -> int`
  - Count scores strictly below *threshold*.
- `bucket_scores(scores: list, buckets: int = 4) -> dict`
  - Partition scores into equal-width buckets across [0.0, 1.0].
- `log_evaluation_json(score: CriticScore, log_level: str = 'INFO') -> None`
  - Log evaluation result as structured JSON.
- `improvement_over_baseline(scores: list, baseline: float = 0.5) -> float`
  - Return the fraction of scores strictly above *baseline*.
- `score_iqr(scores: list) -> float`
  - Return the inter-quartile range (Q3 - Q1) of overall scores.
- `dimension_covariance(scores: list, dim_a: str, dim_b: str) -> float`
  - Return the sample covariance between two CriticScore dimensions.
- `top_improving_dimension(before: 'CriticScore', after: 'CriticScore') -> str`
  - Return the dimension with the largest improvement between two scores.
- `critic_dimension_rank(score) -> list`
  - Return dimensions ranked from lowest to highest score.
- `dimension_variance(scores: list, dim: str) -> float`
  - Return the population variance of *dim* across a list of scores.
- `weakest_dimension(score) -> str`
  - Return the name of the lowest-scoring dimension in *score*.
- `dimension_delta_summary(before, after) -> dict`
  - Return a dict of per-dimension deltas between two ``CriticScore`` objects.
- `all_dimensions_above(score, threshold: float = 0.5) -> bool`
  - Return True if all dimensions of *score* exceed *threshold*.
- `dimension_ratio(score) -> dict`
  - Return each dimension score as a fraction of the total score sum.
- `all_dimensions_below(score, threshold: float = 0.5) -> bool`
  - Return True if all dimensions of *score* are below *threshold*.
- `dimension_mean(score) -> float`
  - Return the mean value across all dimensions of *score*.
- `dimension_count_above(score, threshold: float = 0.5) -> int`
  - Return the number of dimensions strictly above *threshold*.
- `dimension_std(score) -> float`
  - Return the standard deviation of dimension values in *score*.
- `dimension_improvement_mask(before, after) -> dict`
  - Return a bool dict indicating which dimensions improved.
- `passing_dimensions(score, threshold: float = 0.5) -> list`
  - Return list of dimension names strictly above *threshold*.
- `weighted_score(score, weights: dict = None) -> float`
  - Return a custom-weighted overall score.
- `dimension_correlation(scores_a: list, scores_b: list, dimension: str = 'completeness') -> float`
  - Return Pearson correlation for *dimension* across two score lists.
- `dimension_entropy(score) -> float`
  - Return Shannon entropy of dimension values in *score*.
- `compare_scores(before, after) -> dict`
  - Return per-dimension diffs plus overall delta.
- `score_is_above_baseline(score: 'CriticScore', baseline: float = 0.5) -> bool`
  - Return whether every dimension in *score* exceeds *baseline*.
- `top_k_dimensions(score: 'CriticScore', k: int = 3) -> list`
  - Return the *k* highest-scoring dimension names for *score*.
- `dimension_improvement_rate(before: 'CriticScore', after: 'CriticScore') -> float`
  - Return the fraction of dimensions that improved from *before* to *after*.
- `dimension_weighted_sum(score: 'CriticScore', weights: dict = None) -> float`
  - Return a weighted sum of all dimension scores.
- `dimension_min(score: 'CriticScore') -> str`
  - Return the name of the lowest-scoring dimension.
- `dimension_max(score: 'CriticScore') -> str`
  - Return the name of the highest-scoring dimension.
- `dimension_range(score: 'CriticScore') -> float`
  - Return the range (max - min) across all dimension values.
- `score_reliability(scores: list) -> float`
  - Return a reliability measure for a list of :class:`CriticScore` objects.
- `dimensions_above_count(score: 'CriticScore', threshold: float = 0.5) -> int`
  - Return the number of dimensions strictly above *threshold*.
- `score_letter_grade(score: 'CriticScore') -> str`
  - Return a letter grade (A–F) based on the overall score.
- `dimension_coefficient_of_variation(score: 'CriticScore') -> float`
  - Return the coefficient of variation (std / mean) of dimension values.
- `dimensions_at_max_count(score: 'CriticScore', threshold: float = 0.9) -> int`
  - Return the number of dimensions at or above *threshold*.
- `dimension_harmonic_mean(score: 'CriticScore') -> float`
  - Return the harmonic mean of the six dimension values.
- `dimension_geometric_mean(score: 'CriticScore') -> float`
  - Return the geometric mean of the six dimension values.
- `dimensions_below_count(score: 'CriticScore', threshold: float = 0.3) -> int`
  - Return the number of dimensions below *threshold*.
- `dimension_spread(score: 'CriticScore') -> float`
  - Return max - min of the six dimension values.
- `top_dimension(score: 'CriticScore') -> str`
  - Return the name of the highest-scoring dimension.
- `bottom_dimension(score: 'CriticScore') -> str`
  - Return the name of the lowest-scoring dimension.
- `score_above_threshold_count(score: 'CriticScore', threshold: float = 0.7) -> int`
  - Return count of dimensions at or above *threshold*.
- `dimension_balance_score(score: 'CriticScore') -> float`
  - Return a "balance" score in [0, 1].
- `score_percentile_rank(score: 'CriticScore', history: list) -> float`
  - Return the percentile rank of *score* overall within *history*.
- `score_classification(score: 'CriticScore') -> str`
  - Return a human-readable quality bucket for *score*.
- `dimension_rank_order(score: 'CriticScore') -> list`
  - Return dimension names sorted from highest to lowest value.
- `dimension_normalized_vector(score: 'CriticScore') -> list`
  - Return dimension values normalized to a unit vector (L2).
- `score_above_median(score: 'CriticScore', history: list) -> bool`
  - Return True if *score* overall is above the median of *history*.
- `dimension_cosine_similarity(score1: 'CriticScore', score2: 'CriticScore') -> float`
  - Return cosine similarity between two CriticScore dimension vectors.
- `score_distance(score1: 'CriticScore', score2: 'CriticScore') -> float`
  - Return Euclidean distance between two CriticScore dimension vectors.
- `dimension_percentile(score: 'CriticScore', p: float = 50.0) -> float`
  - Return the p-th percentile of dimension values in a CriticScore.
- `dimension_above_threshold(score: 'CriticScore', threshold: float = 0.7) -> int`
  - Count how many dimensions in a CriticScore exceed a threshold.
- `dimension_mean(score: 'CriticScore') -> float`
  - Return the arithmetic mean of all dimension values in a CriticScore.
- `dimension_below_threshold(score: 'CriticScore', threshold: float = 0.5) -> int`
  - Count how many dimensions in a CriticScore fall below *threshold*.
- `dimension_weighted_score(score: 'CriticScore', weights: dict | None = None) -> float`
  - Return a weighted average of dimension scores.
- `dimension_top_k(score: 'CriticScore', k: int = 3) -> list`
  - Return the names of the top-k highest-scoring dimensions.
- `dimension_bottom_k(score: 'CriticScore', k: int = 3) -> list`
  - Return the names of the bottom-k lowest-scoring dimensions.
- `dimension_sum(score: 'CriticScore') -> float`
  - Return the sum of all dimension values in a CriticScore.
- `score_diff_from_mean(score: 'CriticScore') -> float`
  - Return the difference between overall score and dimension mean.
- `cache_hit_potential() -> float`
  - Calculate potential benefit of caching (shared/instance).
- `score_dimension_variance(score: 'CriticScore') -> float`
  - Calculate variance across the six dimension scores.
- `dimension_range(score: 'CriticScore') -> float`
  - Get range (max - min) of dimension scores.
- `weakest_dimension(score: 'CriticScore') -> str`
  - Identify the dimension with lowest score.
- `strongest_dimension(score: 'CriticScore') -> str`
  - Identify the dimension with highest score.
- `score_balance_ratio(score: 'CriticScore') -> float`
  - Calculate balance ratio (min/max dimension score).
- `dimensions_above_threshold(score: 'CriticScore', threshold: float = 0.7) -> int`
  - Count dimensions with scores above threshold.
- `overall_vs_best_dimension(score: 'CriticScore') -> float`
  - Compare overall score to strongest dimension.
- `score_consistency_coefficient(score: 'CriticScore') -> float`
  - Calculate coefficient of variation (CV) for dimension scores.
- `recommendation_density(score: 'CriticScore') -> float`
  - Calculate density of recommendations relative to weaknesses.
- `dimension_iqr(score: 'CriticScore') -> float`
  - Return the interquartile range (IQR) of dimension values in a score.
- `dimension_coefficient_of_variation(score: 'CriticScore') -> float`
  - Return the coefficient of variation (std / mean) of dimension values.
- `dimension_skewness(score: 'CriticScore') -> float`
  - Return the skewness of the 6 evaluation dimension values.
- `dimensions_above_mean(score: 'CriticScore') -> int`
  - Return the number of dimension values strictly above the collective mean.
- `dimension_gini(score: 'CriticScore') -> float`
  - Return the Gini coefficient of the 6 evaluation dimension values.
- `score_dimension_variance(score: 'CriticScore') -> float`
  - Return the population variance of the 6 evaluation dimension values.
- `top_two_dimensions(score: 'CriticScore') -> tuple`
  - Return the names of the two highest-scoring evaluation dimensions.
- `dimension_trend_slope(score: 'CriticScore', prev_score: 'CriticScore') -> dict`
  - Return per-dimension slope between two successive CriticScore objects.
- `min_max_dimension_ratio(score: 'CriticScore') -> float`
  - Return the ratio of the minimum dimension value to the maximum.
- `dimension_range(score: 'CriticScore') -> float`
  - Return the range (max − min) of the six dimension values.
- `dimension_weighted_std(score: 'CriticScore') -> float`
  - Return the weighted population standard deviation of the six dimensions.
- `dimension_percentile_rank(score: 'CriticScore', dim: str) -> float`
  - Return the percentile rank of a named dimension within a CriticScore.
- `score_dimension_entropy(score: 'CriticScore') -> float`
  - Return the Shannon entropy of the six-dimension value distribution.
- `score_dimension_energy(score: 'CriticScore') -> float`
  - Return the L2 energy (norm squared) of the six CriticScore dimensions.
- `score_dimension_kurtosis(score: 'CriticScore') -> float`
  - Return the population excess kurtosis of the six CriticScore dimensions.
- `score_dimension_skewness(score: 'CriticScore') -> float`
  - Return the population skewness of the six CriticScore dimension values.
- `score_dimension_range_ratio(score: 'CriticScore') -> float`
  - Return the range ratio of the six CriticScore dimension values.
- `score_dimension_gini_coefficient(score: 'CriticScore') -> float`
  - Return the Gini coefficient of the 6 CriticScore dimension values.
- `score_dimension_max_z(score: 'CriticScore') -> float`
  - Return the maximum absolute z-score across the 6 CriticScore dimensions.
- `score_dimension_min_z(score: 'CriticScore') -> float`
  - Return the minimum absolute z-score across the 6 CriticScore dimensions.
- `score_dimension_mean_abs_deviation(score: 'CriticScore') -> float`
  - Return the Mean Absolute Deviation (MAD) of the six CriticScore dimensions.
- `score_dimension_median_abs_deviation(score: 'CriticScore') -> float`
  - Return the Median Absolute Deviation (MAD) of the six CriticScore dimensions.

## ipfs_datasets_py/optimizers/graphrag/ontology_mediator.py

Ontology Mediator for GraphRAG Optimization.

### Classes

#### `MediatorState`

Tracks state across refinement rounds.

Methods:
- `add_round(ontology: Dict[str, Any], score: Any, refinement_action: str) -> Any`
  - Add a refinement round to the history.
- `get_score_trend() -> str`
  - Get the trend of scores over rounds.
- `to_dict() -> Dict[str, Any]`
  - Serialize MediatorState to a dictionary, including all refinement-specific fields.
- `from_dict(data: Dict[str, Any]) -> 'MediatorState'`
  - Reconstruct a MediatorState from a dictionary.

#### `OntologyMediator`

Mediates ontology generation and refinement cycles.

Methods:
- `generate_prompt(context: Any, feedback: Optional[Any] = None) -> str`
  - Generate extraction prompt incorporating critic feedback.
- `refine_ontology(ontology: Dict[str, Any], feedback: Any, context: Any) -> Ontology`
  - Refine ontology based on critic feedback.
- `batch_apply_strategies(ontologies: List[Dict[str, Any]], feedbacks: List[Any], context: Any, max_workers: Optional[int] = None, track_changes: bool = True) -> Ontology`
  - Apply refinement strategies to multiple ontologies in parallel.
- `get_action_stats() -> Dict[str, int]`
  - Return cumulative per-action invocation counts across all :meth:`refine_ontology` calls.
- `get_action_summary(top_n: Optional[int] = None) -> List[Dict[str, Any]]`
  - Return action statistics sorted by invocation count (descending).
- `preview_recommendations(ontology: Dict[str, Any], score: Any, context: Any) -> List[str]`
  - Return the recommendations that *would* be applied without mutating state.
- `suggest_refinement_strategy(ontology: Dict[str, Any], score: Any, context: Any) -> Dict[str, Any]`
  - Suggest the optimal refinement strategy based on current ontology quality.
- `batch_suggest_strategies(ontologies: List[Dict[str, Any]], scores: List[Any], context: Any, max_workers: int | None = None) -> Dict[str, Any]`
  - Suggest refinement strategies for a batch of ontologies.
- `compare_strategies(strategies: List[Dict[str, Any]]) -> Dict[str, Any]`
  - Compare a list of refinement strategies and return the best pick.
- `undo_all() -> Optional[Dict[str, Any]]`
  - Undo all refinements and return the oldest ontology snapshot.
- `get_recommendation_stats() -> Dict[str, int]`
  - Return counts of unique recommendation phrases seen across all refinements.
- `reset_state() -> None`
  - Clear all internal mutable state accumulated across refinement calls.
- `reset_all_state() -> None`
  - Clear all internal mutable state including the action entry log.
- `top_recommended_action() -> Optional[str]`
  - Return the action name with the highest recommendation count.
- `pending_recommendation() -> Optional[str]`
  - Return the top recommendation phrase without modifying any state.
- `most_frequent_action() -> Optional[str]`
  - Return the action with the highest cumulative invocation count.
- `action_count_for(action: str) -> int`
  - Return the cumulative invocation count for a specific *action*.
- `action_types() -> list`
  - Return a sorted list of distinct action type strings that have been applied.
- `actions_never_applied() -> list[str]`
  - Return known refinement action types that have never been applied.
- `total_action_count() -> int`
  - Return the total count of all action invocations.
- `top_actions(n: int = 3) -> list`
  - Return the top *n* most-frequently applied action names.
- `undo_depth() -> int`
  - Return the number of undoable snapshots in the undo stack.
- `reset_action_counts() -> int`
  - Clear all accumulated action count statistics.
- `apply_action_bulk(actions: list) -> int`
  - Increment action counts for each action entry in *actions*.
- `clear_recommendation_history() -> int`
  - Clear the recommendation phrase frequency table.
- `get_round_count() -> int`
  - Return the total number of refinement rounds performed.
- `action_log(max_entries: int = 50) -> List[Dict[str, Any]]`
  - Return the most recent action log entries.
- `get_undo_depth() -> int`
  - Return the number of snapshots in the undo stack.
- `peek_undo() -> Optional[Dict[str, Any]]`
  - Return the top snapshot from the undo stack without popping it.
- `stash(ontology: Dict[str, Any]) -> int`
  - Push a snapshot of *ontology* onto the undo stack without running a
- `snapshot_count() -> int`
  - Return the number of snapshots currently on the undo stack.
- `clear_stash() -> int`
  - Clear all snapshots from the undo stack.
- `log_snapshot(label: str, ontology: Dict[str, Any]) -> None`
  - Store a labeled snapshot in the undo stack.
- `set_max_rounds(n: int) -> None`
  - Update the maximum refinement rounds at runtime.
- `log_action_summary(top_n: Optional[int] = 10) -> None`
  - Log the top action counts at INFO level.
- `undo_last_action() -> Optional[Dict[str, Any]]`
  - Revert the last applied refinement action by popping the undo stack.
- `run_refinement_cycle(data: Any, context: Any) -> MediatorState`
  - Run complete refinement cycle.
- `run_agentic_refinement_cycle(data: Any, context: Any, max_rounds: Optional[int] = None, min_improvement: float = 0.01) -> MediatorState`
  - Run a refinement cycle that uses strategy recommendations to guide stopping.
- `run_llm_refinement_cycle(data: Any, context: Any, agent: Any, max_rounds: Optional[int] = None, min_improvement: float = 0.01) -> MediatorState`
  - Run a refinement cycle that uses an LLM agent to propose feedback.
- `check_convergence(state: MediatorState) -> bool`
  - Check if refinement has converged.
- `action_frequency() -> dict`
  - Return a normalised frequency map of action names.
- `has_actions() -> bool`
  - Return ``True`` if any actions have been recorded.
- `action_diversity() -> int`
  - Return the number of distinct action types that have been used.
- `action_sequence_entropy() -> float`
  - Compute Shannon entropy of the action sequence as categorical symbols.
- `most_used_action() -> 'str | None'`
  - Return the action name with the highest recorded count.
- `least_used_action() -> 'str | None'`
  - Return the action name with the lowest positive recorded count.
- `undo_stack_summary() -> list`
  - Return a list of labels for each item on the mediator's undo stack.
- `undo_stack_depth() -> int`
  - Return the number of items currently on the undo stack.
- `total_actions_taken() -> int`
  - Return the total number of actions recorded across all action types.
- `unique_action_count() -> int`
  - Return the number of distinct action types that have been used.
- `apply_feedback_list(scores: list) -> None`
  - Apply a list of ``CriticScore`` objects to the mediator's feedback loop.
- `feedback_history_size() -> int`
  - Return the number of feedback records stored in the mediator.
- `action_count_unique() -> int`
  - Return the number of distinct action types that have been invoked.
- `feedback_age(idx: int) -> int`
  - Return how many rounds/refinements ago the feedback at index was recorded.
- `clear_feedback() -> int`
  - Clear all recorded feedback history and return how many were removed.
- `feedback_score_mean() -> float`
  - Return the mean feedback score seen by this mediator.
- `most_improved_action() -> Optional[str]`
  - Return the action type with the highest average score across feedback.
- `feedback_count_by_action(action: str) -> int`
  - Return how many times *action* appears in ``_action_counts``.
- `action_success_rate(action: str) -> float`
  - Return the stored success rate for *action*.
- `action_entropy() -> float`
  - Return the Shannon entropy of the action count distribution.
- `action_entropy_change() -> float`
  - Return the change in action entropy over the feedback history.
- `total_action_count() -> int`
  - Return the total number of action invocations recorded.
- `action_ratio(action: str) -> float`
  - Return the fraction of total actions attributed to a given action.
- `action_mode() -> str`
  - Return the action name with the highest count.
- `action_least_frequent() -> str`
  - Return the action name with the lowest count.
- `action_diversity_score() -> float`
  - Return a diversity score based on the entropy of action distribution.
- `action_gini() -> float`
  - Return the Gini coefficient of the action count distribution.
- `action_count_per_round() -> float`
  - Return the average number of actions recorded per round.
- `action_names() -> list`
  - Return a sorted list of all action names recorded.
- `action_top_n(n: int = 3) -> list`
  - Return the top *n* most-performed actions as (name, count) tuples.
- `action_count_total() -> int`
  - Return the total number of actions performed across all types.
- `action_diversity_ratio() -> float`
  - Return the ratio of distinct action types to total actions performed.
- `action_max_consecutive() -> int`
  - Return the maximum count for any single action type.
- `action_least_recent() -> str`
  - Return the name of the least-performed action type.
- `action_round_with_most() -> str`
  - Return the action type that was performed the most times.
- `action_pct_of_total(action_name: str) -> float`
  - Return the fraction of total actions that *action_name* accounts for.
- `action_entropy_normalized() -> float`
  - Return the normalized Shannon entropy of the action distribution.
- `action_balance_score() -> float`
  - Return a balance score measuring how evenly actions are distributed.
- `action_uniformity_index() -> float`
  - Return a uniformity index: 1 - (std / mean) of action counts, clipped to [0,1].
- `action_peak_fraction() -> float`
  - Return the fraction of total actions performed by the most-frequent type.
- `action_concentration_ratio(top_k: int = 3) -> float`
  - Return the share of total actions held by the top-*k* action types.
- `action_last_n_most_common(n: int = 5) -> str`
  - Return the name of the most-common action among the last *n* recorded.
- `action_gini_coefficient() -> float`
  - Return the Gini coefficient of action count distribution.
- `total_refinements() -> int`
  - Get total number of refinement operations applied.
- `rounds_completed() -> int`
  - Get number of refinement rounds completed.
- `has_converged(threshold: float = 0.01, window: int = 3) -> bool`
  - Check if refinement has converged (minimal score changes).
- `refinement_efficiency() -> float`
  - Calculate efficiency of refinements (improvement per action).
- `score_change_per_round() -> float`
  - Calculate average score change per refinement round.
- `action_impact(action_name: str) -> float`
  - Calculate average score impact of a specific action type.
- `most_productive_round() -> int`
  - Find the round that produced the largest score improvement.
- `refinement_stagnation_rounds(threshold: float = 0.001) -> int`
  - Count consecutive rounds with minimal improvement (stagnation).
- `score_volatility() -> float`
  - Calculate volatility (standard deviation) of refinement scores.
- `refinement_trajectory() -> str`
  - Get description of overall refinement trajectory.
- `retry_last_round(ontology: 'Dict[str, Any]', score: Any, context: Any) -> 'Dict[str, Any]'`
  - Re-apply the most recent refinement round.

## ipfs_datasets_py/optimizers/agentic/cli.py

Command-line interface for agentic optimizer.

### Functions

- `main(args: Optional[List[str]] = None) -> int`
  - Main entry point.

### Classes

#### `OptimizerArgparseCLI`

Command-line interface for agentic optimizer.

Methods:
- `cmd_optimize(args: argparse.Namespace) -> int`
  - Run optimization task.
- `cmd_agents_list(args: argparse.Namespace) -> int`
  - List all agents.
- `cmd_agents_status(args: argparse.Namespace) -> int`
  - Show detailed status for an agent.
- `cmd_queue_process(args: argparse.Namespace) -> int`
  - Process task queue.
- `cmd_stats(args: argparse.Namespace) -> int`
  - Show optimization statistics.
- `cmd_rollback(args: argparse.Namespace) -> int`
  - Rollback a change.
- `cmd_config(args: argparse.Namespace) -> int`
  - Manage configuration.
- `cmd_validate(args: argparse.Namespace) -> int`
  - Validate code.
- `run(argv: Optional[List[str]] = None) -> int`
  - Run CLI.

#### `OptimizerCLI`

Methods:
- `load_config() -> None`
- `save_config() -> None`
- `cmd_optimize(args: Any) -> None`
- `cmd_agents_list(args: Any) -> None`
- `cmd_agents_status(args: Any) -> None`
- `cmd_queue_process(args: Any) -> None`
- `cmd_stats(args: Any) -> None`
- `cmd_rollback(args: Any) -> None`
- `cmd_config(args: Any) -> None`
- `cmd_validate(args: Any) -> None`
