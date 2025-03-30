# Data Provenance Reporting and Visualization

This module provides comprehensive data provenance tracking, reporting, and visualization capabilities for the IPFS Datasets Python library. It enables detailed tracking of data lineage, transformations, and access patterns, as well as generating formatted reports and visualizations.

## Key Features

### Provenance Tracking
- Comprehensive tracking of data origins, transformations, and accesses
- Detailed recording of transformation steps with parameters and metrics
- Parent-child relationship tracking between datasets
- Access history with timestamps, users, and operations
- Support for verification status and metadata

### Provenance Reporting
- Generate detailed reports in multiple formats (JSON, Text, HTML, Markdown)
- Multiple report types (summary, detailed, technical, compliance)
- Customizable report content with optional lineage and access history
- Rich formatting with tables, headings, and structured data

### Lineage Visualization
- Visual representations of data lineage relationships
- Multiple visualization formats (DOT, Mermaid, D3.js, JSON)
- Node styling based on data type
- Custom node labels and edge relationships
- Support for directional traversal (upstream, downstream, or both)

## Usage Examples

### Recording Data Provenance

```python
from ipfs_datasets_py.security import SecurityManager, SecurityConfig

# Initialize security manager
security_manager = SecurityManager.initialize(SecurityConfig(track_provenance=True))

# Record provenance for a dataset
security_manager.record_provenance(
    data_id="dataset_123",
    source="example_source",
    creator="example_user",
    creation_time="2023-05-15T10:30:00",
    process_steps=[],
    parent_ids=[],
    checksum="0x123456789abcdef",
    version="1.0",
    data_type="dataset",
    schema={"columns": ["id", "name", "value"]},
    size_bytes=1024,
    record_count=100,
    content_type="application/json",
    lineage_info={
        "source_system": "example_system",
        "source_type": "database",
        "extraction_method": "sql_query",
        "extraction_time": "2023-05-15T10:15:00"
    },
    tags=["example", "sample"]
)
```

### Recording Transformation Steps

```python
# Record a transformation step
step_id = security_manager.record_transformation_step(
    data_id="source_dataset_123",
    operation="filter",
    description="Filter rows where value > 50",
    tool="duckdb",
    parameters={"condition": "value > 50"},
    inputs=["source_dataset_123"],
    outputs=["filtered_dataset_456"]
)

# Complete the transformation step
security_manager.complete_transformation_step(
    data_id="source_dataset_123",
    step_id=step_id,
    status="completed",
    outputs=["filtered_dataset_456"],
    metrics={"execution_time_ms": 150, "filtered_rows": 30}
)
```

### Recording Data Access

```python
# Record a data access event
security_manager.record_data_access(
    data_id="dataset_123",
    operation="read",
    details={
        "reason": "Example read access",
        "user_id": "user_456",
        "system": "example_system"
    }
)
```

### Generating Provenance Reports

```python
# Generate a detailed report in HTML format
report = security_manager.generate_provenance_report(
    data_id="dataset_123",
    report_type="detailed",
    format="html",
    include_lineage=True,
    include_access_history=True
)

# Save the HTML report to a file
with open("provenance_report.html", "w") as f:
    f.write(report["html_content"])
```

### Generating Lineage Visualizations

```python
# Generate a lineage visualization in DOT format for GraphViz
visualization = security_manager.generate_lineage_visualization(
    data_id="dataset_123",
    format="dot",
    max_depth=3,
    direction="both",
    include_attributes=True
)

# Save the DOT visualization to a file
with open("lineage.dot", "w") as f:
    f.write(visualization["dot_content"])
```

## Report Types

### Summary Report
- Basic information about the dataset
- High-level lineage information
- Access summary statistics
- Verification status

### Detailed Report
- Comprehensive dataset information
- Complete lineage with upstream and downstream datasets
- Transformation history with descriptions
- Access history with timestamps and users

### Technical Report
- All information from the detailed report
- Technical details about transformations (parameters, metrics)
- Detailed lineage graph representation
- Complete access history with all details

### Compliance Report
- Information relevant for compliance and audit purposes
- Verification status and history
- Access history focused on who accessed what and when
- Parent-child relationships for data traceability

## Visualization Formats

### DOT Format
- GraphViz DOT language for rendering directed graphs
- Node colors based on data type
- Edge labels showing relationship types
- Hierarchical layout of data lineage

### Mermaid Format
- Mermaid flowchart notation for web-based rendering
- Styled nodes based on data type
- Directional edges with relationship labels
- Compatible with many documentation systems

### D3.js Format
- JSON format for use with D3.js force-directed graphs
- Node grouping by data type for visual styling
- Force-directed layout for interactive exploration
- Ideal for web-based visualizations

### JSON Format
- Raw JSON representation of the lineage graph
- Complete node and edge information
- Attributes for nodes and edges
- Suitable for custom visualization solutions

## Example Workflow

See the complete example in `provenance_report_example.py` that demonstrates:

1. Creating a sample data transformation pipeline with multiple steps
2. Recording provenance information for each dataset
3. Tracking transformations through multiple processing steps
4. Recording data access events
5. Generating provenance reports in different formats
6. Creating lineage visualizations for data exploration

Run the example with:

```bash
python -m ipfs_datasets_py.provenance_report_example
```

The example will generate multiple report and visualization outputs in the `~/provenance_reports` directory.

## Integration with External Tools

### GraphViz Integration
The DOT format visualizations can be rendered with GraphViz:

```bash
dot -Tpng lineage.dot -o lineage.png
```

### Mermaid Integration
Mermaid diagrams can be rendered in many markdown viewers, or using the Mermaid CLI:

```bash
mmdc -i lineage.mmd -o lineage.svg
```

### D3.js Integration
The D3.js format can be used in web applications for interactive visualization:

```html
<script src="https://d3js.org/d3.v7.min.js"></script>
<script>
  fetch('lineage_d3.json')
    .then(response => response.json())
    .then(graph => {
      // Create interactive visualization
      const svg = d3.select("svg");
      const simulation = d3.forceSimulation(graph.nodes)
        .force("link", d3.forceLink(graph.links).id(d => d.id))
        .force("charge", d3.forceManyBody())
        .force("center", d3.forceCenter(width / 2, height / 2));
        
      // Render nodes and links
      // ...
    });
</script>
```

## Advanced Usage

### Custom Report Formatting
You can customize the report format by accessing the raw report data and applying your own formatting logic:

```python
# Get raw report data in JSON format
report_data = security_manager.generate_provenance_report(
    data_id="dataset_123",
    report_type="detailed",
    format="json"
)

# Apply custom formatting
import jinja2
template = jinja2.Template("""
<html>
  <head><title>{{ report.data_info.data_id }} - Provenance Report</title></head>
  <body>
    <h1>{{ report.data_info.data_id }}</h1>
    <!-- Custom formatting logic -->
  </body>
</html>
""")

html_content = template.render(report=report_data)
```

### Extended Lineage Traversal
You can control how far the lineage visualization extends and in which direction:

```python
# Upstream-only lineage (data sources)
upstream_visualization = security_manager.generate_lineage_visualization(
    data_id="dataset_123",
    direction="upstream",
    max_depth=2
)

# Downstream-only lineage (derived datasets)
downstream_visualization = security_manager.generate_lineage_visualization(
    data_id="dataset_123",
    direction="downstream",
    max_depth=2
)
```

### Verifying Data Provenance
You can verify the integrity of a dataset's provenance:

```python
# Verify data provenance using checksum
is_valid = security_manager.verify_data_provenance(
    data_id="dataset_123",
    verification_method="checksum"
)

# Verify data provenance using parent consistency
is_valid = security_manager.verify_data_provenance(
    data_id="dataset_123",
    verification_method="parent_consistency"
)
```