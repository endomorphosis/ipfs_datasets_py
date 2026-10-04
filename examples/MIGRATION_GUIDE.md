# Examples Migration Guide

This guide helps you navigate the examples reorganization and find equivalent examples for your use case.

## 📋 What Changed

The examples directory was reorganized to focus on **package module integration** rather than MCP server tools or dashboards. The goal is to help developers understand how to use ipfs_datasets_py in their own applications.

## 🆕 New Organization

### Essential Examples (Start Here)
- **01_getting_started.py** - Verify installation, check modules
- **02_embeddings_basic.py** - Generate embeddings, semantic similarity
- **03_vector_search.py** - FAISS/Qdrant vector stores
- **04_file_conversion.py** - Convert file formats
- **05_knowledge_graphs_basic.py** - Extract entities/relationships
- **06_ipfs_storage.py** - IPFS operations
- **07_pdf_processing.py** - PDF extraction with OCR
- **08_multimedia_download.py** - yt-dlp and FFmpeg
- **09_batch_processing.py** - Scale processing

### Coming Soon
- **10_legal_data_scraping.py** - Legal datasets
- **11_web_archiving.py** - Web scraping and archiving
- **12_graphrag_basic.py** - Knowledge graph RAG
- **13_logic_reasoning.py** - Formal logic
- **14_cross_document_reasoning.py** - Multi-doc analysis
- **15_graphrag_optimization.py** - Ontology optimization

## 🔄 Migration Map

### If you were using...

#### MCP Server Examples
**Old:** `demo_mcp_server.py`, `mcp_server_example.py`  
**New:** These are MCP-focused, not package integration examples.  
**Recommendation:** If you need MCP server functionality, use the MCP documentation. For package integration, see the new numbered examples.

#### Dashboard Examples
**Old:** `demo_mcp_dashboard.py`, `mcp_dashboard_examples.py`, various dashboard demos  
**New:** Dashboard examples will be archived.  
**Recommendation:** Focus on package modules. Build your own dashboards using the data processing capabilities.

#### Embeddings
**Old:** Scattered across multiple files  
**New:** **02_embeddings_basic.py** - Comprehensive embeddings guide  
**Why:** Consolidated all embedding examples into one clear guide

#### Vector Search
**Old:** Mixed with other examples  
**New:** **03_vector_search.py** - FAISS, Qdrant, search patterns  
**Why:** Dedicated example for vector store operations

#### File Processing
**Old:** `advanced_features_example.py`, `file_converter_example.py`  
**New:** **04_file_conversion.py** - Unified file conversion  
**Why:** Single clear example for all file format conversions

#### Knowledge Graphs
**Old:** `knowledge_graph_validation_example.py`, `universal_knowledge_graph_example.py`  
**Kept:** `knowledge_graph_validation_example.py` (SPARQL validation still valuable)  
**New:** **05_knowledge_graphs_basic.py** - Basic entity extraction  
**Why:** Simplified starting point, advanced example still available

#### PDF Processing
**Old:** Scattered across file converter examples  
**New:** **07_pdf_processing.py** - Dedicated PDF guide with OCR  
**Why:** PDFs are complex enough to deserve their own example

#### Multimedia
**Old:** `demo_multimedia_final.py`, `test_multimedia_comprehensive.py`  
**New:** **08_multimedia_download.py** - yt-dlp + FFmpeg guide  
**Why:** Focused on practical multimedia processing workflows

#### Batch Processing
**Old:** Parts of `advanced_features_example.py`  
**New:** **09_batch_processing.py** - Complete batch processing guide  
**Why:** Scaling is important enough for dedicated coverage

#### Pipelines
**Old:** `pipeline_example.py`  
**Kept:** Still available, demonstrates monadic error handling  
**Note:** Still relevant for advanced error handling patterns

#### Logic & Reasoning
**Old:** `neurosymbolic/` directory examples  
**Kept:** These examples are still valuable  
**Coming:** **13_logic_reasoning.py** - Simplified introduction  
**Why:** Neurosymbolic examples are advanced; need beginner intro

## 📚 Finding What You Need

### I want to...

#### Get started with the package
→ **01_getting_started.py**

#### Generate text embeddings
→ **02_embeddings_basic.py**

#### Build a semantic search system
→ **02_embeddings_basic.py** + **03_vector_search.py**

#### Convert document formats
→ **04_file_conversion.py**

#### Extract information from PDFs
→ **07_pdf_processing.py**

#### Download videos/audio
→ **08_multimedia_download.py**

#### Process many files at once
→ **09_batch_processing.py**

#### Build knowledge graphs
→ **05_knowledge_graphs_basic.py**  
→ `knowledge_graph_validation_example.py` (advanced)

#### Store data on IPFS
→ **06_ipfs_storage.py**

#### Scrape legal data
→ Coming: **10_legal_data_scraping.py**  
→ Meanwhile: See `processors/legal_scrapers/` for API

#### Do formal logic reasoning
→ `neurosymbolic/` examples (advanced)  
→ Coming: **13_logic_reasoning.py** (beginner)

#### Build GraphRAG systems
→ `graphrag_optimizer_example.py` (advanced)  
→ Coming: **12_graphrag_basic.py** (beginner)

## 🗂️ What's Staying

These examples are still valuable and will remain:

### Specialized Examples
- **knowledge_graphs/simple_example.py** - Basic KG patterns
- **neurosymbolic/** - Logic reasoning examples
  - example1_basic_reasoning.py
  - example2_temporal_reasoning.py
  - example3_deontic_reasoning.py
  - example4_multiformat_parsing.py
  - example5_combined_reasoning.py
- **external_provers/** - Z3 integration
  - example1_z3_basic.py
  - example2_cache_performance.py
- **processors/** - Processor-specific patterns
  - 04_ipfs_processing.py
  - 05_error_handling.py
  - 06_caching.py
  - 07_health_monitoring.py
  - 08_async_processing.py

### Still Valuable
- `pipeline_example.py` - Monadic error handling
- `advanced_features_example.py` - Advanced patterns
- `knowledge_graph_validation_example.py` - SPARQL validation
- `sparql_validation_example.py` - SPARQL queries

## 🗄️ What's Being Archived

These examples focus on MCP server tools or dashboards rather than package integration:

### MCP Server Focus
- `demo_mcp_server.py`
- `mcp_server_example.py`
- `mcp_server_demo.py`
- `claude_mcp_integration.py`

### Dashboard Focus
- `demo_mcp_dashboard.py`
- `demo_mcp_investigation_dashboard.py`
- `demo_unified_investigation_dashboard.py`
- `mcp_dashboard_examples.py`
- `unified_dashboard_example.py`
- `provenance_dashboard_example.py`
- `create_maps_dashboard_demo.py`
- `demo_news_analysis_dashboard.py`

### Visualization Focus
- `alert_visualization_integration.py`
- `optimizer_visualization_demo.py`
- `rag_audit_visualization_example.py`
- `create_visual_demonstration.py`

### Integration/Demo Focus
- `accelerate_integration_demo.py`
- `ipfs_accelerate_example.py`
- `cli_caching_demo.py`
- `cli_tools_as_data_sources.py`
- `vscode_auth_example.py`
- `vscode_cli_example.py`

### Redundant/Outdated
- `demo_multimedia_final.py` → Use **08_multimedia_download.py**
- `test_multimedia_comprehensive.py` → See tests/
- `validate_multimedia_simple.py` → See tests/
- `file_converter_example.py` → Use **04_file_conversion.py**

## 💡 Quick Reference

### For Package Integration
Use the new numbered examples (01-15). They focus on:
- How to import modules
- How to use APIs
- How to integrate into your code
- Clear, runnable examples

### For MCP Server Tools
Refer to MCP server documentation rather than examples. The examples directory focuses on package integration.

### For Advanced Topics
Check the specialized subdirectories:
- `knowledge_graphs/` - Advanced KG patterns
- `neurosymbolic/` - Logic and reasoning
- `external_provers/` - Theorem prover integration
- `processors/` - Processor patterns

### For Dashboards/Visualization
These are application-specific. Build your own using the package's data processing capabilities demonstrated in the examples.

## 🤔 Still Can't Find It?

1. **Check the main README**: `examples/README.md`
2. **Search the codebase**: `grep -r "your_feature" ipfs_datasets_py/`
3. **Check tests**: Often show usage patterns
4. **Check source docs**: Look at module docstrings

## 📝 Contributing

If you create an example that would help others:

1. Follow the pattern in new numbered examples
2. Focus on package module usage
3. Include clear docstrings and comments
4. Add error handling
5. Submit a PR with updates to README.md

---

**Questions?** Open an issue on GitHub with the `examples` label.

**Last Updated:** 2024-02-17
