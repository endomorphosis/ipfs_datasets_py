"""
Neo4j Exporter

Exports data from Neo4j database to IPLD format for migration to IPFS Graph Database.

Features:
- Batch processing for large databases
- Progress tracking
- Resume capability
- Schema export (indexes, constraints)
- Cypher-based extraction
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime
import time

from .formats import GraphData, NodeData, RelationshipData, SchemaData, MigrationFormat
from ..exceptions import MigrationError

logger = logging.getLogger(__name__)


@dataclass
class ExportConfig:
    """Configuration for Neo4j export."""
    
    # Connection
    uri: str = "bolt://localhost:7687"
    username: str = "neo4j"
    password: str = "password"
    database: str = "neo4j"
    
    # Export options
    batch_size: int = 1000  # Nodes/relationships per batch
    include_schema: bool = True
    include_indexes: bool = True
    include_constraints: bool = True
    
    # Output
    output_file: Optional[str] = None
    output_format: MigrationFormat = MigrationFormat.DAG_JSON
    
    # Progress
    progress_callback: Optional[Callable[[int, int, str], None]] = None
    
    # Filters
    node_labels: Optional[List[str]] = None  # Export only these labels
    relationship_types: Optional[List[str]] = None  # Export only these types


@dataclass
class ExportResult:
    """Result of export operation."""
    
    success: bool
    node_count: int = 0
    relationship_count: int = 0
    duration_seconds: float = 0.0
    output_file: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'success': self.success,
            'node_count': self.node_count,
            'relationship_count': self.relationship_count,
            'duration_seconds': self.duration_seconds,
            'output_file': self.output_file,
            'errors': self.errors,
            'warnings': self.warnings
        }


class Neo4jExporter:
    """
    Exports data from Neo4j to IPLD format.
    
    Usage:
        config = ExportConfig(
            uri="bolt://localhost:7687",
            username="neo4j",
            password="password",
            output_file="graph_export.json"
        )
        
        exporter = Neo4jExporter(config)
        result = exporter.export()
        
        if result.success:
            print(f"Exported {result.node_count} nodes and {result.relationship_count} relationships")
    """
    
    def __init__(self, config: ExportConfig):
        """
        Initialize exporter.
        
        Args:
            config: Export configuration
        """
        self.config = config
        self._driver = None
        self._neo4j_available = False
        
        # Try to import neo4j
        try:
            from neo4j import GraphDatabase
            self._GraphDatabase = GraphDatabase
            self._neo4j_available = True
        except ImportError:
            logger.warning("neo4j package not available. Install with: pip install neo4j")
            self._GraphDatabase = None
    
    def _connect(self) -> bool:
        """
        Connect to Neo4j database.
        
        Returns:
            True if connection successful
        """
        if not self._neo4j_available:
            raise MigrationError("neo4j package not installed. Install with: pip install neo4j")
        
        try:
            self._driver = self._GraphDatabase.driver(
                self.config.uri,
                auth=(self.config.username, self.config.password)
            )
            # Verify connection
            self._driver.verify_connectivity()
            logger.info("Connected to Neo4j at %s", self.config.uri)
            return True
        except MigrationError:
            raise
        except Exception as e:
            raise MigrationError(
                "Failed to connect to Neo4j",
                details={"uri": self.config.uri, "database": self.config.database},
            ) from e
    
    def _close(self) -> None:
        """Close Neo4j connection."""
        if self._driver:
            try:
                self._driver.close()
            except Exception as e:
                logger.warning(
                    "Failed to close Neo4j driver cleanly (%s): %s",
                    type(e).__name__,
                    e,
                )
            logger.info("Closed Neo4j connection")
    
    def _export_nodes(self, graph_data: GraphData) -> int:
        """
        Export nodes from Neo4j.
        
        Args:
            graph_data: GraphData object to populate
            
        Returns:
            Number of nodes exported
        """
        count = 0
        batch_num = 0
        
        # Build query
        query = "MATCH (n) RETURN id(n) as id, labels(n) as labels, properties(n) as properties"
        
        # Add label filter if specified
        if self.config.node_labels:
            label_conditions = " OR ".join([f"n:{label}" for label in self.config.node_labels])
            query = f"MATCH (n) WHERE {label_conditions} RETURN id(n) as id, labels(n) as labels, properties(n) as properties"
        
        with self._driver.session(database=self.config.database) as session:
            result = session.run(query)
            
            batch = []
            for record in result:
                node = NodeData(
                    id=str(record['id']),
                    labels=record['labels'],
                    properties=dict(record['properties'])
                )
                batch.append(node)
                count += 1
                
                # Process batch
                if len(batch) >= self.config.batch_size:
                    graph_data.nodes.extend(batch)
                    batch_num += 1
                    batch = []
                    
                    if self.config.progress_callback:
                        self.config.progress_callback(count, -1, f"Exported {count} nodes")
                    
                    logger.debug("Exported batch %d (%d nodes)", batch_num, count)
            
            # Add remaining nodes
            if batch:
                graph_data.nodes.extend(batch)
        
        logger.info("Exported %d nodes", count)
        return count
    
    def _export_relationships(self, graph_data: GraphData) -> int:
        """
        Export relationships from Neo4j.
        
        Args:
            graph_data: GraphData object to populate
            
        Returns:
            Number of relationships exported
        """
        count = 0
        batch_num = 0
        
        # Build query
        query = """
        MATCH (a)-[r]->(b)
        RETURN id(r) as id, type(r) as type, id(a) as start, id(b) as end, properties(r) as properties
        """
        
        # Add type filter if specified
        if self.config.relationship_types:
            type_conditions = " OR ".join([f"type(r) = '{t}'" for t in self.config.relationship_types])
            query = f"""
            MATCH (a)-[r]->(b)
            WHERE {type_conditions}
            RETURN id(r) as id, type(r) as type, id(a) as start, id(b) as end, properties(r) as properties
            """
        
        with self._driver.session(database=self.config.database) as session:
            result = session.run(query)
            
            batch = []
            for record in result:
                rel = RelationshipData(
                    id=str(record['id']),
                    type=record['type'],
                    start_node=str(record['start']),
                    end_node=str(record['end']),
                    properties=dict(record['properties'])
                )
                batch.append(rel)
                count += 1
                
                # Process batch
                if len(batch) >= self.config.batch_size:
                    graph_data.relationships.extend(batch)
                    batch_num += 1
                    batch = []
                    
                    if self.config.progress_callback:
                        self.config.progress_callback(-1, count, f"Exported {count} relationships")
                    
                    logger.debug("Exported batch %d (%d relationships)", batch_num, count)
            
            # Add remaining relationships
            if batch:
                graph_data.relationships.extend(batch)
        
        logger.info("Exported %d relationships", count)
        return count
    
    def _export_schema(self, graph_data: GraphData) -> None:
        """
        Export schema information (indexes, constraints).
        
        Args:
            graph_data: GraphData object to populate
        """
        if not self.config.include_schema:
            return
        
        schema = SchemaData()
        
        with self._driver.session(database=self.config.database) as session:
            # Get indexes
            if self.config.include_indexes:
                try:
                    result = session.run("SHOW INDEXES")
                    for record in result:
                        index_info = {
                            'name': record.get('name'),
                            'type': record.get('type'),
                            'labels': record.get('labelsOrTypes', []),
                            'properties': record.get('properties', [])
                        }
                        schema.indexes.append(index_info)
                    logger.info("Exported %d indexes", len(schema.indexes))
                except Exception as e:
                    logger.warning(
                        "Could not export indexes (%s): %s",
                        type(e).__name__,
                        e,
                    )
            
            # Get constraints
            if self.config.include_constraints:
                try:
                    result = session.run("SHOW CONSTRAINTS")
                    for record in result:
                        constraint_info = {
                            'name': record.get('name'),
                            'type': record.get('type'),
                            'labels': record.get('labelsOrTypes', []),
                            'properties': record.get('properties', [])
                        }
                        schema.constraints.append(constraint_info)
                    logger.info("Exported %d constraints", len(schema.constraints))
                except Exception as e:
                    logger.warning(
                        "Could not export constraints (%s): %s",
                        type(e).__name__,
                        e,
                    )
            
            # Get node labels
            result = session.run("CALL db.labels()")
            schema.node_labels = [record['label'] for record in result]
            logger.info("Found %d node labels", len(schema.node_labels))
            
            # Get relationship types
            result = session.run("CALL db.relationshipTypes()")
            schema.relationship_types = [record['relationshipType'] for record in result]
            logger.info("Found %d relationship types", len(schema.relationship_types))
        
        graph_data.schema = schema
    
    def export(self) -> ExportResult:
        """
        Export data from Neo4j.
        
        Returns:
            ExportResult with status and statistics
        """
        start_time = time.time()
        result = ExportResult(success=False)
        
        try:
            # Connect to Neo4j
            self._connect()
            
            # Create graph data
            graph_data = GraphData(metadata={
                'export_time': datetime.now().isoformat(),
                'source_uri': self.config.uri,
                'source_database': self.config.database
            })
            
            # Export nodes
            logger.info("Exporting nodes...")
            result.node_count = self._export_nodes(graph_data)
            
            # Export relationships
            logger.info("Exporting relationships...")
            result.relationship_count = self._export_relationships(graph_data)
            
            # Export schema
            if self.config.include_schema:
                logger.info("Exporting schema...")
                self._export_schema(graph_data)
            
            # Save to file if specified
            if self.config.output_file:
                logger.info("Saving to file: %s", self.config.output_file)
                graph_data.save_to_file(self.config.output_file, self.config.output_format)
                result.output_file = self.config.output_file
            
            # Calculate duration
            result.duration_seconds = time.time() - start_time
            result.success = True
            
            logger.info("Export completed successfully in %.2f seconds", result.duration_seconds)
            logger.info("Exported %d nodes and %d relationships", 
                       result.node_count, result.relationship_count)
            
            return result
            
        except MigrationError as e:
            logger.error("Export failed: %s", e, exc_info=True)
            result.errors.append(str(e))
            result.duration_seconds = time.time() - start_time
            return result

        except Exception as e:
            logger.error("Export failed unexpectedly: %s", e, exc_info=True)
            result.errors.append(
                str(
                    MigrationError(
                        "Export failed unexpectedly",
                        details={"error": str(e), "error_class": type(e).__name__},
                    )
                )
            )
            result.duration_seconds = time.time() - start_time
            return result
        
        finally:
            self._close()
    
    def export_to_graph_data(self) -> Optional[GraphData]:
        """
        Export directly to GraphData object without saving to file.
        
        Returns:
            GraphData object or None if export fails
        """
        # Temporarily disable file output
        original_output = self.config.output_file
        self.config.output_file = None
        
        try:
            # Connect and create graph data
            self._connect()
            
            graph_data = GraphData(metadata={
                'export_time': datetime.now().isoformat(),
                'source_uri': self.config.uri,
                'source_database': self.config.database
            })
            
            # Export data
            self._export_nodes(graph_data)
            self._export_relationships(graph_data)
            
            if self.config.include_schema:
                self._export_schema(graph_data)
            
            return graph_data

        except MigrationError:
            return None
            
        finally:
            self._close()
            self.config.output_file = original_output
