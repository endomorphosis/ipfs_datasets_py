"""
Migration Tools for Neo4j ↔ IPFS Graph Database

This module provides tools for migrating data between Neo4j and IPFS Graph Database,
enabling seamless transitions and data portability.

Components:
- Neo4j Exporter: Export data from Neo4j to IPLD format
- IPFS Importer: Import IPLD data into IPFS Graph Database
- Schema Checker: Validate schema compatibility
- Integrity Verifier: Verify data integrity after migration

Example usage:

# Export from Neo4j:
from ipfs_datasets_py.knowledge_graphs.migration import Neo4jExporter, ExportConfig

config = ExportConfig(
    uri="bolt://localhost:7687",
    username="neo4j",
    password="password",
    output_file="graph_export.json"
)

exporter = Neo4jExporter(config)
result = exporter.export()

# Import to IPFS:
from ipfs_datasets_py.knowledge_graphs.migration import IPFSImporter, ImportConfig

config = ImportConfig(
    input_file="graph_export.json"
)

importer = IPFSImporter(config)
result = importer.import_data()
"""

from .neo4j_exporter import Neo4jExporter, ExportConfig, ExportResult
from .ipfs_importer import IPFSImporter, ImportConfig, ImportResult
from .schema_checker import SchemaChecker, CompatibilityReport
from .integrity_verifier import IntegrityVerifier, VerificationReport
from .formats import (
    GraphData,
    NodeData,
    RelationshipData,
    SchemaData,
    MigrationFormat,
    register_format,
    registered_formats,
)

__all__ = [
    # Exporter
    'Neo4jExporter',
    'ExportConfig',
    'ExportResult',
    
    # Importer
    'IPFSImporter',
    'ImportConfig',
    'ImportResult',
    
    # Checker
    'SchemaChecker',
    'CompatibilityReport',
    
    # Verifier
    'IntegrityVerifier',
    'VerificationReport',
    
    # Formats
    'GraphData',
    'NodeData',
    'RelationshipData',
    'SchemaData',
    'MigrationFormat',
    # Format registry
    'register_format',
    'registered_formats',
]
