# Usage Examples for ipfs_datasets_py Optimizers

This document provides comprehensive, real-world usage examples for all optimizer types in ipfs_datasets_py.

## Table of Contents

- [GraphRAG Optimizers](#graphrag-optimizers)
  - [Ontology Generation](#ontology-generation)
  - [Query Optimization](#query-optimization)
  - [Statistical Analysis](#statistical-analysis)
  - [Async Batch Processing](#async-batch-processing)
- [Agentic Optimizers](#agentic-optimizers)
- [Common Patterns](#common-patterns)
  - [Query Validation](#query-validation)
  - [Caching Strategies](#caching-strategies)
- [Troubleshooting](#troubleshooting)

---

## GraphRAG Optimizers

### Ontology Generation

#### Basic Entity Extraction

Extract entities and relationships from text documents:

```python
from ipfs_datasets_py.optimizers.graphrag import (
    OntologyGenerator,
    OntologyGenerationContext,
    ExtractionStrategy,
    DataType,
)

# Initialize generator
generator = OntologyGenerator()

# Create extraction context for legal domain
context = OntologyGenerationContext(
    data_source="contract.pdf",
    data_type=DataType.TEXT,
    domain="legal",
    extraction_strategy=ExtractionStrategy.RULE_BASED,
)

# Extract entities from contract text
contract_text = """
Alice Smith must pay Bob Johnson $10,000 by December 31, 2025.
Payment shall be made to XYZ Corporation's bank account.
"""

result = generator.extract_entities(contract_text, context)

# Access extracted entities
for entity in result.entities:
    print(f"Entity: {entity.text} (Type: {entity.type}, Confidence: {entity.confidence})")

# Access relationships
for rel in result.relationships:
    print(f"Relationship: {rel.type} between {rel.source_id} and {rel.target_id}")
```

#### Using LLM-Based Extraction

For more sophisticated entity extraction using language models:

```python
from ipfs_datasets_py.optimizers.graphrag import ExtractionStrategy

# Configure LLM-based extraction
context = OntologyGenerationContext(
    data_source="research_paper.txt",
    data_type=DataType.TEXT,
    domain="scientific",
    extraction_strategy=ExtractionStrategy.LLM_BASED,
)

# Extract with LLM backend
result = generator.extract_entities(complex_text, context)

# LLM extraction provides higher confidence and richer entity types
print(f"Extracted {len(result.entities)} entities with mean confidence: "
      f"{sum(e.confidence for e in result.entities) / len(result.entities):.2f}")
```

#### Extracting from Files

Extract entities directly from files:

```python
# Extract from PDF file
pdf_result = generator.extract_entities_from_file(
    "document.pdf",
    context,
    max_pages=10  # Limit to first 10 pages
)

# Extract from JSON data
json_context = OntologyGenerationContext(
    data_source="api_response.json",
    data_type=DataType.JSON,
    domain="api",
    extraction_strategy=ExtractionStrategy.HYBRID,
)

with open("api_response.json") as f:
    json_data = json.load(f)

json_result = generator.extract_entities(json_data, json_context)
```

#### Streaming Extraction for Large Documents

Process large documents incrementally:

```python
large_document = open("large_report.txt").read()

# Stream entities as they are extracted
for entity in generator.extract_entities_streaming(large_document, context):
    # Process each entity immediately
    store_to_database(entity)
    
    # Can break early if needed
    if entity.text == "stop_marker":
        break
```

### Query Optimization

#### Unified GraphRAG Query Optimizer

Optimize queries for different graph types with automatic validation:

```python
from ipfs_datasets_py.optimizers.graphrag import UnifiedGraphRAGQueryOptimizer

# Initialize optimizer
optimizer = UnifiedGraphRAGQueryOptimizer()

# Define a complex query
query = {
    "vector": [0.1, 0.2, 0.3, ...],  # 768-dim embedding
    "max_vector_results": 20,
    "min_similarity": 0.75,
    "traversal": {
        "max_depth": 3,
        "edge_types": ["RELATES_TO", "CONTAINS"],
    },
    "priority": "high",
}

# Optimize query (automatically validates and corrects parameters)
optimized_query = optimizer.optimize_query(query)

# Query is now validated and optimized
print(f"Max results: {optimized_query['max_vector_results']}")  # Clamped to [1, 1000]
print(f"Min similarity: {optimized_query['min_similarity']}")  # Clamped to [0.0, 1.0]
```

#### Wikipedia Traversal Optimization

Optimize queries for Wikipedia-style knowledge graphs:

```python
wiki_query = {
    "starting_page": "Machine Learning",
    "max_depth": 4,
    "categories": ["Computer Science", "Artificial Intelligence"],
    "min_similarity": 0.8,
}

optimized_wiki = optimizer.optimize_wikipedia_traversal(wiki_query)

# Use optimized query for traversal
results = wikipedia_graph.traverse(optimized_wiki)
```

#### IPLD Traversal Optimization

Optimize for IPFS/IPLD content-addressed graphs:

```python
ipld_query = {
    "root_cid": "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
    "max_depth": 2,
    "selector": {
        "type": "ExploreRecursive",
        "limit": 100,
    },
}

optimized_ipld = optimizer.optimize_ipld_traversal(ipld_query)

# Query is optimized for IPLD DAG traversal
ipld_client.traverse(optimized_ipld)
```

### Statistical Analysis

#### Tracking Extraction Quality Over Time

Monitor extraction quality trends using statistical methods:

```python
from ipfs_datasets_py.optimizers.graphrag import OntologyGenerator

generator = OntologyGenerator()

# Process multiple documents and collect results
results = []
for document in document_batch:
    result = generator.extract_entities(document, context)
    results.append(result)

# Calculate statistical metrics
kurtosis = generator.history_kurtosis(results)
print(f"Kurtosis: {kurtosis:.3f}")
if kurtosis > 1.0:
    print("⚠️  Heavy-tailed distribution - many outliers detected")
elif kurtosis < -1.0:
    print("✓ Light-tailed distribution - consistent quality")

# Calculate EWMA to track trends
ewma = generator.score_ewma(results, alpha=0.3)
print(f"EWMA (weighted recent quality): {ewma:.2f}")

if ewma < 0.7:
    print("⚠️  Quality trending downward, investigate")

# Get full EWMA series for visualization
ewma_series = generator.score_ewma_series(results, alpha=0.3)

# Plot quality trend
import matplotlib.pyplot as plt
plt.plot(ewma_series)
plt.xlabel("Batch Number")
plt.ylabel("EWMA Confidence")
plt.title("Extraction Quality Trend")
plt.axhline(y=0.7, color='r', linestyle='--', label='Threshold')
plt.legend()
plt.savefig("quality_trend.png")
```

#### Analyzing Entity Distribution

Understand entity confidence distributions:

```python
# Get unique relationship types
unique_types = generator.unique_relationship_types(result)
print(f"Discovered {len(unique_types)} relationship types: {unique_types}")

# Count high-confidence entities
high_conf_count = generator.entity_count_with_confidence_above(result, threshold=0.9)
total_count = generator.entity_count(result)
print(f"High confidence entities: {high_conf_count}/{total_count} ({high_conf_count/total_count*100:.1f}%)")

# Analyze entity-relationship ratio
ratio = generator.entity_relation_ratio(result)
print(f"Entity/Relationship ratio: {ratio:.2f}")
if ratio > 5:
    print("⚠️  Many entities but few relationships - may need better relationship inference")

# Calculate median entity text length
median_length = generator.entity_text_length_median(result)
print(f"Median entity text length: {median_length:.0f} characters")
```

### Async Batch Processing

#### Processing Multiple Documents Concurrently

Use async/await for efficient batch processing:

```python
import asyncio
from ipfs_datasets_py.optimizers.graphrag import OntologyGenerator

async def process_document_batch():
    generator = OntologyGenerator()
    
    # Prepare documents
    documents = [
        "Document 1 text...",
        "Document 2 text...",
        "Document 3 text...",
        # ... many more documents
    ]
    
    # Process up to 5 documents concurrently
    results = await generator.extract_batch_async(
        documents,
        context,
        max_concurrent=5,
        timeout_per_item=30.0  # 30 second timeout per document
    )
    
    # Process results
    for i, result in enumerate(results):
        print(f"Document {i+1}: {len(result.entities)} entities extracted")
    
    return results

# Run async batch processing
results = asyncio.run(process_document_batch())
```

#### Async Streaming for Real-Time Processing

Stream extraction results asynchronously:

```python
async def stream_large_document():
    generator = OntologyGenerator()
    large_text = load_large_document()
    
    async for entity in generator.extract_with_streaming_async(
        large_text,
        context,
        chunk_size=1000
    ):
        # Process each entity as it arrives
        await save_to_database(entity)
        print(f"Processed: {entity.text}")

asyncio.run(stream_large_document())
```

#### Async Relationship Inference

Infer relationships asynchronously for large entity sets:

```python
async def infer_relationships_for_entities():
    generator = OntologyGenerator()
    
    # Extract entities first
    result = await generator.extract_entities_async(document, context)
    
    # Infer additional relationships asynchronously
    relationships = await generator.infer_relationships_async(
        result.entities,
        context
    )
    
    print(f"Inferred {len(relationships)} relationships")
    return relationships

relationships = asyncio.run(infer_relationships_for_entities())
```

---

## Agentic Optimizers

### Using the Agentic CLI

The agentic optimizer provides a command-line interface for optimization tasks:

```bash
# Initialize optimization session
python -m ipfs_datasets_py.optimizers.agentic init \
    --backend openai \
    --model gpt-4 \
    --task entity_extraction

# Run optimization on a document
python -m ipfs_datasets_py.optimizers.agentic optimize \
    --input contract.txt \
    --output entities.json \
    --domain legal \
    --verbose

# Batch process multiple files
python -m ipfs_datasets_py.optimizers.agentic batch \
    --input-dir ./documents \
    --output-dir ./results \
    --workers 4
```

### Programmatic Agentic Usage

Use agentic optimizers in Python code:

```python
from ipfs_datasets_py.optimizers.agentic import AgenticOptimizer

# Initialize with LLM backend
optimizer = AgenticOptimizer(
    backend="openai",
    model="gpt-4",
    temperature=0.7,
)

# Define optimization task
task = {
    "objective": "Extract all legal obligations from this contract",
    "constraints": ["Must identify parties", "Must extract deadlines"],
    "domain": "legal",
}

# Execute optimization
result = optimizer.optimize(document_text, task)

# Access structured results
for obligation in result.obligations:
    print(f"Party: {obligation.party}")
    print(f"Action: {obligation.action}")
    print(f"Deadline: {obligation.deadline}")
```

---

## Common Patterns

### Query Validation

All optimizers support automatic query validation through `QueryValidationMixin`:

```python
from ipfs_datasets_py.optimizers.common import QueryValidationMixin

class MyOptimizer(QueryValidationMixin):
    def process_query(self, query):
        # Validate numeric parameters
        max_results = self.validate_numeric_param(
            value=query.get("max_results"),
            param_name="max_results",
            min_value=1,
            max_value=1000,
            default=10,
        )
        
        # Validate list parameters
        edge_types = self.validate_list_param(
            value=query.get("edge_types"),
            param_name="edge_types",
            element_type=str,
            min_length=1,
            max_length=50,
            default=["ALL"],
        )
        
        # Validate enum parameters
        priority = self.validate_string_param(
            value=query.get("priority"),
            param_name="priority",
            allowed_values=["low", "normal", "high", "critical"],
            default="normal",
        )
        
        # Parameters are now validated and safe to use
        return {
            "max_results": max_results,
            "edge_types": edge_types,
            "priority": priority,
        }
```

### Caching Strategies

Optimize performance with query caching:

```python
from ipfs_datasets_py.optimizers.graphrag import UnifiedGraphRAGQueryOptimizer

optimizer = UnifiedGraphRAGQueryOptimizer()

# Generate cache key for query
query = {"vector": embedding, "max_results": 10}
cache_key = optimizer.generate_cache_key(query)

# Check if result is cached
if optimizer.validate_cache_entry(cache_key):
    result = optimizer.get_from_cache(cache_key)
    print("Cache hit!")
else:
    # Compute result and cache it
    result = expensive_graph_operation(query)
    optimizer.save_to_cache(cache_key, result)
    print("Cache miss - computed and cached")
```

### Handling Malformed Queries

Gracefully handle and repair malformed queries:

```python
# Malformed query with invalid values
malformed_query = {
    "max_results": 50000,  # Too large
    "min_similarity": 1.5,  # Out of bounds
    "priority": "URGENT",  # Invalid enum
    "edge_types": None,    # None instead of list
}

# Optimizer automatically corrects issues
optimized = optimizer.optimize_query(malformed_query)

# Results in valid query:
# {
#   "max_results": 1000,        # Clamped to max
#   "min_similarity": 1.0,       # Clamped to max
#   "priority": "high",          # Mapped to valid enum
#   "edge_types": [],            # Converted None to empty list
# }
```

---

## Troubleshooting

### Low Extraction Confidence

If extraction confidence is consistently low:

```python
# Check statistical metrics first
kurtosis = generator.history_kurtosis(results)
ewma = generator.score_ewma(results, alpha=0.3)

if ewma < 0.6:
    # Try switching to LLM-based extraction
    context.extraction_strategy = ExtractionStrategy.LLM_BASED
    
    # Or use hybrid approach
    context.extraction_strategy = ExtractionStrategy.HYBRID
    
    # Adjust confidence threshold
    context.extraction_config.confidence_threshold = 0.5  # Lower threshold
```

### Memory Issues with Large Documents

For documents causing memory issues:

```python
# Use streaming extraction
for entity in generator.extract_entities_streaming(large_doc, context):
    process_entity(entity)
    del entity  # Free memory immediately

# Or use async batch with chunking
from ipfs_datasets_py.optimizers.common import AsyncBatchProcessor

processor = AsyncBatchProcessor(max_concurrent=3)
results = await processor.process_batch_chunked(
    items=large_document_list,
    func=lambda doc: generator.extract_entities(doc, context),
    chunk_size=100  # Process 100 at a time
)
```

### Timeout Errors in AsyncBatch Processing

Handle timeouts gracefully:

```python
try:
    results = await generator.extract_batch_async(
        documents,
        context,
        max_concurrent=5,
        timeout_per_item=10.0  # 10 second timeout
    )
except asyncio.TimeoutError:
    # Reduce concurrency or increase timeout
    results = await generator.extract_batch_async(
        documents,
        context,
        max_concurrent=2,  # Reduced concurrency
        timeout_per_item=30.0  # Increased timeout
    )
```

### Query Validation Errors

Debug validation issues:

```python
# Enable validation logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Validation warnings will be logged
optimizer = UnifiedGraphRAGQueryOptimizer()
result = optimizer.optimize_query(query)

# Check what was corrected
original_query_key = optimizer.generate_cache_key(query)
optimized_query_key = optimizer.generate_cache_key(result)

if original_query_key != optimized_query_key:
    print("Query was modified during validation")
    print(f"Original: {query}")
    print(f"Optimized: {result}")
```

---

## Performance Tips

1. **Use async batch processing** for multiple documents
2. **Enable caching** for repeated queries
3. **Use streaming** for large documents
4. **Monitor EWMA** to detect quality degradation early
5. **Set appropriate timeouts** to prevent hanging operations
6. **Use property-based testing** to validate optimizer behavior

For more information, see the [API documentation](README.md) and [architecture guide](docs/ARCHITECTURE.md).
