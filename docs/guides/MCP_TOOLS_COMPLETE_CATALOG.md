# MCP Tools Complete Catalog

## Detailed Tool Inventory

This document provides a complete catalog of all MCP tools available in the `ipfs_datasets_py` project, organized by category with specific function names and descriptions.

---

## 🗂️ Dataset Tools (15 tools)

### Core Dataset Operations
1. **`load_dataset`** - Load datasets from various sources (HF Hub, files, URLs)
2. **`process_dataset`** - Apply transformations, filters, and operations to datasets
3. **`save_dataset`** - Save datasets to various destinations and formats
4. **`convert_dataset_format`** - Convert datasets between different formats

### Dataset Processing Tools from Claude's Toolbox
5. **`ClaudesDatasetTool`** - Dataset operations migrated from claudes_toolbox-1
6. **`dataset_tools_claudes`** - Claude's original dataset manipulation functions

---

## 📦 IPFS Tools (12 tools)

### Basic IPFS Operations
1. **`pin_to_ipfs`** - Pin files, directories, or data to IPFS network
2. **`get_from_ipfs`** - Retrieve content from IPFS by CID
3. **`ClaudesIPFSTool`** - IPFS operations migrated from claudes_toolbox-1
4. **`ipfs_tools_claudes`** - Claude's original IPFS functions

### IPFS Cluster Management
5. **`get_cluster_status`** - Get IPFS cluster status and node information
6. **`add_node`** - Add nodes to IPFS cluster
7. **`remove_node`** - Remove nodes from IPFS cluster
8. **`pin_content`** - Pin content across cluster with replication
9. **`unpin_content`** - Remove pins from cluster
10. **`list_pins`** - List pinned content with status filtering
11. **`sync_cluster`** - Synchronize cluster state across nodes
12. **Enhanced IPFS Cluster Tools** - Advanced cluster management wrapper

---

## 🧮 Embedding Tools (25+ tools)

### Basic Embedding Generation
1. **`generate_embedding`** - Generate embeddings for single text inputs
2. **`generate_batch_embeddings`** - Generate embeddings for multiple texts efficiently
3. **`generate_embeddings_from_file`** - Generate embeddings from file contents

### Advanced Embedding Operations
4. **`shard_embeddings_by_dimension`** - Shard large embedding collections by dimensions
5. **`shard_embeddings_by_cluster`** - Shard embeddings based on clustering results
6. **`merge_embedding_shards`** - Combine sharded embeddings back into unified collections

### Enhanced Embedding Tools
7. **`create_embeddings`** - Advanced embedding creation with multiple models
8. **`index_dataset`** - Index datasets for embedding-based search
9. **`search_embeddings`** - Perform semantic search across embedding collections
10. **`chunk_text`** - Intelligent text chunking for embeddings
11. **`manage_endpoints`** - Manage embedding service endpoints and models

### Advanced Search Operations
12. **`semantic_search`** - Advanced semantic search with ranking
13. **`multi_modal_search`** - Search across text, image, and other modalities
14. **`hybrid_search`** - Combine semantic and keyword search
15. **`search_with_filters`** - Search with advanced filtering options

### Sparse Embedding Tools
16. **`generate_sparse_embedding`** - Generate sparse embeddings (SPLADE, etc.)
17. **`index_sparse_collection`** - Index sparse embedding collections
18. **`sparse_search`** - Search sparse embedding indices
19. **`manage_sparse_models`** - Manage sparse embedding models

### Vector Store Management
20. **`manage_vector_store`** - Manage vector store operations
21. **`optimize_vector_store`** - Optimize vector store performance

### Cluster Management for Embeddings
22. **`cluster_management`** - Manage embedding clusters and assignments

### Embedding Tools Registration
23. **`tool_registration`** - Register embedding tools with MCP system

### Legacy Embedding Tools
24. **`advanced_embedding_generation`** - Legacy advanced embedding functions
25. **`embedding_generation`** - Legacy basic embedding functions

---

## 🔍 Vector Tools (15 tools)

### Vector Index Management
1. **`create_vector_index`** - Create vector indices for similarity search
2. **`search_vector_index`** - Search vector indices for similar items
3. **`vector_store_management`** - Advanced vector store operations and management

### Backend-Specific Operations
4. **`_create_faiss_index`** - Create FAISS-based vector indices
5. **`_create_qdrant_index`** - Create Qdrant-based vector indices
6. **`_create_elasticsearch_index`** - Create Elasticsearch-based vector indices
7. **`_search_faiss_index`** - Search FAISS indices
8. **`list_vector_indexes`** - List available vector indices
9. **`delete_vector_index`** - Delete vector indices

### Enhanced Vector Store Tools
10. **`enhanced_vector_store_tools`** - Advanced vector store management

### Index Management Tools
11. **`load_index`** - Load and initialize vector indices from storage
12. **`manage_shards`** - Manage vector index shards
13. **`monitor_index_status`** - Monitor index health and performance
14. **`manage_index_configuration`** - Configure index parameters

### Shared State Management
15. **`shared_state`** - Manage shared state across vector operations

---

## 📊 Analytics Tools (8 tools)

### Data Analysis
1. **`cluster_analysis`** - Perform clustering analysis on datasets and embeddings
2. **`quality_assessment`** - Assess data quality and embedding quality
3. **`dimensionality_reduction`** - Reduce dimensionality for visualization and analysis
4. **`analyze_data_distribution`** - Analyze statistical distributions in datasets

### Analysis Tools Integration
5. **`analysis_tools`** - Comprehensive analytics tool suite

### Specialized Analysis
6. **Data drift detection** - Monitor data distribution changes over time
7. **Similarity analysis** - Analyze similarity patterns in datasets
8. **Performance analytics** - Analyze system and model performance

---

## 🔄 Workflow Tools (12 tools)

### Workflow Management
1. **`execute_workflow`** - Execute complex multi-step workflows
2. **`batch_process_datasets`** - Process multiple datasets in batch operations
3. **`schedule_workflow`** - Schedule workflows for future execution
4. **`get_workflow_status`** - Monitor workflow execution status

### Enhanced Workflow Operations
5. **`create_workflow`** - Create workflow definitions
6. **`list_workflows`** - List available workflows with filtering

### Step Execution Functions
7. **`_execute_embedding_step`** - Execute embedding-related workflow steps
8. **`_execute_dataset_step`** - Execute dataset processing steps
9. **`_execute_vector_step`** - Execute vector operation steps
10. **`_execute_ipfs_step`** - Execute IPFS-related steps
11. **`_execute_conditional_step`** - Execute conditional logic steps
12. **`_execute_parallel_step`** - Execute parallel processing steps

---

## 📈 Monitoring Tools (15+ tools)

### System Monitoring
1. **`health_check`** - Comprehensive system health monitoring
2. **`get_performance_metrics`** - Collect detailed performance metrics
3. **`monitor_services`** - Monitor specific service status and performance
4. **`generate_monitoring_report`** - Generate comprehensive monitoring reports

### Enhanced Monitoring
5. **`get_system_metrics`** - Get detailed system metrics
6. **`get_service_metrics`** - Get service-specific metrics
7. **`check_health`** - Advanced health checking with service inclusion
8. **`get_alerts`** - Retrieve system alerts with filtering
9. **`collect_metrics`** - Collect metrics with time windows and aggregation

### Specialized Health Checks
10. **`_check_system_health`** - System-level health verification
11. **`_check_memory_health`** - Memory usage and availability checks
12. **`_check_cpu_health`** - CPU utilization and performance checks
13. **`_check_disk_health`** - Disk space and I/O health checks
14. **`_check_network_health`** - Network connectivity and performance checks
15. **`_check_services_health`** - Service availability and status checks
16. **`_check_embeddings_health`** - Embedding service health checks
17. **`_check_vector_stores_health`** - Vector store health monitoring

---

## 🔐 Security & Authentication Tools (12 tools)

### Authentication
1. **`authenticate_user`** - Authenticate users with various methods
2. **`validate_token`** - Validate authentication tokens and permissions
3. **`get_user_info`** - Get user information from tokens
4. **`check_access_permission`** - Check user permissions for resources

### Enhanced Authentication
5. **`authenticate`** - Enhanced authentication with multiple methods
6. **`get_user_from_token`** - Extract user details from authentication tokens
7. **`refresh_token`** - Refresh authentication tokens
8. **`decode_token`** - Decode and validate JWT tokens

### Auth Tools (Class-based)
9. **`AuthenticationService`** - Comprehensive authentication service
10. **`EnhancedAuthenticationTool`** - Enhanced authentication wrapper
11. **`TokenValidationTool`** - Token validation wrapper
12. **`UserInfoTool`** - User information retrieval wrapper

---

## ⚙️ Administrative Tools (15 tools)

### System Administration
1. **`manage_endpoints`** - Manage system endpoints and services
2. **`system_maintenance`** - Perform system maintenance tasks
3. **`configure_system`** - Configure system settings and parameters

### Enhanced Admin Operations
4. **`get_system_status`** - Get comprehensive system status
5. **`manage_service`** - Manage individual services (start/stop/restart)
6. **`update_configuration`** - Update system configuration with backup
7. **`cleanup_resources`** - Clean up system resources and temporary files

### Admin Tool Wrappers
8. **`SystemStatusTool`** - System status monitoring wrapper
9. **`ServiceManagementTool`** - Service management wrapper
10. **`ConfigurationUpdateTool`** - Configuration management wrapper
11. **`ResourceCleanupTool`** - Resource cleanup wrapper

### Administrative Functions
12. **User management** - Manage user accounts and permissions
13. **Resource quotas** - Manage storage and compute quotas
14. **Backup operations** - System backup and restore
15. **Log management** - Manage system logs and rotation

---

## 🛠️ Development Tools (20+ tools)

### Testing and Quality Assurance
1. **`run_comprehensive_tests`** - Execute comprehensive test suites
2. **`create_test_runner`** - Create and configure test runners
3. **`TestRunner`** - Comprehensive test runner for Python projects
4. **`DatasetTestRunner`** - Specialized test runner for dataset functionality
5. **`TestExecutor`** - Core test execution functionality

### Code Quality and Analysis
6. **`lint_codebase`** - Perform code quality analysis and linting
7. **`LintingTool`** - Advanced linting with multiple tools
8. **`codebase_search`** - Search and analyze codebase structure

### Documentation and Code Generation
9. **`documentation_generator`** - Generate documentation from code
10. **`documentation_generator_simple`** - Simplified documentation generator
11. **`test_generator`** - Generate test cases from code analysis

### Development Tool Infrastructure
12. **`base_tool`** - Base class for all development tools
13. **`BaseDevelopmentTool`** - Enhanced base development tool
14. **`development_tool_mcp_wrapper`** - MCP wrapper for development tools

### Test Result Management
15. **`TestResult`** - Individual test result management
16. **`TestSuiteResult`** - Test suite result aggregation
17. **`TestRunSummary`** - Complete test run summaries

### Configuration and Setup
18. **`config`** - Development tool configuration
19. **Development environment setup** - Environment configuration tools
20. **CI/CD integration** - Continuous integration tools

---

## 🎯 Specialized Tools (25+ tools)

### Web Archive Tools
1. **`create_warc`** - Create Web ARChive (WARC) files
2. **`extract_text_from_warc`** - Extract text content from WARC files
3. **`extract_links_from_warc`** - Extract links and relationships from WARC files
4. **`extract_metadata_from_warc`** - Extract metadata from WARC files
5. **`index_warc`** - Index WARC files for search
6. **`extract_dataset_from_cdxj`** - Extract datasets from CDXJ index files

### Session Management Tools
7. **`create_session`** - Create and manage user sessions
8. **`manage_session_state`** - Manage session state and data
9. **`cleanup_sessions`** - Clean up expired sessions
10. **`EnhancedSessionTool`** - Enhanced session management wrapper

### Background Task Management
11. **`check_task_status`** - Check background task status
12. **`manage_background_tasks`** - Manage background task lifecycle
13. **`manage_task_queue`** - Manage task queues and priorities
14. **`EnhancedBackgroundTaskTool`** - Enhanced background task management

### Provenance and Audit Tools
15. **`record_provenance`** - Record data provenance and lineage
16. **`record_audit_event`** - Record audit events for compliance
17. **`generate_audit_report`** - Generate comprehensive audit reports
18. **`ClaudesProvenanceTool`** - Provenance tools from Claude's toolbox
19. **`AuditTool`** - Comprehensive audit functionality

### Cache Management Tools
20. **`manage_cache`** - Manage system caches
21. **`optimize_cache`** - Optimize cache performance
22. **`cache_embeddings`** - Cache embeddings for faster access
23. **`get_cached_embeddings`** - Retrieve cached embeddings
24. **`EnhancedCacheManager`** - Advanced cache management

### Data Processing Tools
25. **`chunk_text`** - Advanced text chunking strategies
26. **`transform_data`** - Data transformation operations
27. **`convert_format`** - Format conversion utilities
28. **`validate_data`** - Data validation tools

### Storage Tools
29. **`store_data`** - Store data in various backends
30. **`retrieve_data`** - Retrieve stored data
31. **`manage_collections`** - Manage data collections
32. **`query_storage`** - Query storage systems

### Command Line Interface Tools
33. **`execute_command`** - Execute system commands safely

### Knowledge Graph Tools
34. **`query_knowledge_graph`** - Query knowledge graphs with SPARQL/Cypher

### Rate Limiting Tools
35. **`rate_limiting_tools`** - Implement rate limiting for API calls

### Function Execution Tools
36. **`execute_python_snippet`** - Execute Python code snippets safely

---

## 🔧 FastAPI Integration Tools (8 tools)

### API Integration
1. **`FastAPIIntegration`** - Complete FastAPI service integration
2. **`startup_event`** - API startup event handlers
3. **`root`** - Root endpoint handler
4. **`list_tools`** - List available tools via API
5. **`get_tool_info`** - Get tool information via API
6. **`execute_tool`** - Execute tools via API
7. **`list_categories`** - List tool categories
8. **`health_check`** - API health check endpoint

---

## 📝 Tool Registration and Management (5 tools)

### Registration System
1. **`tool_registration`** - Main tool registration system
2. **`MCPToolRegistry`** - Tool registry management
3. **`tool_wrapper`** - Tool wrapper utilities
4. **`BaseMCPTool`** - Base MCP tool interface
5. **`get_global_manager`** - Global tool manager access

---

## 🔄 Migration and Integration Tools (5 tools)

### Legacy Integration
1. **`ipfs_embeddings_integration`** - Integration with ipfs_embeddings_py
2. **Migration completion tools** - Tools for handling migration status
3. **Compatibility wrappers** - Wrappers for legacy tool compatibility
4. **Feature flag management** - Manage feature flags for gradual rollout
5. **Integration validators** - Validate integration completeness

---

## Summary Statistics

- **Total MCP Tools**: 140+ individual tools
- **Tool Categories**: 12 major categories
- **Core Function Coverage**: 
  - Dataset operations: 15 tools
  - IPFS operations: 12 tools  
  - Embedding operations: 25+ tools
  - Vector operations: 15 tools
  - Monitoring: 15+ tools
  - Security: 12 tools
  - Admin: 15 tools
  - Development: 20+ tools
  - Specialized: 25+ tools

## Tool Naming Conventions

### Function Patterns
- **Async Functions**: All tools are async (`async def tool_name`)
- **MCP Registration**: Tools prefixed with `mcp_ipfs-datasets2_`
- **Enhanced Tools**: Advanced versions often named `enhanced_*_tools`
- **Legacy Tools**: Claude's original tools often suffixed with `_claudes`

### Parameter Patterns
- **Required Parameters**: Core functionality parameters
- **Optional Parameters**: Configuration and customization options
- **Return Format**: Standardized `Dict[str, Any]` with status, data, metadata

### Integration Patterns
- **Class-Based Tools**: Inherit from `BaseMCPTool` or `BaseDevelopmentTool`
- **Function-Based Tools**: Direct async functions for simple operations
- **Wrapper Tools**: Enhanced functionality wrapping core operations

This comprehensive catalog provides complete coverage of all MCP tools available in the `ipfs_datasets_py` project, enabling effective discovery and usage by AI assistants and developers.
