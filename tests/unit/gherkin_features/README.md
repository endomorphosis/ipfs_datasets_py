# Gherkin Feature Files for IPFS Datasets

This directory contains Gherkin feature files for all modules in the `ipfs_datasets_py` subdirectory.

## Overview

These feature files follow the Gherkin syntax (Given-When-Then) and are designed to:
- Describe module behavior in a human-readable format
- Support black-box testing without implementation details
- Follow DRY (Don't Repeat Yourself) principle
- Follow SRP (Single Responsibility Principle)
- Exclude adverbs and implementation-specific language

## Structure

Each `.feature` file corresponds to a Python module in `ipfs_datasets_py/` and contains:
- **Feature**: High-level description of the module's functionality
- **Scenarios**: Specific test cases for module behaviors
- **Given**: Initial context or state
- **When**: Action or trigger
- **Then**: Expected outcome

## File Naming

Feature files are named to match their corresponding Python modules:
- `config.py` → `config.feature`
- `dataset_manager.py` → `dataset_manager.feature`
- etc.

## Usage

These Gherkin files serve as:
1. **Documentation**: Human-readable specification of module behavior
2. **Test Planning**: Blueprint for implementing actual tests
3. **Requirements**: Clear definition of expected functionality
4. **Communication**: Common language between developers, testers, and stakeholders

## Implementing Tests

To implement tests from these Gherkin scenarios:

1. Choose a BDD framework (e.g., `pytest-bdd`, `behave`)
2. Create step definitions that map to Given/When/Then statements
3. Implement the actual test code
4. Run tests against the implementation

Example with pytest-bdd:
```python
from pytest_bdd import scenario, given, when, then

@scenario('config.feature', 'Load configuration from default location')
def test_load_config_default():
    pass

@given('a valid config.toml file exists in the default path')
def default_config():
    # Setup code
    pass

@when('the configuration is initialized')
def init_config():
    # Action code
    pass

@then('the configuration is loaded')
def verify_config_loaded():
    # Assertion code
    pass
```

## Module Coverage

All 71 Python modules in `ipfs_datasets_py/` have corresponding feature files:

### Core Modules
- `config.feature` - Configuration management
- `audit.feature` - Audit logging
- `dataset_manager.feature` - Dataset lifecycle management
- `security.feature` - Security and access control
- `ucan.feature` - UCAN authorization

### Data Processing
- `car_conversion.feature` - CAR file conversion
- `dataset_serialization.feature` - Dataset serialization
- `jsonl_to_parquet.feature` - JSONL to Parquet conversion
- `ipfs_parquet_to_car.feature` - Parquet to CAR conversion

### IPFS Integration
- `ipfs_datasets.feature` - Core IPFS dataset operations
- `ipfs_multiformats.feature` - Content identifier generation
- `ipfs_knn_index.feature` - KNN search on IPFS
- `unixfs_integration.feature` - UnixFS file system

### Knowledge and Reasoning
- `knowledge_graph_extraction.feature` - Knowledge graph extraction
- `graphrag_integration.feature` - GraphRAG integration
- `graphrag_processor.feature` - GraphRAG processing
- `cross_document_reasoning.feature` - Cross-document reasoning
- `deontological_reasoning.feature` - Ethical reasoning

### Web and Archiving
- `web_archive.feature` - Web archiving
- `web_text_extractor.feature` - Text extraction from web
- `simple_crawler.feature` - Web crawling
- `advanced_web_archiving.feature` - Enhanced web archiving
- `web_archive_utils.feature` - Web archive utilities

### Multimedia
- `multimodal_processor.feature` - Multimodal processing
- `advanced_media_processing.feature` - Advanced media processing
- `enhanced_multimodal_processor.feature` - Enhanced multimodal processing

### Dashboards and Visualization
- `admin_dashboard.feature` - Admin interface
- `provenance_dashboard.feature` - Provenance visualization
- `monitoring.feature` - System monitoring
- `unified_monitoring_dashboard.feature` - Unified monitoring
- `mcp_dashboard.feature` - MCP monitoring
- `advanced_analytics_dashboard.feature` - Analytics visualization
- `news_analysis_dashboard.feature` - News analysis
- `patent_dashboard.feature` - Patent analysis
- `enhanced_rag_visualization.feature` - RAG visualization

### Performance and Optimization
- `performance_optimizer.feature` - Performance optimization
- `advanced_performance_optimizer.feature` - Advanced optimization
- `query_optimizer.feature` - Query optimization
- `resilient_operations.feature` - Fault-tolerant operations
- `streaming_data_loader.feature` - Streaming data loading

### API and Services
- `fastapi_service.feature` - FastAPI service
- `fastapi_config.feature` - FastAPI configuration
- `enterprise_api.feature` - Enterprise API

### Infrastructure
- `auto_installer.feature` - Dependency installation
- `libp2p_kit.feature` - LibP2P networking
- `libp2p_kit_full.feature` - Full LibP2P implementation
- `libp2p_kit_stub.feature` - LibP2P stub
- `s3_kit.feature` - S3 storage operations

### Advanced Features
- `vector_tools.feature` - Vector operations
- `content_discovery.feature` - Content discovery
- `jsonnet_utils.feature` - Jsonnet templating
- `sparql_query_templates.feature` - SPARQL queries
- `intelligent_recommendation_engine.feature` - Recommendations

### Website Processing
- `website_graphrag_processor.feature` - Website GraphRAG processing
- `website_graphrag_system.feature` - Website GraphRAG system
- `advanced_graphrag_website_processor.feature` - Advanced website processing
- `graphrag_website_example.feature` - GraphRAG examples

### Data Lineage and Provenance
- `data_provenance.feature` - Data provenance tracking
- `data_provenance_enhanced.feature` - Enhanced provenance
- `cross_document_lineage.feature` - Document lineage
- `cross_document_lineage_enhanced.feature` - Enhanced lineage

### Integration and Examples
- `complete_advanced_graphrag.feature` - Complete GraphRAG system
- `enhanced_graphrag_integration.feature` - Enhanced GraphRAG integration
- `phase7_complete_integration.feature` - Phase 7 integration
- `monitoring_example.feature` - Monitoring examples

### Specialized Tools
- `wikipedia_rag_optimizer.feature` - Wikipedia RAG optimization
- `mcp_investigation_dashboard.feature` - MCP investigation
- `investigation_mcp_client.feature` - MCP client

### Package Management
- `__init__.feature` - Package initialization
- `_dependencies.feature` - Dependency management

## Guidelines for Scenarios

When writing or reading these scenarios, remember:

1. **No Implementation Details**: Scenarios describe "what" not "how"
2. **Black Box Testing**: Only observable behavior is tested
3. **No Adverbs**: Avoid "quickly", "efficiently", etc.
4. **Clear Outcomes**: Each scenario has verifiable outcomes
5. **Single Responsibility**: Each scenario tests one behavior
6. **Reusable Steps**: Steps can be reused across scenarios

## Contributing

When adding new modules to `ipfs_datasets_py/`:
1. Create a corresponding `.feature` file in this directory
2. Follow the existing format and style
3. Ensure scenarios are clear and testable
4. Avoid implementation-specific language
5. Focus on observable behavior

## License

These feature files are part of the ipfs_datasets_py project and follow the same license.
