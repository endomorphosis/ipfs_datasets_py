"""
Investigation and analysis package for ipfs_datasets_py.

Provides data ingestion and geospatial analysis for investigative workflows.

Reusable by:
- MCP server tools (mcp_server/tools/investigation_tools/)
- CLI commands
- Direct Python imports
"""
from .data_ingestion_engine import DataIngestionEngine
from .geospatial_analysis_engine import GeospatialAnalysisEngine
from .entity_analysis_engine import (  # noqa: F401
    extract_entities_from_document,
    cluster_entities,
    analyze_entity_relationships,
    count_entity_types,
    analyze_confidence_distribution,
    find_entity_in_corpus,
    get_entity_relationships,
    generate_entity_timeline,
    get_entity_sources,
)

__all__ = [
    "DataIngestionEngine",
    "GeospatialAnalysisEngine",
    "extract_entities_from_document",
    "cluster_entities",
    "analyze_entity_relationships",
    "count_entity_types",
    "analyze_confidence_distribution",
    "find_entity_in_corpus",
    "get_entity_relationships",
    "generate_entity_timeline",
    "get_entity_sources",
]
