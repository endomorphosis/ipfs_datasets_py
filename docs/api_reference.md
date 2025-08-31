# IPFS Datasets Python - API Reference

This documentation provides detailed information about the modules, classes, and functions available in the IPFS Datasets Python package.

## 🗺️ Navigation Guide

### By Use Case
- **Getting Started**: [Core Modules](#core-modules) → [Basic Usage](#basic-usage-examples)
- **Vector Search**: [Vector Storage](#vector-storage-and-search) → [Search Examples](#search-examples)
- **PDF Processing**: [PDF Module](#pdf-processing) → [PDF Examples](#pdf-examples)
- **AI Integration**: [RAG Modules](#graph-based-rag) → [LLM Examples](#llm-examples)

### By Component Type
- **🏗️ Infrastructure**: [Core Modules](#core-modules), [IPLD Integration](#ipld-integration)
- **🔍 Search & Retrieval**: [Vector Storage](#vector-storage-and-search), [Search Module](#search-module)
- **🤖 AI & ML**: [Embeddings](#embeddings), [RAG Modules](#graph-based-rag)
- **📄 Document Processing**: [PDF Processing](#pdf-processing), [Text Utils](#text-utilities)
- **🔧 Tools & Management**: [MCP Tools](#mcp-tools), [Operations](#operations-and-management)

## Table of Contents

1. [Core Modules](#core-modules)
   - [ipfs_datasets](#ipfs_datasets)
   - [dataset_serialization](#dataset_serialization)
   - [car_conversion](#car_conversion)
   - [ipfs_parquet_to_car](#ipfs_parquet_to_car)
   
2. [Embeddings](#embeddings)
   - [Embedding Generation](#embedding-generation)
   - [Text Chunking](#text-chunking)
   - [Schema Definitions](#schema-definitions)

3. [Vector Storage and Search](#vector-storage-and-search)
   - [Vector Stores](#vector-stores) 
   - [Search Module](#search-module)
   - [ipfs_knn_index](#ipfs_knn_index)

4. [PDF Processing](#pdf-processing)
   - [PDF Processor](#pdf-processor)
   - [Batch Processing](#batch-processing)
   - [OCR Engine](#ocr-engine)
   - [LLM Optimization](#llm-optimization)

5. [Text Utilities](#text-utilities)
   - [Text Processing](#text-processing)
   - [Chunk Optimization](#chunk-optimization)
   
6. [IPLD Integration](#ipld-integration)
   - [ipld.storage](#ipld-storage)
   - [ipld.dag_pb](#ipld-dag_pb)
   - [unixfs_integration](#unixfs_integration)

7. [Graph-Based RAG](#graph-based-rag)
   - [knowledge_graph_extraction](#knowledge_graph_extraction)
   - [llm_graphrag](#llm_graphrag)
   - [rag_query_optimizer](#rag_query_optimizer)
   - [llm_reasoning_tracer](#llm_reasoning_tracer)
   - [llm_semantic_validation](#llm_semantic_validation)

8. [MCP Tools](#mcp-tools)
   - [Tool Registry](#tool-registry)
   - [Available Tools](#available-tools)
   - [Tool Development](#tool-development)

9. [Web Archive Integration](#web-archive-integration)
   - [web_archive_utils](#web_archive_utils)

10. [Operations and Management](#operations-and-management)
    - [data_provenance](#data_provenance)
    - [cross_document_lineage](#cross_document_lineage)
    - [monitoring](#monitoring)
    - [security](#security)
    - [resilient_operations](#resilient_operations)
    - [admin_dashboard](#admin_dashboard)
    - [streaming_data_loader](#streaming_data_loader)
    - [federated_search](#federated_search)

11. [Configuration](#configuration)
    - [config](#config)

---

## Core Modules

### ipfs_datasets

The main module providing the central interface for working with datasets.

#### Functions

##### `load_dataset(dataset_name, **kwargs)`

Loads a dataset from various sources.

**Parameters:**
- `dataset_name` (str): Name of the dataset to load
- `**kwargs`: Additional arguments for dataset loading

**Returns:**
- Dataset object

##### `process_dataset(dataset, operations, **kwargs)`

Process a dataset with a list of operations.

**Parameters:**
- `dataset`: Dataset object
- `operations` (list): List of operations to apply
- `**kwargs`: Additional arguments

**Returns:**
- Processed dataset

##### `save_dataset(dataset, destination, format='parquet', **kwargs)`

Save a dataset to a destination in a specified format.

**Parameters:**
- `dataset`: Dataset object
- `destination` (str): Path or identifier for where to save the dataset
- `format` (str): Format to save in ('parquet', 'car', 'arrow', etc.)
- `**kwargs`: Additional arguments for format-specific saving

**Returns:**
- Path or CID identifier of the saved dataset

---

### dataset_serialization

Module for serializing datasets to various formats.

#### Functions

##### `serialize_dataset(dataset, format='parquet', **kwargs)`

Serialize a dataset to a specific format.

**Parameters:**
- `dataset`: Dataset object
- `format` (str): Format to serialize to ('parquet', 'car', 'arrow', etc.)
- `**kwargs`: Additional arguments for format-specific serialization

**Returns:**
- Serialized dataset (bytes or file path)

##### `deserialize_dataset(data, format='parquet', **kwargs)`

Deserialize a dataset from a specific format.

**Parameters:**
- `data`: Serialized dataset (bytes or file path)
- `format` (str): Format to deserialize from ('parquet', 'car', 'arrow', etc.)
- `**kwargs`: Additional arguments for format-specific deserialization

**Returns:**
- Deserialized dataset object

---

### car_conversion

Module for converting datasets to and from Content Addressable aRchives (CAR).

#### Functions

##### `dataset_to_car(dataset, output_path, hash_columns=None, **kwargs)`

Convert a dataset to a CAR file.

**Parameters:**
- `dataset`: Dataset object
- `output_path` (str): Path to save the CAR file
- `hash_columns` (list): Column names to use for content-addressing
- `**kwargs`: Additional arguments

**Returns:**
- Root CID of the CAR file

##### `car_to_dataset(car_path, **kwargs)`

Convert a CAR file to a dataset.

**Parameters:**
- `car_path` (str): Path to the CAR file
- `**kwargs`: Additional arguments

**Returns:**
- Dataset object

---

### ipfs_parquet_to_car

Module for direct conversion between Parquet and CAR files.

#### Functions

##### `parquet_to_car(parquet_path, car_path, hash_columns=None, **kwargs)`

Convert a Parquet file to a CAR file.

**Parameters:**
- `parquet_path` (str): Path to the Parquet file
- `car_path` (str): Path to save the CAR file
- `hash_columns` (list): Column names to use for content-addressing
- `**kwargs`: Additional arguments

**Returns:**
- Root CID of the CAR file

##### `car_to_parquet(car_path, parquet_path, **kwargs)`

Convert a CAR file to a Parquet file.

**Parameters:**
- `car_path` (str): Path to the CAR file
- `parquet_path` (str): Path to save the Parquet file
- `**kwargs`: Additional arguments

**Returns:**
- Path to the Parquet file

---

## IPLD Integration

### ipld.storage

Module for working with IPLD-based storage for datasets.

#### Classes

##### `IPLDStorage`

Storage class for IPLD-based dataset storage.

**Methods:**
- `__init__(self, ipfs_client=None, storage_dir=None)`: Initialize storage
- `store(self, data, hash_algorithm='sha2-256')`: Store data and get CID
- `get(self, cid)`: Get data by CID
- `put_many(self, blocks)`: Store multiple blocks
- `get_many(self, cids)`: Get multiple blocks by CIDs
- `export_to_car(self, cids, output_path)`: Export blocks to CAR file
- `import_from_car(self, car_path)`: Import blocks from CAR file

---

### ipld.dag_pb

Module implementing DAG-PB (Directed Acyclic Graph - ProtoBuf) for IPLD.

#### Classes

##### `PBNode`

Class for PBNode in DAG-PB.

**Methods:**
- `__init__(self, data=None, links=None)`: Initialize PBNode
- `add_link(self, name, cid, tsize=None)`: Add a link to another node
- `remove_link(self, name)`: Remove a link by name
- `get_link(self, name)`: Get a link by name
- `to_dict(self)`: Convert to dictionary
- `from_dict(cls, obj)`: Create from dictionary

#### Functions

##### `encode(node)`

Encode a PBNode to bytes.

**Parameters:**
- `node` (PBNode): Node to encode

**Returns:**
- Encoded bytes

##### `decode(data)`

Decode bytes to a PBNode.

**Parameters:**
- `data` (bytes): Data to decode

**Returns:**
- PBNode object

---

### unixfs_integration

Module for integrating with UnixFS for file and directory representation.

#### Classes

##### `UnixFSWriter`

Class for writing data to UnixFS format.

**Methods:**
- `__init__(self, ipfs_client=None)`: Initialize writer
- `write_file(self, file_path, chunker=None)`: Write file to UnixFS
- `write_directory(self, dir_path, recursive=True)`: Write directory to UnixFS
- `write_to_car(self, path, car_path, chunker=None)`: Write to CAR file

##### `UnixFSReader`

Class for reading data from UnixFS format.

**Methods:**
- `__init__(self, ipfs_client=None)`: Initialize reader
- `read_file(self, cid)`: Read file from UnixFS
- `read_directory(self, cid)`: Read directory from UnixFS
- `extract_from_car(self, car_path, output_dir)`: Extract from CAR file

---

## Vector Storage and Search

### ipfs_knn_index

Module for k-nearest neighbors search in vector space.

#### Classes

##### `IPFSKnnIndex`

Vector indexing and search with IPFS integration.

**Methods:**
- `__init__(self, dimension=768, metric='cosine')`: Initialize index
- `add_vectors(self, vectors, metadata=None)`: Add vectors to index
- `search(self, query_vector, top_k=10)`: Search for similar vectors
- `save(self, output_path)`: Save index to file
- `load(self, input_path)`: Load index from file
- `export_to_ipfs(self)`: Export index to IPFS
- `export_to_car(self, output_path)`: Export index to CAR file
- `from_ipfs(cls, cid)`: Load index from IPFS
- `from_car(cls, car_path)`: Load index from CAR file

---

### ipfs_embeddings_py

Module for generating and working with embeddings.

#### Functions

##### `load_embedding_model(model_name)`

Load an embedding model.

**Parameters:**
- `model_name` (str): Name of embedding model

**Returns:**
- Embedding model

##### `generate_embeddings(texts, model)`

Generate embeddings for texts.

**Parameters:**
- `texts` (list): List of texts
- `model`: Embedding model

**Returns:**
- List of embedding vectors

---

## Graph-Based RAG

### knowledge_graph_extraction

Module for extracting knowledge graphs from text.

#### Classes

##### `KnowledgeGraphExtractor`

Class for extracting knowledge graphs.

**Methods:**
- `__init__(self, extraction_models=None)`: Initialize extractor
- `extract_graph(self, text, document_cid=None)`: Extract knowledge graph
- `merge_with_existing(self, new_graph, existing_graph_cid)`: Merge graphs
- `store_on_ipfs(self, entities, relationships, metadata=None)`: Store graph on IPFS

---

### llm_graphrag

Module for graph-based RAG (Retrieval-Augmented Generation).

#### Classes

##### `GraphRAGQueryEngine`

Engine for graph-based RAG queries.

**Methods:**
- `__init__(self, vector_stores, graph_store, model_weights=None)`: Initialize engine
- `query(self, query_text, top_k=10, max_graph_hops=2)`: Perform GraphRAG query
- `vector_search(self, query_embedding, models=None)`: Perform vector search
- `graph_search(self, seed_entities, max_hops=2)`: Perform graph search
- `combine_results(self, vector_results, graph_results)`: Combine search results

---

### rag_query_optimizer

Module for optimizing RAG queries.

#### Classes

##### `QueryOptimizer`

Class for optimizing RAG queries.

**Methods:**
- `__init__(self, vector_store, knowledge_graph)`: Initialize optimizer
- `optimize_query(self, query, context=None)`: Optimize query
- `rewrite_query(self, query, context=None)`: Rewrite query
- `decompose_query(self, query, context=None)`: Decompose complex query
- `determine_query_type(self, query)`: Determine query type

---

### llm_reasoning_tracer

Module for tracing reasoning in LLM-based systems.

#### Classes

##### `ReasoningTracer`

Class for tracing reasoning steps.

**Methods:**
- `__init__(self, trace_file=None)`: Initialize tracer
- `start_trace(self, query)`: Start a new trace
- `add_reasoning_step(self, step_name, input_data, output_data)`: Add step
- `end_trace(self, result)`: End the trace
- `get_trace(self, trace_id=None)`: Get a specific trace
- `export_trace(self, trace_id, format='json')`: Export trace
- `visualize_trace(self, trace_id)`: Visualize reasoning trace

---

### llm_semantic_validation

Module for validating LLM outputs for semantic correctness.

#### Classes

##### `SemanticValidator`

Class for semantic validation of LLM outputs.

**Methods:**
- `__init__(self, validation_model=None)`: Initialize validator
- `validate(self, query, response, context=None)`: Validate response
- `validate_factuality(self, response, context)`: Check factual accuracy
- `validate_coherence(self, response)`: Check coherence
- `validate_relevance(self, query, response)`: Check relevance to query
- `get_confidence_score(self, query, response, context=None)`: Get confidence score

---

## Web Archive Integration

### web_archive_utils

Module for working with web archives.

#### Functions

##### `index_warc(warc_file, output_path=None)`

Index a WARC file using IPWB.

**Parameters:**
- `warc_file` (str): Path to WARC file
- `output_path` (str): Path to save CDXJ index

**Returns:**
- Path to CDXJ index

##### `extract_dataset_from_cdxj(cdxj_path)`

Extract a dataset from a CDXJ index.

**Parameters:**
- `cdxj_path` (str): Path to CDXJ index

**Returns:**
- Dataset object

##### `query_wayback_machine(url, from_date=None, to_date=None)`

Query Internet Archive Wayback Machine.

**Parameters:**
- `url` (str): URL to query
- `from_date` (str): Start date
- `to_date` (str): End date

**Returns:**
- List of capture information

---

## Operations and Management

### data_provenance

Module for tracking data provenance and lineage.

#### Classes

##### `ProvenanceManager`

Base class for tracking data provenance.

**Methods:**

- `record_source(output_id, source_type, **kwargs)`: Record a data source
- `record_transformation(input_ids, output_id, transformation_type, **kwargs)`: Record a transformation
- `record_merge(input_ids, output_id, merge_type, **kwargs)`: Record a merge operation
- `record_query(input_ids, query_text, **kwargs)`: Record a query operation
- `get_lineage(data_id)`: Get the lineage for a data entity
- `visualize(data_ids, file_path=None)`: Visualize the provenance graph

##### `EnhancedProvenanceManager`

Enhanced version of the provenance manager with advanced features.

**Methods:**

- All methods from `ProvenanceManager`
- `record_verification(data_id, verification_type, **kwargs)`: Record a verification operation
- `record_annotation(data_id, annotation_type, content, **kwargs)`: Record an annotation
- `semantic_search(query, limit=10)`: Search records by semantic similarity
- `temporal_query(start_time, end_time=None, **kwargs)`: Query records by time

### cross_document_lineage

Module for tracking detailed data lineage across document and domain boundaries, with enhanced capabilities for domain-based organization, detailed transformation tracking, version awareness, temporal consistency checks, and IPLD integration.

#### Overview

The cross_document_lineage module provides a comprehensive framework for tracking data as it flows across document boundaries and multiple domains. It enables enhanced visibility into data transformations, with support for detailed lineage tracking at multiple levels of granularity, from field-level impacts to complete document lineage. The module integrates with both audit logging and IPLD storage to provide a complete provenance tracking solution.

Key features:
- Domain-based organization with hierarchical structure
- Detailed transformation decomposition and tracking
- Version-aware lineage with temporal consistency checks
- Semantic relationship detection and confidence scoring
- Bidirectional audit trail integration
- IPLD-based content-addressable storage
- Flexible query capabilities with path and subgraph extraction
- Visualization tools for complex lineage graphs
- Impact and dependency analysis

#### Classes

##### `LineageDomain`

Represents a logical domain in the data lineage graph for organizing lineage data in a structured, hierarchical manner.

**Attributes:**

- `domain_id`: Unique identifier for the domain
- `name`: Name of the domain
- `description`: Optional description
- `domain_type`: Type of domain (generic, application, dataset, workflow, etc.)
- `attributes`: Additional domain attributes for domain-specific metadata
- `metadata_schema`: Optional validation schema for metadata to enforce consistency
- `parent_domain_id`: Optional parent domain ID for hierarchical domains
- `timestamp`: Creation timestamp for temporal analysis

##### `LineageBoundary`

Represents a boundary between domains in the lineage graph, defining how data flows across domain boundaries with appropriate constraints and security properties.

**Attributes:**

- `boundary_id`: Unique identifier for the boundary
- `source_domain_id`: Source domain ID for the data flow origin
- `target_domain_id`: Target domain ID for the data flow destination
- `boundary_type`: Type of boundary (data_transfer, api_call, etl_process, etc.)
- `attributes`: Additional boundary attributes such as security properties, permissions, etc.
- `constraints`: Boundary constraints defining rules for cross-domain data flow
- `timestamp`: Creation timestamp for temporal analysis

##### `LineageNode`

Represents a node in the data lineage graph, representing datasets, transformations, or other data artifacts.

**Attributes:**

- `node_id`: Unique identifier for the node
- `node_type`: Type of node (dataset, transformation, query, result, etc.)
- `entity_id`: Optional entity ID for linking to external systems or specific data entities
- `record_type`: Optional record type for compatibility with provenance records
- `metadata`: Node metadata containing detailed information about the artifact
- `timestamp`: Creation timestamp for temporal consistency checking

##### `LineageLink`

Represents a link in the data lineage graph, connecting nodes with typed relationships and confidence scoring.

**Attributes:**

- `source_id`: Source node ID representing the origin of the relationship
- `target_id`: Target node ID representing the destination of the relationship
- `relationship_type`: Type of relationship (input_to, output_from, derived_from, etc.)
- `confidence`: Confidence score (0.0-1.0) indicating certainty of the relationship
- `metadata`: Link metadata containing additional information about the relationship
- `timestamp`: Creation timestamp for temporal ordering
- `direction`: Link direction (forward, backward, bidirectional) for flexible traversal

##### `LineageTransformationDetail`

Detailed representation of a transformation operation in lineage tracking, providing fine-grained information about data transformations at field, record, or dataset level.

**Attributes:**

- `detail_id`: Unique identifier for the detail
- `transformation_id`: ID of the parent transformation node
- `operation_type`: Type of operation (filter, join, aggregate, map, etc.)
- `inputs`: Input field mappings with data types and specifications
- `outputs`: Output field mappings with transformed data types and specifications
- `parameters`: Operation parameters describing the transformation configuration
- `impact_level`: Level of impact (field, record, dataset, etc.) for granular tracking
- `confidence`: Confidence score for this transformation detail
- `timestamp`: Creation timestamp for temporal ordering

##### `LineageVersion`

Represents a version of a node in the lineage graph, enabling version-aware lineage tracking with complete history and change tracking.

**Attributes:**

- `version_id`: Unique identifier for the version
- `node_id`: ID of the versioned node
- `version_number`: Version identifier (semantic versioning recommended)
- `parent_version_id`: Optional previous version ID for establishing version history
- `change_description`: Optional description of changes made in this version
- `creator_id`: Optional ID of the version creator for attribution
- `attributes`: Additional version attributes for custom version metadata
- `timestamp`: Creation timestamp for temporal ordering and analysis

##### `LineageSubgraph`

Represents a subgraph in the data lineage graph, used for query results, visualization, and analysis of specific lineage paths or portions.

**Attributes:**

- `nodes`: Dictionary of nodes in the subgraph mapping node IDs to LineageNode objects
- `links`: List of links in the subgraph as LineageLink objects
- `root_id`: Root node ID that serves as the entry point for traversal
- `domains`: Optional dictionary of domains included in this subgraph for domain-aware analysis
- `boundaries`: Optional list of boundaries between domains to track cross-domain flows
- `transformation_details`: Optional dictionary of transformation details for detailed operation tracking
- `versions`: Optional dictionary of versions for version-aware analysis
- `metadata`: Subgraph metadata containing summary information and statistics
- `extraction_criteria`: Criteria used to extract this subgraph for reproducing the query

##### `EnhancedLineageTracker`

Enhanced lineage tracking for comprehensive data provenance.

**Methods:**

- `create_domain(name, description=None, domain_type="generic", attributes=None, metadata_schema=None, parent_domain_id=None)`: Create a new domain
- `create_domain_boundary(source_domain_id, target_domain_id, boundary_type, attributes=None, constraints=None)`: Create a boundary between domains
- `create_node(node_type, metadata=None, domain_id=None, entity_id=None)`: Create a new node
- `create_link(source_id, target_id, relationship_type, metadata=None, confidence=1.0, direction="forward", cross_domain=False)`: Create a link between nodes
- `record_transformation_details(transformation_id, operation_type, inputs, outputs, parameters=None, impact_level="field", confidence=1.0)`: Record detailed transformation information
- `create_version(node_id, version_number, change_description=None, parent_version_id=None, creator_id=None, attributes=None)`: Create a new version of a node
- `extract_subgraph(root_id, max_depth=3, direction="both", include_domains=True, include_versions=False, include_transformation_details=False, relationship_types=None, domain_filter=None)`: Extract a subgraph
- `query_lineage(query)`: Execute a query against the lineage graph
- `find_paths(start_node_id, end_node_id, max_depth=10, relationship_filter=None)`: Find all paths between two nodes
- `detect_semantic_relationships(confidence_threshold=0.7, max_candidates=100)`: Detect semantic relationships between nodes
- `export_to_ipld(include_domains=True, include_versions=False, include_transformation_details=False)`: Export the lineage graph to IPLD
- `from_ipld(root_cid, ipld_storage=None, config=None)`: Create an instance from an IPLD-stored lineage graph
- `visualize_lineage(subgraph=None, output_path=None, visualization_type="interactive", include_domains=True)`: Visualize the lineage graph
- `merge_lineage(other_tracker, conflict_resolution="newer", allow_domain_merging=True)`: Merge another lineage tracker into this one
- `validate_temporal_consistency()`: Validate temporal consistency across the graph
- `apply_metadata_inheritance()`: Apply metadata inheritance rules
- `add_metadata_inheritance_rule(source_type, target_type, properties, condition=None, override=False)`: Add a rule for metadata inheritance
- `get_entity_lineage(entity_id, include_semantic=True)`: Get complete lineage for a specific entity
- `generate_provenance_report(entity_id=None, node_id=None, include_visualization=True, format="json")`: Generate a comprehensive provenance report

##### `LineageMetrics`

Calculate metrics for data lineage analysis.

**Methods:**

- `calculate_impact_score(graph, node_id)`: Calculate the impact score of a node
- `calculate_dependency_score(graph, node_id)`: Calculate the dependency score of a node
- `calculate_centrality(graph, node_type=None)`: Calculate centrality metrics for nodes
- `identify_critical_paths(graph)`: Identify critical paths in the lineage graph
- `calculate_complexity(graph, node_id)`: Calculate complexity metrics for a node's lineage

### monitoring

Module for monitoring system operations.

#### Classes

##### `MonitoringSystem`

System for monitoring operations.

**Methods:**
- `__init__(self, config=None)`: Initialize monitoring system
- `configure_logging(self, log_level='INFO', log_file=None)`: Configure logging
- `record_metric(self, metric_name, value, tags=None)`: Record a metric
- `get_metrics(self, metric_name=None, start_time=None, end_time=None)`: Get metrics
- `set_alert(self, metric_name, condition, threshold, action=None)`: Set alert
- `start_profiling(self, name=None)`: Start profiling
- `end_profiling(self, name=None)`: End profiling
- `get_profile_data(self, name=None)`: Get profiling data
- `get_health_status(self)`: Get system health status
- `export_metrics(self, format='json', output_path=None)`: Export metrics

---

### security

Module for security and governance.

#### Classes

##### `SecurityManager`

Manager for security features.

**Methods:**
- `__init__(self, config=None)`: Initialize security manager
- `configure(self, config=None)`: Configure security settings
- `create_user(self, username, password, role='user')`: Create user
- `authenticate_user(self, username, password)`: Authenticate user
- `encrypt_data(self, data, key_id=None)`: Encrypt data
- `decrypt_data(self, encrypted_data, key_id=None)`: Decrypt data
- `encrypt_file(self, file_path, output_path=None, key_id=None)`: Encrypt file
- `decrypt_file(self, file_path, output_path=None, key_id=None)`: Decrypt file
- `create_resource_policy(self, resource_id, policy)`: Create resource policy
- `check_access(self, user_id, resource_id, access_type)`: Check access
- `record_provenance(self, data_id, operation, metadata=None)`: Record provenance
- `get_provenance(self, data_id)`: Get data provenance
- `get_audit_logs(self, filters=None)`: Get audit logs

#### Decorators

##### `require_authentication(func)`

Decorator to require authentication.

##### `require_access(resource_id_param, access_type)`

Decorator to require resource access.

#### Context Managers

##### `encrypted_context(data_or_file, key_id=None)`

Context manager for working with encrypted data.

---

### resilient_operations

Module for resilient operations against node failures.

#### Classes

##### `ResilienceManager`

Manager for resilient operations.

**Methods:**
- `__init__(self, config=None)`: Initialize resilience manager
- `configure(self, config=None)`: Configure resilience settings
- `register_node(self, node_id, capabilities=None)`: Register a node
- `execute_with_retry(self, operation, max_retries=3)`: Execute with retry
- `execute_with_fallback(self, operations)`: Execute with fallback
- `distribute_operation(self, operation, node_selection='round_robin')`: Distribute operation
- `monitor_operation(self, operation_id)`: Monitor operation status
- `checkpoint_operation(self, operation_id, state)`: Create operation checkpoint
- `recover_operation(self, operation_id)`: Recover operation from checkpoint
- `get_node_status(self, node_id=None)`: Get node status

---

### admin_dashboard

Module for administration dashboards.

#### Classes

##### `AdminDashboard`

Dashboard for system administration.

**Methods:**
- `__init__(self, config=None)`: Initialize dashboard
- `configure(self, config=None)`: Configure dashboard
- `register_component(self, component_id, component)`: Register component
- `get_system_metrics(self, start_time=None, end_time=None)`: Get system metrics
- `get_storage_stats(self)`: Get storage statistics
- `get_node_stats(self)`: Get node statistics
- `get_dataset_stats(self, dataset_id=None)`: Get dataset statistics
- `get_user_stats(self)`: Get user statistics
- `get_security_logs(self, start_time=None, end_time=None)`: Get security logs
- `generate_report(self, report_type, parameters=None)`: Generate report
- `export_dashboard_data(self, format='json', output_path=None)`: Export dashboard data

---

### streaming_data_loader

Module for streaming data loading.

#### Classes

##### `StreamingLoader`

Loader for streaming data.

**Methods:**
- `__init__(self, batch_size=1000, max_workers=4)`: Initialize loader
- `stream_from_file(self, file_path, processor=None)`: Stream from file
- `stream_from_url(self, url, processor=None)`: Stream from URL
- `stream_from_ipfs(self, cid, processor=None)`: Stream from IPFS
- `stream_with_checkpoint(self, source, checkpoint_interval=1000)`: Stream with checkpointing
- `resume_from_checkpoint(self, checkpoint_file)`: Resume from checkpoint

---

### federated_search

Module for federated search across distributed datasets.

#### Classes

##### `FederatedSearchEngine`

Engine for federated search.

**Methods:**
- `__init__(self, config=None)`: Initialize search engine
- `register_dataset(self, dataset_id, dataset_info)`: Register a dataset
- `register_node(self, node_id, node_info)`: Register a node
- `search(self, query, dataset_ids=None, node_ids=None)`: Perform search
- `distribute_query(self, query, dataset_ids, node_ids)`: Distribute query
- `collect_results(self, query_id, timeout=30)`: Collect search results
- `merge_results(self, results, strategy='score')`: Merge results
- `get_dataset_info(self, dataset_id=None)`: Get dataset information
- `get_node_info(self, node_id=None)`: Get node information

---

## Configuration

### config

Module for configuration management.

#### Functions

##### `load_config(config_path=None)`

Load configuration from file.

**Parameters:**
- `config_path` (str): Path to configuration file

**Returns:**
- Configuration object

##### `get_config_value(key, default=None)`

Get a specific configuration value.

**Parameters:**
- `key` (str): Configuration key
- `default`: Default value if key not found

**Returns:**
- Configuration value

##### `set_config_value(key, value)`

Set a specific configuration value.

**Parameters:**
- `key` (str): Configuration key
- `value`: Value to set

**Returns:**
- None

##### `save_config(config, config_path=None)`

Save configuration to file.

**Parameters:**
- `config`: Configuration object
- `config_path` (str): Path to save configuration

**Returns:**
- None