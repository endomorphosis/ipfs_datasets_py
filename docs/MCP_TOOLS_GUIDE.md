# MCP Tools Usage Guide

## Overview

This guide provides comprehensive documentation for using MCP (Model Context Protocol) tools in the IPFS Datasets Python project. MCP tools provide a standardized interface for AI assistants and other systems to invoke functionality.

## Table of Contents

1. [What are MCP Tools?](#what-are-mcp-tools)
2. [Tool Categories](#tool-categories)
3. [Enhancement 12 Legal Tools](#enhancement-12-legal-tools)
4. [Usage Patterns](#usage-patterns)
5. [Error Handling](#error-handling)
6. [Testing](#testing)
7. [Development](#development)

## What are MCP Tools?

MCP (Model Context Protocol) tools are async Python functions that:
- Accept standardized input parameters
- Return standardized output dictionaries
- Follow the thin wrapper pattern
- Delegate business logic to core modules

### Benefits

- **Consistency**: Same behavior across MCP, CLI, and Python imports
- **Maintainability**: Single source of truth for business logic
- **Testability**: Core logic independently testable
- **Reusability**: Code shared across interfaces

## Tool Categories

The MCP server organizes tools into categories:

### Core Tool Categories

| Category | Description | Example Tools |
|----------|-------------|---------------|
| `dataset_tools` | Dataset loading, saving, conversion | load_dataset, save_dataset |
| `ipfs_tools` | IPFS operations (pin, add, get) | pin_to_ipfs, get_from_ipfs |
| `embedding_tools` | Vector embeddings and similarity | generate_embeddings, semantic_search |
| `legal_dataset_tools` | Legal search and analysis | multi_engine_legal_search, expand_legal_query |
| `pdf_tools` | PDF processing and GraphRAG | pdf_ingest_to_graphrag, pdf_optimize_for_llm |
| `graph_tools` | Knowledge graph operations | graph_create, graph_query_cypher |

### Hierarchical Tool Manager

The `HierarchicalToolManager` reduces context window usage by 99%:

```python
from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager

manager = HierarchicalToolManager()

# List all categories
categories = await manager.list_categories()

# List tools in a category
tools = await manager.list_tools("legal_dataset_tools")

# Get tool schema
schema = await manager.get_tool_schema("legal_dataset_tools", "multi_engine_legal_search")

# Execute tool
result = await manager.dispatch_tool(
    category="legal_dataset_tools",
    tool="multi_engine_legal_search",
    params={"query": "EPA regulations", "engines": ["brave", "duckduckgo"]}
)
```

## Enhancement 12 Legal Tools

Enhancement 12 provides 8 comprehensive legal search tools.

### 1. Multi-Engine Legal Search

**Tool**: `multi_engine_legal_search`

**Description**: Search across multiple search engines (Brave, DuckDuckGo, Google CSE) with parallel execution and intelligent fallback.

**Usage**:

```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.multi_engine_legal_search import (
    multi_engine_legal_search
)

# Basic search
result = await multi_engine_legal_search(
    query="EPA water pollution regulations",
    engines=["brave", "duckduckgo"],
    max_results=20,
    parallel_enabled=True,
    fallback_enabled=True
)

print(f"Status: {result['status']}")
print(f"Total results: {result['total_results']}")
print(f"Engines used: {result['engines_used']}")
```

**Parameters**:
- `query` (str, required): Search query
- `engines` (list, optional): Engines to use (default: ["brave", "duckduckgo"])
- `max_results` (int, optional): Max results per engine (default: 20)
- `parallel_enabled` (bool, optional): Execute in parallel (default: True)
- `fallback_enabled` (bool, optional): Fallback on failure (default: True)
- `deduplication_enabled` (bool, optional): Remove duplicates (default: True)

**Returns**:
```python
{
    "status": "success",
    "query": "EPA water pollution regulations",
    "results": [...],
    "total_results": 45,
    "engines_used": ["brave", "duckduckgo"],
    "metadata": {...}
}
```

### 2. Enhanced Query Expansion

**Tool**: `expand_legal_query`

**Description**: Expand legal queries with 200+ synonyms, relationships, and domain-specific terms.

**Usage**:

```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.enhanced_query_expander import (
    expand_legal_query
)

# Expand query
result = await expand_legal_query(
    query="EPA regulations on water quality",
    strategy="balanced",  # conservative, balanced, or aggressive
    max_expansions=10,
    include_synonyms=True,
    include_related=True,
    domains=["environmental", "administrative"]
)

print(f"Original: {result['original_query']}")
print(f"Expansions: {result['expanded_queries']}")
```

**Strategies**:
- `conservative`: Fewer, more precise expansions
- `balanced`: Moderate expansion (default)
- `aggressive`: Maximum expansion for recall

**Domains**:
- `administrative`: Administrative law
- `criminal`: Criminal law
- `civil`: Civil law
- `environmental`: Environmental law
- `labor`: Labor law

### 3. Advanced Result Filtering

**Tool**: `filter_legal_results`

**Description**: Filter search results by domain, date, jurisdiction, quality score, and fuzzy deduplication.

**Usage**:

```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.result_filter import (
    filter_legal_results
)

# Filter results
result = await filter_legal_results(
    results=search_results,
    domain_whitelist=["gov", "courts.gov"],
    date_range={"start": "2020-01-01", "end": "2024-12-31"},
    jurisdictions=["federal", "state"],
    min_quality_score=0.7,
    enable_fuzzy_dedup=True,
    similarity_threshold=0.85
)

print(f"Filtered from {result['total_input']} to {result['total_output']}")
print(f"Removed: {result['removed_total']}")
```

**Jurisdictions**:
- `federal`: Federal regulations and laws
- `state`: State laws and regulations
- `local`: Local ordinances
- `international`: International treaties

### 4. Citation Extraction

**Tool**: `extract_legal_citations`

**Description**: Extract legal citations, build citation networks, and export in multiple formats.

**Usage**:

```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.citation_extraction_tool import (
    extract_legal_citations,
    export_citations
)

# Extract citations
result = await extract_legal_citations(
    results=search_results,
    build_network=True,
    rank_by="importance",  # importance, frequency, or recency
    citation_types=["case", "statute", "regulation"]
)

print(f"Found {result['total_citations']} citations")
print(f"Types: {result['citation_types_found']}")

# Export citations
export_result = await export_citations(
    citations=result['citations'],
    format="graphml",  # json, csv, graphml, or dot
    output_path="/tmp/citations.graphml"
)
```

### 5. Legal GraphRAG Integration

**Tool**: `create_legal_knowledge_graph`

**Description**: Create knowledge graphs from legal documents with entity/relationship extraction and semantic search.

**Usage**:

```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.legal_graphrag_tool import (
    create_legal_knowledge_graph,
    search_legal_graph
)

# Create knowledge graph
documents = [
    {"id": "1", "title": "Case A", "content": "..."},
    {"id": "2", "title": "Statute B", "content": "..."}
]

graph_result = await create_legal_knowledge_graph(
    documents=documents,
    extract_entities=True,
    extract_relationships=True,
    entity_types=["case", "statute", "party"],
    min_confidence=0.7
)

# Search graph
search_result = await search_legal_graph(
    graph_id=graph_result['graph_id'],
    query="regulations on water pollution",
    search_type="semantic",  # semantic, keyword, structural, or hybrid
    include_subgraph=True
)
```

### 6. Multi-Language Support

**Tool**: `detect_query_language`, `translate_legal_query`, `cross_language_legal_search`

**Description**: Detect languages, translate queries, and search across 5 languages (en, de, fr, es, it).

**Usage**:

```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.multilanguage_support_tool import (
    detect_query_language,
    translate_legal_query,
    cross_language_legal_search
)

# Detect language
lang_result = await detect_query_language(
    query="Was sind die EPA-Vorschriften?"
)
print(f"Detected: {lang_result['detected_language']}")  # "de"

# Translate query
trans_result = await translate_legal_query(
    query="EPA water regulations",
    target_language="de",
    preserve_legal_terms=True
)
print(f"Translation: {trans_result['translated_query']}")

# Cross-language search
search_result = await cross_language_legal_search(
    query="water pollution regulations",
    languages=["en", "de", "fr"],
    max_results_per_language=10,
    translate_results=True
)
```

### 7. Regulation Version Tracking

**Tool**: `track_regulation_version`, `get_regulation_at_date`, `get_regulation_changes`

**Description**: Track regulation versions over time with temporal queries and change detection.

**Usage**:

```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.regulation_version_tracker_tool import (
    track_regulation_version,
    get_regulation_at_date,
    get_regulation_changes
)

# Track a new version
track_result = await track_regulation_version(
    regulation_id="40-CFR-122.1",
    content="Full regulation text...",
    effective_date="2024-01-15",
    title="Water Pollution Standards"
)

# Get version at specific date
version_result = await get_regulation_at_date(
    regulation_id="40-CFR-122.1",
    query_date="2023-06-15"
)

# Get changes between dates
changes_result = await get_regulation_changes(
    regulation_id="40-CFR-122.1",
    from_date="2023-01-01",
    to_date="2024-01-01",
    include_diff=True
)
```

### 8. Legal Report Generation

**Tool**: `generate_legal_report`, `export_legal_report`

**Description**: Generate formatted reports with multiple templates and export formats.

**Usage**:

```python
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.legal_report_generator_tool import (
    generate_legal_report,
    export_legal_report
)

# Generate report
report = await generate_legal_report(
    search_results=results,
    template="compliance",  # compliance, research, or monitoring
    title="EPA Water Regulations Compliance Report",
    include_summary=True,
    include_citations=True
)

# Export report
export_result = await export_legal_report(
    report_data=report,
    format="markdown",  # markdown, html, pdf, docx, or json
    output_path="/tmp/report.md"
)
```

## Usage Patterns

### Pattern 1: Thin Wrapper

All MCP tools follow the thin wrapper pattern:

```python
async def tool_function(**params):
    """
    Tool wrapper.
    
    This is a thin wrapper around CoreClass.method().
    All business logic is in ipfs_datasets_py.processors or ipfs_datasets_py.core_operations
    """
    try:
        from ipfs_datasets_py.processors import CoreClass
        
        # 1. Validate inputs
        if not param:
            return {"status": "error", "message": "validation error"}
        
        # 2. Initialize core class
        processor = CoreClass()
        
        # 3. Call core method
        result = processor.core_method(**params)
        
        # 4. Add MCP metadata
        result["mcp_tool"] = "tool_function"
        
        # 5. Return standardized result
        return result
        
    except ImportError as e:
        return {"status": "error", "message": f"Module not found: {e}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
```

### Pattern 2: Error Handling

All tools return standardized error responses:

```python
{
    "status": "error",
    "message": "Description of the error",
    "context": {...}  # Optional error context
}
```

### Pattern 3: Success Response

All tools return standardized success responses:

```python
{
    "status": "success",
    "result_field": "result_data",
    "metadata": {...},
    "mcp_tool": "tool_name"
}
```

## Error Handling

### Common Errors

1. **ImportError**: Missing dependencies
   ```python
   {
       "status": "error",
       "message": "Required module not found: langdetect. Install with: pip install ipfs-datasets-py[legal]"
   }
   ```

2. **ValidationError**: Invalid input
   ```python
   {
       "status": "error",
       "message": "query must be a non-empty string"
   }
   ```

3. **ProcessingError**: Processing failure
   ```python
   {
       "status": "error",
       "message": "Failed to process documents: <details>"
   }
   ```

### Handling Errors in Code

```python
result = await tool_function(**params)

if result["status"] == "error":
    print(f"Error: {result['message']}")
    # Handle error gracefully
else:
    # Process successful result
    process_result(result)
```

## Testing

### Running Tests

```bash
# Run all MCP tool tests
pytest tests/mcp/ -v

# Run Enhancement 12 tests
pytest tests/mcp/test_enhancement12_tools.py -v

# Run specific test class
pytest tests/mcp/test_enhancement12_tools.py::TestMultiLanguageSupportTool -v

# Run with coverage
pytest tests/mcp/ --cov=ipfs_datasets_py.mcp_server.tools --cov-report=html
```

### Writing Tests

Follow the GIVEN-WHEN-THEN pattern:

```python
import pytest

class TestYourTool:
    """Test your MCP tool"""

    @pytest.mark.asyncio
    async def test_given_valid_input_when_calling_tool_then_returns_success(self):
        """
        GIVEN valid input parameters
        WHEN calling the tool
        THEN it should return success status
        """
        from ipfs_datasets_py.mcp_server.tools.category.your_tool import your_tool
        
        result = await your_tool(param1="value1", param2="value2")
        
        assert result["status"] == "success"
        assert "result_field" in result
```

## Development

### Creating New Tools

1. **Choose category**: Determine appropriate tool category
2. **Create tool file**: `ipfs_datasets_py/mcp_server/tools/{category}/{tool_name}.py`
3. **Implement core logic**: Add business logic to appropriate core module
4. **Create thin wrapper**: Tool delegates to core module
5. **Add tests**: Create tests in `tests/mcp/test_{category}.py`
6. **Document**: Add to this guide

### Tool Template

```python
"""
Tool Description.

This tool does X, Y, and Z.

Core implementation: ipfs_datasets_py.processors.module_name
"""

import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


async def tool_function(
    param1: str,
    param2: Optional[int] = None
) -> Dict[str, Any]:
    """
    Tool function description.
    
    This is a thin wrapper around CoreClass.method().
    All business logic is in ipfs_datasets_py.processors.module_name
    
    Args:
        param1: Description of param1
        param2: Description of param2 (optional)
    
    Returns:
        Dictionary containing:
        - status: "success" or "error"
        - result: Result data
        - metadata: Additional metadata
    
    Example:
        >>> result = await tool_function(param1="value")
        >>> print(result['status'])
    """
    try:
        from ipfs_datasets_py.processors import CoreClass
        
        # Validate inputs
        if not param1:
            return {
                "status": "error",
                "message": "param1 is required"
            }
        
        # Initialize core class
        processor = CoreClass()
        
        # Call core method
        result = processor.core_method(param1, param2)
        
        # Add MCP metadata
        result["mcp_tool"] = "tool_function"
        
        return result
        
    except ImportError as e:
        logger.error(f"Import error: {e}")
        return {
            "status": "error",
            "message": f"Required module not found: {e}"
        }
    except Exception as e:
        logger.error(f"Error: {e}")
        return {
            "status": "error",
            "message": str(e)
        }
```

### Best Practices

1. **Keep tools thin**: Delegate to core modules
2. **Validate inputs**: Check all required parameters
3. **Handle errors gracefully**: Return standardized error responses
4. **Add comprehensive docs**: Docstrings with examples
5. **Write tests**: Cover success and error paths
6. **Log appropriately**: Use logger for debugging
7. **Type hints**: Add type hints for all parameters
8. **Async functions**: Use async/await for all tools

## Additional Resources

- [Enhancement 12 Completion Report](../ENHANCEMENT_12_MCP_COMPLETION.md)
- [Core Operations Guide](./CORE_OPERATIONS_GUIDE.md)
- [Testing Guide](./TESTING_GUIDE.md)
- [MCP Server Documentation](../ipfs_datasets_py/mcp_server/README.md)

---

**Document Version**: 1.0  
**Date**: 2026-02-17  
**Status**: Complete  
**Maintainer**: IPFS Datasets Python Team
