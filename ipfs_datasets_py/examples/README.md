# Enhanced Data Provenance Examples

This directory contains examples demonstrating the enhanced data provenance tracking capabilities of the IPFS Datasets Python library.

## Overview

The enhanced data provenance system builds upon the base provenance tracking system to provide:

1. **Advanced visualization** with multiple engines and formats
2. **Extended record types** for comprehensive tracking
3. **Graph-based metrics** for complexity and impact analysis
4. **Semantic search** for finding relevant provenance records
5. **Temporal queries** for time-based analysis
6. **IPLD integration** for distributed provenance tracking
7. **Audit logging integration** for security and compliance

## Example Files

### `data_provenance_example.py`

This example demonstrates a complete data processing pipeline with enhanced provenance tracking:

- Recording data sources
- Data cleaning and validation
- Feature engineering
- Model training and inference
- Visualization and reporting
- Semantic search
- Metrics calculation

Run this example to see how provenance tracking works throughout a typical data science workflow:

```bash
python3 -m ipfs_datasets_py.examples.data_provenance_example
```

### `ipld_provenance_integration.py`

This example shows how to use IPLD (InterPlanetary Linked Data) for distributed provenance tracking across multiple organizations:

- Organization A collects and preprocesses data
- Organization B performs analysis and model training
- Organization C deploys the model and runs inference
- Full provenance chain is maintained with verifiable content-addressed data

Run this example to see how distributed provenance works across organizations:

```bash
python3 -m ipfs_datasets_py.examples.ipld_provenance_integration
```

## Key Concepts

### Provenance Records

The enhanced system includes additional record types:

- **VerificationRecord**: For data validation and quality checks
- **AnnotationRecord**: For manual notes and comments
- **ModelTrainingRecord**: For ML model training events
- **ModelInferenceRecord**: For model inference events

### Visualization Engines

Multiple visualization engines are supported:

- **matplotlib**: Default engine with custom layouts and styling
- **plotly**: Interactive visualizations with HTML export
- **dash**: Dashboard-style visualizations with Cytoscape

### Provenance Metrics

Advanced metrics for analyzing data lineage:

- **Impact metrics**: How data affects downstream entities
- **Centrality metrics**: Key nodes in the provenance graph
- **Complexity metrics**: Depth, breadth, and density of lineage
- **Time metrics**: Age and update frequency of data

### IPLD Integration

Content-addressed storage for provenance with:

- Verifiable content identifiers (CIDs)
- Immutable provenance chains
- Distributed tracking across organizations
- CAR file export for provenance exchange

## Usage Recommendations

1. Use a consistent naming scheme for data entity IDs
2. Record all major processing steps with appropriate detail
3. Include validation and verification steps
4. Add annotations for human context and decisions
5. Use the appropriate visualization for your audience
6. Export provenance data regularly for archiving

## See Also

- [Data Provenance Documentation](../../docs/data_provenance.md)
- [IPLD Storage Documentation](../../docs/ipld.md)
- [Audit Logging Documentation](../../docs/audit_logging.md)