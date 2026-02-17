# CLI-MCP Integration Guide

## Overview

This guide documents the relationship between CLI commands and MCP (Model Context Protocol) tools in the IPFS Datasets Python project. It provides complete command mapping, usage examples, and migration patterns.

**Version**: Phase 9 (February 2026)  
**Status**: Active Development  
**Completion**: 76%

## Table of Contents

1. [Introduction](#introduction)
2. [Command Architecture](#command-architecture)
3. [Dataset Commands](#dataset-commands)
4. [Search Commands](#search-commands)
5. [Knowledge Graph Commands](#knowledge-graph-commands)
6. [Complete Command Mapping](#complete-command-mapping)
7. [Usage Examples](#usage-examples)
8. [Migration Guide](#migration-guide)
9. [Best Practices](#best-practices)
10. [Troubleshooting](#troubleshooting)

## Introduction

### What is CLI-MCP Integration?

The IPFS Datasets Python project provides two primary interfaces:
- **CLI (Command-Line Interface)**: Direct terminal commands for human users
- **MCP (Model Context Protocol)**: Tool-based API for AI assistants and programmatic access

**Key Benefit**: Same business logic, different interfaces. Both CLI and MCP use the same `core_operations` modules, ensuring consistent behavior.

### Why Two Interfaces?

1. **CLI**: Human-friendly commands with pretty output
2. **MCP**: AI-friendly structured tool invocations with JSON responses

### Architecture Pattern

```
User Input
    ↓
┌───────────┬──────────┐
│    CLI    │   MCP    │
└─────┬─────┴────┬─────┘
      │          │
      └────┬─────┘
           ↓
    core_operations/
    (Business Logic)
           ↓
      IPFS/Storage
```

## Command Architecture

### CLI Command Structure

```bash
ipfs-datasets <command> <subcommand> [options]
```

**Example**:
```bash
ipfs-datasets dataset validate --path /data --json
```

### MCP Tool Structure

```python
{
    "tool": "category/tool_name",
    "parameters": {
        "param1": "value1",
        "param2": "value2"
    }
}
```

**Example**:
```json
{
    "tool": "dataset_tools/validate_dataset",
    "parameters": {
        "path": "/data"
    }
}
```

## Dataset Commands

### CLI: Dataset Commands

#### 1. Validate Dataset

**CLI**:
```bash
ipfs-datasets dataset validate --path <path>
```

**MCP Equivalent**:
```json
{
    "tool": "dataset_tools/validate_dataset",
    "parameters": {
        "path": "/path/to/dataset"
    }
}
```

**Options**:
- `--path PATH`: Path to dataset (required)
- `--json`: Output in JSON format

**Example**:
```bash
# Basic validation
ipfs-datasets dataset validate --path /data/my_dataset

# JSON output
ipfs-datasets dataset validate --path /data/my_dataset --json
```

#### 2. Dataset Info

**CLI**:
```bash
ipfs-datasets dataset info --name <name>
```

**MCP Equivalent**:
```json
{
    "tool": "dataset_tools/get_dataset_info",
    "parameters": {
        "name": "dataset_name"
    }
}
```

**Options**:
- `--name NAME`: Dataset name (required)
- `--json`: Output in JSON format

**Example**:
```bash
# Get dataset information
ipfs-datasets dataset info --name squad

# JSON output
ipfs-datasets dataset info --name squad --json
```

#### 3. List Datasets

**CLI**:
```bash
ipfs-datasets dataset list
```

**MCP Equivalent**:
```json
{
    "tool": "dataset_tools/list_datasets",
    "parameters": {}
}
```

**Options**:
- `--json`: Output in JSON format

**Example**:
```bash
# List all datasets
ipfs-datasets dataset list

# JSON output
ipfs-datasets dataset list --json
```

#### 4. Process Dataset

**CLI**:
```bash
ipfs-datasets dataset process --input <input> --output <output>
```

**MCP Equivalent**:
```json
{
    "tool": "dataset_tools/process_dataset",
    "parameters": {
        "input": "/input/path",
        "output": "/output/path",
        "operations": ["operation1", "operation2"]
    }
}
```

**Options**:
- `--input PATH`: Input dataset path (required)
- `--output PATH`: Output dataset path (required)
- `--json`: Output in JSON format

**Example**:
```bash
# Process dataset
ipfs-datasets dataset process --input /data/raw --output /data/processed

# JSON output
ipfs-datasets dataset process --input /data/raw --output /data/processed --json
```

## Search Commands

### CLI: Search Commands

#### 1. Basic Search

**CLI**:
```bash
ipfs-datasets search basic <query>
```

**MCP Equivalent**:
```json
{
    "tool": "search_tools/basic_search",
    "parameters": {
        "query": "search terms"
    }
}
```

**Options**:
- `<query>`: Search query text (required)
- `--json`: Output in JSON format

**Example**:
```bash
# Basic text search
ipfs-datasets search basic "machine learning datasets"

# JSON output
ipfs-datasets search basic "nlp tasks" --json
```

#### 2. Semantic Search

**CLI**:
```bash
ipfs-datasets search semantic <query>
```

**MCP Equivalent**:
```json
{
    "tool": "search_tools/semantic_search",
    "parameters": {
        "query": "search terms",
        "top_k": 10
    }
}
```

**Options**:
- `<query>`: Search query text (required)
- `--json`: Output in JSON format

**Example**:
```bash
# Semantic vector search
ipfs-datasets search semantic "natural language processing"

# JSON output
ipfs-datasets search semantic "computer vision" --json
```

#### 3. Hybrid Search

**CLI**:
```bash
ipfs-datasets search hybrid <query>
```

**MCP Equivalent**:
```json
{
    "tool": "search_tools/hybrid_search",
    "parameters": {
        "query": "search terms",
        "alpha": 0.5
    }
}
```

**Options**:
- `<query>`: Search query text (required)
- `--json`: Output in JSON format

**Example**:
```bash
# Hybrid search (basic + semantic)
ipfs-datasets search hybrid "data science"

# JSON output
ipfs-datasets search hybrid "ai research" --json
```

## Knowledge Graph Commands

### CLI: Graph Commands

#### 1. Create Graph

**CLI**:
```bash
ipfs-datasets graph create
```

**MCP Equivalent**:
```json
{
    "tool": "graph_tools/create_graph",
    "parameters": {}
}
```

**Example**:
```bash
ipfs-datasets graph create
```

#### 2. Add Entity

**CLI**:
```bash
ipfs-datasets graph add-entity --id <id> --type <type> [--props <json>]
```

**MCP Equivalent**:
```json
{
    "tool": "graph_tools/add_entity",
    "parameters": {
        "entity_id": "entity1",
        "entity_type": "Person",
        "properties": {"name": "John", "age": 30}
    }
}
```

**Example**:
```bash
ipfs-datasets graph add-entity --id person1 --type Person --props '{"name":"John"}'
```

#### 3. Add Relationship

**CLI**:
```bash
ipfs-datasets graph add-rel --source <id> --target <id> --type <type>
```

**MCP Equivalent**:
```json
{
    "tool": "graph_tools/add_relationship",
    "parameters": {
        "source_id": "entity1",
        "target_id": "entity2",
        "rel_type": "KNOWS"
    }
}
```

**Example**:
```bash
ipfs-datasets graph add-rel --source person1 --target person2 --type KNOWS
```

#### 4. Query Graph

**CLI**:
```bash
ipfs-datasets graph query --query <query>
```

**MCP Equivalent**:
```json
{
    "tool": "graph_tools/query_graph",
    "parameters": {
        "query": "MATCH (n:Person) RETURN n"
    }
}
```

**Example**:
```bash
ipfs-datasets graph query --query "MATCH (n:Person) RETURN n"
```

## Complete Command Mapping

### Dataset Operations

| CLI Command | MCP Tool | Core Module |
|-------------|----------|-------------|
| `dataset validate` | `dataset_tools/validate_dataset` | DataProcessor |
| `dataset info` | `dataset_tools/get_dataset_info` | DatasetLoader |
| `dataset list` | `dataset_tools/list_datasets` | DatasetLoader |
| `dataset process` | `dataset_tools/process_dataset` | DataProcessor |

### Search Operations

| CLI Command | MCP Tool | Core Module |
|-------------|----------|-------------|
| `search basic` | `search_tools/basic_search` | SearchManager |
| `search semantic` | `search_tools/semantic_search` | SearchManager |
| `search hybrid` | `search_tools/hybrid_search` | SearchManager |

### Knowledge Graph Operations

| CLI Command | MCP Tool | Core Module |
|-------------|----------|-------------|
| `graph create` | `graph_tools/create_graph` | KnowledgeGraphManager |
| `graph add-entity` | `graph_tools/add_entity` | KnowledgeGraphManager |
| `graph add-rel` | `graph_tools/add_relationship` | KnowledgeGraphManager |
| `graph query` | `graph_tools/query_graph` | KnowledgeGraphManager |
| `graph search` | `graph_tools/search_graph` | KnowledgeGraphManager |

### IPFS Operations

| CLI Command | MCP Tool | Core Module |
|-------------|----------|-------------|
| `ipfs pin` | `ipfs_tools/pin_to_ipfs` | IPFSPinner |
| `ipfs get` | `ipfs_tools/get_from_ipfs` | IPFSGetter |
| `ipfs cat` | `ipfs_tools/cat_from_ipfs` | IPFSGetter |

## Usage Examples

### Example 1: Dataset Validation Workflow

**CLI Version**:
```bash
# Validate dataset
ipfs-datasets dataset validate --path /data/my_dataset

# Get detailed info
ipfs-datasets dataset info --name my_dataset

# Process if valid
ipfs-datasets dataset process --input /data/my_dataset --output /data/processed
```

**MCP Version**:
```json
// Step 1: Validate
{
    "tool": "dataset_tools/validate_dataset",
    "parameters": {"path": "/data/my_dataset"}
}

// Step 2: Get info
{
    "tool": "dataset_tools/get_dataset_info",
    "parameters": {"name": "my_dataset"}
}

// Step 3: Process
{
    "tool": "dataset_tools/process_dataset",
    "parameters": {
        "input": "/data/my_dataset",
        "output": "/data/processed"
    }
}
```

### Example 2: Search and Analyze

**CLI Version**:
```bash
# Basic search
ipfs-datasets search basic "machine learning"

# Semantic search for similar content
ipfs-datasets search semantic "deep learning models"

# Hybrid search for best results
ipfs-datasets search hybrid "neural networks"
```

**MCP Version**:
```json
// Basic search
{
    "tool": "search_tools/basic_search",
    "parameters": {"query": "machine learning"}
}

// Semantic search
{
    "tool": "search_tools/semantic_search",
    "parameters": {"query": "deep learning models", "top_k": 10}
}

// Hybrid search
{
    "tool": "search_tools/hybrid_search",
    "parameters": {"query": "neural networks", "alpha": 0.5}
}
```

### Example 3: Knowledge Graph Building

**CLI Version**:
```bash
# Create graph
ipfs-datasets graph create

# Add entities
ipfs-datasets graph add-entity --id person1 --type Person --props '{"name":"Alice"}'
ipfs-datasets graph add-entity --id person2 --type Person --props '{"name":"Bob"}'

# Add relationship
ipfs-datasets graph add-rel --source person1 --target person2 --type KNOWS

# Query
ipfs-datasets graph query --query "MATCH (n:Person) RETURN n"
```

**MCP Version**:
```json
// Create graph
{"tool": "graph_tools/create_graph", "parameters": {}}

// Add entities
{"tool": "graph_tools/add_entity", "parameters": {
    "entity_id": "person1",
    "entity_type": "Person",
    "properties": {"name": "Alice"}
}}

{"tool": "graph_tools/add_entity", "parameters": {
    "entity_id": "person2",
    "entity_type": "Person",
    "properties": {"name": "Bob"}
}}

// Add relationship
{"tool": "graph_tools/add_relationship", "parameters": {
    "source_id": "person1",
    "target_id": "person2",
    "rel_type": "KNOWS"
}}

// Query
{"tool": "graph_tools/query_graph", "parameters": {
    "query": "MATCH (n:Person) RETURN n"
}}
```

## Migration Guide

### From MCP to CLI

If you're migrating from MCP tool calls to CLI commands:

1. **Identify the MCP tool** you're using
2. **Look up the CLI equivalent** in the mapping table
3. **Convert parameters** to CLI flags
4. **Add `--json` flag** if you need structured output

**Example Migration**:

**Before (MCP)**:
```json
{
    "tool": "dataset_tools/validate_dataset",
    "parameters": {
        "path": "/data/dataset"
    }
}
```

**After (CLI)**:
```bash
ipfs-datasets dataset validate --path /data/dataset --json
```

### From CLI to MCP

If you're migrating from CLI to MCP:

1. **Identify the CLI command** you're using
2. **Look up the MCP equivalent** in the mapping table
3. **Convert flags** to parameters object
4. **Wrap in tool invocation** structure

**Example Migration**:

**Before (CLI)**:
```bash
ipfs-datasets search semantic "machine learning" --json
```

**After (MCP)**:
```json
{
    "tool": "search_tools/semantic_search",
    "parameters": {
        "query": "machine learning",
        "top_k": 10
    }
}
```

## Best Practices

### CLI Best Practices

1. **Use `--json` for scripting**: Always use JSON output when parsing results in scripts
2. **Check exit codes**: CLI returns 0 on success, non-zero on error
3. **Use quotes for multi-word arguments**: `"search query"` instead of `search query`
4. **Combine with Unix tools**: Pipe to `jq`, `grep`, etc. for processing

**Example**:
```bash
# Get JSON and filter with jq
ipfs-datasets dataset list --json | jq '.datasets[] | select(.size > 1000000)'

# Count results
ipfs-datasets search basic "query" --json | jq '.results | length'
```

### MCP Best Practices

1. **Validate parameters**: Check required parameters before invoking
2. **Handle errors gracefully**: MCP tools return error objects
3. **Use batch operations**: Invoke multiple tools for complex workflows
4. **Cache results**: Store frequently accessed data

**Example**:
```python
# Validate before calling
def validate_dataset(path):
    if not os.path.exists(path):
        raise ValueError(f"Path not found: {path}")
    
    result = mcp_client.invoke_tool(
        "dataset_tools/validate_dataset",
        {"path": path}
    )
    
    if result.get("error"):
        raise RuntimeError(result["error"])
    
    return result
```

### Shared Best Practices

1. **Use core_operations directly**: For Python scripts, import modules directly
2. **Consistent error handling**: Both CLI and MCP use same error types
3. **Monitor performance**: Use logging to track operation timing
4. **Test both interfaces**: Ensure consistency across CLI and MCP

## Troubleshooting

### Common Issues

#### Issue 1: Command Not Found

**Symptom**: `bash: ipfs-datasets: command not found`

**Solution**:
```bash
# Install in development mode
pip install -e .

# Or use full path
python /path/to/ipfs_datasets_cli.py dataset validate --path /data
```

#### Issue 2: Missing Dependencies

**Symptom**: `ImportError: No module named 'anyio'`

**Solution**:
```bash
# Install all dependencies
pip install -e ".[all]"

# Or specific dependencies
pip install anyio datasets transformers
```

#### Issue 3: JSON Parse Error

**Symptom**: Cannot parse JSON output

**Solution**:
```bash
# Redirect stderr to hide warnings
ipfs-datasets dataset list --json 2>/dev/null

# Or filter JSON lines only
ipfs-datasets dataset list --json 2>&1 | grep -E '^\{|\['
```

#### Issue 4: MCP Tool Not Found

**Symptom**: `Tool 'category/tool' not found`

**Solution**:
1. Check tool name spelling
2. Verify category exists
3. List available tools:
```bash
ipfs-datasets tools categories
ipfs-datasets tools list <category>
```

### Getting Help

#### CLI Help

```bash
# General help
ipfs-datasets --help

# Command-specific help
ipfs-datasets dataset --help
ipfs-datasets search --help
ipfs-datasets graph --help
```

#### MCP Tool Discovery

```bash
# List all categories
ipfs-datasets tools categories

# List tools in a category
ipfs-datasets tools list dataset_tools

# Get tool schema
ipfs-datasets tools schema dataset_tools validate_dataset
```

## Appendix

### Version History

- **Phase 9 (Feb 2026)**: Added dataset and search CLI commands
- **Phase 8 (Feb 2026)**: Enhanced MCP server with 200+ tools
- **Phase 7 (Feb 2026)**: Hierarchical tool manager (99% context reduction)

### Related Documentation

- [MCP Tools Guide](MCP_TOOLS_GUIDE.md)
- [Core Operations Guide](CORE_OPERATIONS_GUIDE.md)
- [Tool Refactoring Guide](TOOL_REFACTORING_GUIDE.md)
- [Phase 9 Completion Report](PHASE_9_COMPLETION_REPORT.md)

### Contributors

- Phase 9 Implementation Team
- MCP Server Development Team
- Core Operations Team

---

**Last Updated**: February 17, 2026  
**Status**: Active Development  
**Phase 9 Progress**: 76%
