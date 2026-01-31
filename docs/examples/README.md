# Examples

Usage examples demonstrating IPFS Datasets Python capabilities.

## Available Examples

### Integration Examples
- [Integration Examples](integration_examples.md) - System integration patterns
- [Workflow Examples](workflow_examples.md) - Complete workflow demonstrations
- [Advanced Examples](advanced_examples.md) - Complex scenarios and use cases

### Domain-Specific Examples
- [Discord Usage Examples](discord_usage_examples.md) - Discord bot integration
- [Email Usage Examples](email_usage_examples.md) - Email processing workflows
- [Finance Usage Examples](finance_usage_examples.md) - Financial data processing

## Example Categories

### Data Processing
```python
# Load and process datasets
from ipfs_datasets_py import DatasetManager

dm = DatasetManager()
dataset = dm.load_dataset("squad")
processed = dm.process(dataset)
```

### Vector Search
```python
# Semantic search
from ipfs_datasets_py.search import SearchEngine

search = SearchEngine()
results = search.search("your query", top_k=10)
```

### PDF Processing
```python
# Process PDFs with GraphRAG
from ipfs_datasets_py.pdf_processing import PDFProcessor
from ipfs_datasets_py.rag import GraphRAG

pdf = PDFProcessor()
graph = GraphRAG()

content = pdf.process("document.pdf")
graph.add_document(content)
```

### Multimedia
```python
# Download and process media
from ipfs_datasets_py.multimedia import MediaToolManager

media = MediaToolManager()
result = media.download("https://youtube.com/watch?v=...")
```

## Running Examples

All examples are runnable:

```bash
# From repository root
python examples/example_name.py
```

## Demo Scripts

For comprehensive demos, see:
- `scripts/demo/demonstrate_complete_pipeline.py` - Full theorem proving pipeline
- `scripts/demo/demonstrate_graphrag_pdf.py` - GraphRAG PDF processing
- `scripts/demo/demonstrate_legal_deontic_logic.py` - Legal logic conversion

## Need More Examples?

See also:
- [User Guide](../user_guide.md) - Comprehensive usage guide
- [Tutorials](../tutorials/) - Step-by-step tutorials
- [Getting Started](../getting_started.md) - Quick start guide

## Contributing Examples

To add an example:
1. Create a standalone, runnable Python file
2. Include docstrings and comments
3. Add to this README
4. Test thoroughly
