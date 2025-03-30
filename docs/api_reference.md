# IPFS Datasets Python - API Reference

This documentation provides detailed information about the modules, classes, and functions available in the IPFS Datasets Python package.

## Table of Contents

1. [Core Modules](#core-modules)
   - [ipfs_datasets](#ipfs_datasets)
   - [dataset_serialization](#dataset_serialization)
   - [car_conversion](#car_conversion)
   - [ipfs_parquet_to_car](#ipfs_parquet_to_car)
   
2. [IPLD Integration](#ipld-integration)
   - [ipld.storage](#ipld-storage)
   - [ipld.dag_pb](#ipld-dag_pb)
   - [unixfs_integration](#unixfs_integration)
   
3. [Vector Storage and Search](#vector-storage-and-search)
   - [ipfs_knn_index](#ipfs_knn_index)
   - [ipfs_embeddings_py](#ipfs_embeddings_py)

4. [Graph-Based RAG](#graph-based-rag)
   - [knowledge_graph_extraction](#knowledge_graph_extraction)
   - [llm_graphrag](#llm_graphrag)
   - [rag_query_optimizer](#rag_query_optimizer)
   - [llm_reasoning_tracer](#llm_reasoning_tracer)
   - [llm_semantic_validation](#llm_semantic_validation)

5. [Web Archive Integration](#web-archive-integration)
   - [web_archive_utils](#web_archive_utils)

6. [Operations and Management](#operations-and-management)
   - [monitoring](#monitoring)
   - [security](#security)
   - [resilient_operations](#resilient_operations)
   - [admin_dashboard](#admin_dashboard)
   - [streaming_data_loader](#streaming_data_loader)
   - [federated_search](#federated_search)

7. [Configuration](#configuration)
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