# Knowledge Graphs Migration Guide

## Overview

This guide helps you migrate from the old duplicate lineage tracking modules to the new consolidated `lineage/` package.

## Quick Start

### Old Way (Deprecated)
```python
from ipfs_datasets_py.knowledge_graphs.cross_document_lineage import (
    CrossDocumentLineageTracker,
    LineageNode,
    LineageLink
)

# Old API
tracker = CrossDocumentLineageTracker()
```

### New Way (Recommended)
```python
from ipfs_datasets_py.knowledge_graphs.lineage import (
    LineageTracker,
    LineageNode,
    LineageLink
)

# New unified API
tracker = LineageTracker()
```

## API Mapping

### Core Classes

| Old Module | Old Class | New Module | New Class |
|------------|-----------|------------|-----------|
| cross_document_lineage | CrossDocumentLineageTracker | lineage.core | LineageTracker |
| cross_document_lineage | EnhancedLineageTracker | lineage.enhanced | EnhancedLineageTracker |
| cross_document_lineage | LineageNode | lineage.types | LineageNode |
| cross_document_lineage | LineageLink | lineage.types | LineageLink |
| cross_document_lineage_enhanced | CrossDocumentLineageEnhancer | lineage.enhanced | SemanticAnalyzer |

### Method Mapping

| Old Method | New Method | Notes |
|------------|------------|-------|
| track_entity() | track_node() | Renamed for consistency |
| add_relationship() | track_link() | Renamed for consistency |
| get_lineage() | find_lineage_path() | More descriptive name |
| analyze_impact() | Use ImpactAnalyzer class | Now separate analyzer |

## Migration Steps

### Step 1: Update Imports

**Before:**
```python
from ipfs_datasets_py.knowledge_graphs.cross_document_lineage import (
    CrossDocumentLineageTracker,
    LineageNode,
    LineageLink,
    LineageDomain
)
```

**After:**
```python
from ipfs_datasets_py.knowledge_graphs.lineage import (
    LineageTracker,
    LineageNode,
    LineageLink,
    LineageDomain
)
```

### Step 2: Update Class Instantiation

**Before:**
```python
tracker = CrossDocumentLineageTracker(
    enable_semantic_analysis=True,
    enable_boundary_detection=True
)
```

**After:**
```python
from ipfs_datasets_py.knowledge_graphs.lineage import EnhancedLineageTracker

tracker = EnhancedLineageTracker(
    enable_temporal_consistency=True
)
# Semantic analysis and boundary detection are built-in
```

### Step 3: Update Method Calls

**Before:**
```python
# Track entities
tracker.track_entity(
    entity_id="dataset_1",
    entity_type="dataset",
    metadata={"name": "users"}
)

# Add relationships
tracker.add_relationship(
    source_id="dataset_1",
    target_id="dataset_2",
    relationship_type="derived_from"
)
```

**After:**
```python
# Track nodes (entities)
tracker.track_node(
    node_id="dataset_1",
    node_type="dataset",
    metadata={"name": "users"}
)

# Track links (relationships)
tracker.track_link(
    source_id="dataset_1",
    target_id="dataset_2",
    relationship_type="derived_from"
)
```

### Step 4: Update Analysis Code

**Before:**
```python
# Old embedded analysis
tracker.analyze_downstream_impact("dataset_1")
tracker.calculate_metrics()
```

**After:**
```python
# New separate analyzers
from ipfs_datasets_py.knowledge_graphs.lineage import ImpactAnalyzer, LineageMetrics

# Impact analysis
analyzer = ImpactAnalyzer(tracker)
impact = analyzer.analyze_downstream_impact("dataset_1")

# Metrics
metrics = LineageMetrics(tracker.graph)
stats = metrics.compute_basic_stats()
```

### Step 5: Update Visualization

**Before:**
```python
# Old visualization was embedded
tracker.visualize(output_path="lineage.png")
```

**After:**
```python
# New separate visualization
from ipfs_datasets_py.knowledge_graphs.lineage import visualize_lineage

# Static visualization
visualize_lineage(tracker, "lineage.png", renderer="networkx")

# Interactive visualization
visualize_lineage(tracker, "lineage.html", renderer="plotly")
```

## Feature Comparison

### New Features

The new `lineage/` package includes features not in the old modules:

**Enhanced Analysis:**
- `SemanticAnalyzer` - Relationship categorization and similarity
- `BoundaryDetector` - Automatic boundary detection
- `ConfidenceScorer` - Uncertainty propagation

**Visualization:**
- Multiple rendering engines (NetworkX, Plotly)
- Interactive HTML visualizations
- Customizable layouts

**Metrics:**
- Comprehensive graph statistics
- Impact analysis
- Dependency analysis
- Critical node identification

### Removed Features

Some rarely-used features were not migrated:
- Legacy XML export (use JSON instead)
- Obsolete database connectors (use modern APIs)

If you need these features, please file an issue.

## Examples

### Complete Migration Example

**Before (Old API):**
```python
from ipfs_datasets_py.knowledge_graphs.cross_document_lineage import (
    CrossDocumentLineageTracker
)

# Create tracker
tracker = CrossDocumentLineageTracker()

# Track data pipeline
tracker.track_entity("raw_data", "dataset")
tracker.track_entity("cleaned_data", "dataset")
tracker.add_relationship("raw_data", "cleaned_data", "derived_from")

# Get lineage
lineage = tracker.get_lineage("raw_data", "cleaned_data")

# Visualize
tracker.visualize("lineage.png")
```

**After (New API):**
```python
from ipfs_datasets_py.knowledge_graphs.lineage import (
    LineageTracker,
    visualize_lineage
)

# Create tracker
tracker = LineageTracker()

# Track data pipeline
tracker.track_node("raw_data", "dataset")
tracker.track_node("cleaned_data", "dataset")
tracker.track_link("raw_data", "cleaned_data", "derived_from")

# Get lineage
path = tracker.find_lineage_path("raw_data", "cleaned_data")

# Visualize (with more options)
visualize_lineage(tracker, "lineage.html", renderer="plotly")
```

### Advanced Features Example

```python
from ipfs_datasets_py.knowledge_graphs.lineage import (
    EnhancedLineageTracker,
    ImpactAnalyzer,
    LineageMetrics,
    visualize_lineage
)

# Create enhanced tracker
tracker = EnhancedLineageTracker()

# Track with automatic boundary detection
tracker.track_node("ds_prod", "dataset", metadata={"system": "production"})
tracker.track_node("ds_analytics", "dataset", metadata={"system": "analytics"})
tracker.track_link_with_analysis(
    "ds_prod", "ds_analytics", "replicated_to",
    auto_detect_boundary=True  # Automatically detects system boundary
)

# Analyze impact
analyzer = ImpactAnalyzer(tracker)
impact = analyzer.analyze_downstream_impact("ds_prod")
print(f"Total downstream entities: {impact['total_downstream']}")

# Get metrics
metrics = LineageMetrics(tracker.graph)
stats = metrics.compute_basic_stats()
print(f"Graph density: {stats['density']:.2%}")

# Find critical nodes
critical = analyzer.find_critical_nodes(threshold=3)
for node in critical:
    print(f"Critical: {node['node_id']} ({node['connections']} connections)")

# Visualize
visualize_lineage(tracker, "lineage_interactive.html", renderer="plotly")
```

## Deprecation Timeline

- **Now**: New API available, old modules still work
- **Month 3**: Old modules show deprecation warnings
- **Month 6**: Old modules archived, adapters provided
- **Month 12**: Old modules removed

## Getting Help

- **Documentation**: See module docstrings in `lineage/` package
- **Examples**: Check `tests/unit/knowledge_graphs/lineage/` for examples
- **Issues**: File issues on GitHub for migration problems

## FAQ

**Q: Will my existing code break?**
A: No. Old modules remain unchanged. You can migrate gradually.

**Q: What if I can't migrate yet?**
A: Old modules will work for at least 6 months with deprecation warnings after 3 months.

**Q: Is the new API compatible?**
A: The new API is similar but not identical. Use this guide to migrate.

**Q: Are there performance differences?**
A: The new implementation is generally faster due to better structure.

**Q: Can I use both old and new APIs?**
A: Yes, but not recommended. Choose one approach per project.

**Q: What about my existing data?**
A: Data structures (LineageNode, LineageLink) are compatible. You can load old data with the new API.
