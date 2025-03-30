# IPFS Datasets Python - Example Documentation

This directory contains examples demonstrating the various capabilities of the IPFS Datasets Python library.

## Knowledge Graph Extraction and Validation

### knowledge_graph_validation_example.py

This example demonstrates the integrated knowledge graph extraction and validation capabilities, which combine extraction of structured knowledge from text with validation against Wikidata using SPARQL queries.

Key features showcased:

- **Extraction from different sources**:
  - Extracting from plain text
  - Extracting from Wikipedia pages
  - Extracting from multiple documents

- **Integrated validation**:
  - Validation against Wikidata during extraction
  - Validation metrics and coverage analysis
  - Confidence scoring based on validation results

- **Correction suggestions**:
  - Automatic suggestions for fixing inaccurate entities
  - Automatic suggestions for fixing inaccurate relationships
  - Applying corrections to create improved knowledge graphs

- **Entity path analysis**:
  - Finding direct paths between entities
  - Finding multi-hop paths via intermediate entities
  - Analysis of relationship patterns

### Usage

```bash
python knowledge_graph_validation_example.py
```

### Example Output

The example will produce output showing:
- Extracted entities and relationships
- Entity and relationship types
- Validation metrics (coverage scores)
- Path analysis between entities
- Correction suggestions

## Advanced GraphRAG Capabilities

Other examples in this directory demonstrate advanced GraphRAG (Graph Retrieval-Augmented Generation) capabilities that combine vector embeddings with graph structures for enhanced information retrieval.

## Getting Started

To run any of these examples:

1. Ensure the IPFS Datasets Python library is installed:
   ```bash
   pip install -e ..
   ```

2. Run the desired example:
   ```bash
   python example_name.py
   ```

3. Review the output to understand the capabilities demonstrated.

Each example is thoroughly documented with explanatory comments to help understand the code and concepts.