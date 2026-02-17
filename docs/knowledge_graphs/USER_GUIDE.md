# Knowledge Graphs - User Guide

**Version:** 2.0.0  
**Last Updated:** 2026-02-17

## Overview

Complete guide for using the IPFS Datasets Python knowledge graphs module.

## Quick Start

```bash
pip install "ipfs_datasets_py[knowledge_graphs]"
python -m spacy download en_core_web_sm
```

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

extractor = KnowledgeGraphExtractor()
text = "Marie Curie won the Nobel Prize in Physics in 1903."
graph = extractor.extract(text)

for entity in graph.entities:
    print(f"Entity: {entity.name} ({entity.entity_type})")
```

## Core Workflows

### 1. Basic Extraction
Extract entities and relationships from text using the extraction API.

### 2. Query Execution
Execute Cypher queries, hybrid search, and budget-controlled queries.

### 3. IPFS Storage
Store and retrieve graphs using IPLD on IPFS.

### 4. Transaction Management
Use ACID transactions for data consistency.

## Integration Patterns

- GraphRAG integration for question answering
- IPFS integration for decentralized storage
- Neo4j compatibility for existing workflows

## Production Best Practices

1. Use validation for extracted graphs
2. Enable indexes for performance
3. Implement proper error handling
4. Monitor resource usage with budgets
5. Use transactions for data integrity

See [API_REFERENCE.md](API_REFERENCE.md) for complete API documentation.
