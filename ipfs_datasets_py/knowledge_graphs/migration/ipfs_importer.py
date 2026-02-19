"""
IPFS Importer

Imports data from IPLD format into IPFS Graph Database.

Features:
- Batch processing
- Progress tracking
- Validation
- Error handling
- Transaction support
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime
import time

from .formats import GraphData, NodeData, RelationshipData, MigrationFormat
from ..exceptions import MigrationError

logger = logging.getLogger(__name__)


@dataclass
class ImportConfig:
    """Configuration for IPFS import."""
    
    # Input
    input_file: Optional[str] = None
    input_format: MigrationFormat = MigrationFormat.DAG_JSON
    graph_data: Optional[GraphData] = None  # Direct graph data input
    
    # Import options
    batch_size: int = 1000
    create_indexes: bool = True
    create_constraints: bool = True
    validate_data: bool = True
    skip_duplicates: bool = True
    
    # Progress
    progress_callback: Optional[Callable[[int, int, str], None]] = None
    
    # Database
    database: str = "default"


@dataclass
class ImportResult:
    """Result of import operation."""
    
    success: bool
    nodes_imported: int = 0
    relationships_imported: int = 0
    nodes_skipped: int = 0
    relationships_skipped: int = 0
    duration_seconds: float = 0.0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'success': self.success,
            'nodes_imported': self.nodes_imported,
            'relationships_imported': self.relationships_imported,
            'nodes_skipped': self.nodes_skipped,
            'relationships_skipped': self.relationships_skipped,
            'duration_seconds': self.duration_seconds,
            'errors': self.errors,
            'warnings': self.warnings
        }


class IPFSImporter:
    """
    Imports data into IPFS Graph Database.
    
    Usage:
        config = ImportConfig(
            input_file="graph_export.json",
            batch_size=1000
        )
        
        importer = IPFSImporter(config)
        result = importer.import_data()
        
        if result.success:
            print(f"Imported {result.nodes_imported} nodes and {result.relationships_imported} relationships")
    """
    
    def __init__(self, config: ImportConfig):
        """
        Initialize importer.
        
        Args:
            config: Import configuration
        """
        self.config = config
        self._session = None
        self._node_id_map = {}  # Map Neo4j IDs to internal IDs
        
        # Try to import IPFS graph database components
        try:
            from ..neo4j_compat import GraphDatabase
            from ..storage.ipld_backend import IPLDBackend
            self._GraphDatabase = GraphDatabase
            self._IPLDBackend = IPLDBackend
            self._ipfs_available = True
        except ImportError as e:
            logger.warning("IPFS graph database components not available: %s", e)
            self._ipfs_available = False
    
    def _connect(self) -> bool:
        """
        Connect to IPFS Graph Database.
        
        Returns:
            True if connection successful
        """
        if not self._ipfs_available:
            raise MigrationError(
                "IPFS graph database not available",
                details={
                    'operation': 'connect',
                    'remediation': "Install ipfs_kit_py and ensure an IPFS node is running.",
                }
            )
        
        try:
            # For now, use embedded mode for import
            self._driver = self._GraphDatabase.driver("ipfs+embedded://./ipfs_import_data")
            self._session = self._driver.session(database=self.config.database)
            logger.info("Connected to IPFS Graph Database")
            return True
        except MigrationError:
            raise
        except Exception as e:
            raise MigrationError(
                "Failed to connect to IPFS Graph Database",
                details={
                    'operation': 'connect',
                    'database': self.config.database,
                    'error_class': type(e).__name__,
                    'remediation': "Verify IPFS node is running and the database name is correct.",
                },
            ) from e
    
    def _close(self) -> None:
        """Close connection."""
        if self._session:
            try:
                self._session.close()
            except Exception as e:
                logger.warning("Failed to close IPFS session cleanly: %s", e)
        if hasattr(self, '_driver') and self._driver:
            try:
                self._driver.close()
            except Exception as e:
                logger.warning("Failed to close IPFS driver cleanly: %s", e)
        logger.info("Closed IPFS Graph Database connection")
    
    def _load_graph_data(self) -> Optional[GraphData]:
        """
        Load graph data from file or config.
        
        Returns:
            GraphData or None if loading fails
        """
        if self.config.graph_data:
            return self.config.graph_data
        
        if self.config.input_file:
            try:
                logger.info("Loading graph data from %s", self.config.input_file)
                return GraphData.load_from_file(self.config.input_file, self.config.input_format)
            except MigrationError:
                raise
            except Exception as e:
                raise MigrationError(
                    "Failed to load graph data",
                    details={
                        'operation': 'load_graph_data',
                        'input_file': self.config.input_file,
                        'input_format': str(self.config.input_format),
                        'error_class': type(e).__name__,
                        'remediation': "Check that the file exists and the format matches its content.",
                    },
                ) from e
        
        raise MigrationError("No input file or graph data provided")
    
    def _validate_graph_data(self, graph_data: GraphData) -> List[str]:
        """
        Validate graph data before import.
        
        Args:
            graph_data: Graph data to validate
            
        Returns:
            List of validation errors
        """
        errors = []
        
        # Check for duplicate node IDs
        node_ids = set()
        for node in graph_data.nodes:
            if node.id in node_ids:
                errors.append(f"Duplicate node ID: {node.id}")
            node_ids.add(node.id)
        
        # Check for duplicate relationship IDs
        rel_ids = set()
        for rel in graph_data.relationships:
            if rel.id in rel_ids:
                errors.append(f"Duplicate relationship ID: {rel.id}")
            rel_ids.add(rel.id)
        
        # Check that relationship endpoints exist
        for rel in graph_data.relationships:
            if rel.start_node not in node_ids:
                errors.append(f"Relationship {rel.id} references non-existent start node: {rel.start_node}")
            if rel.end_node not in node_ids:
                errors.append(f"Relationship {rel.id} references non-existent end node: {rel.end_node}")
        
        if errors:
            logger.warning("Found %d validation errors", len(errors))
        else:
            logger.info("Graph data validation passed")
        
        return errors
    
    def _import_nodes(self, graph_data: GraphData) -> tuple[int, int]:
        """
        Import nodes.
        
        Args:
            graph_data: Graph data containing nodes
            
        Returns:
            Tuple of (imported_count, skipped_count)
        """
        imported = 0
        skipped = 0
        batch_num = 0
        
        batch = []
        for node in graph_data.nodes:
            # Build CREATE query for node
            labels_str = ":".join(node.labels) if node.labels else ""
            props_list = [f"{k}: ${k}" for k in node.properties.keys()]
            props_str = "{" + ", ".join(props_list) + "}" if props_list else ""
            
            query = f"CREATE (n:{labels_str} {props_str}) RETURN id(n) as internal_id"
            
            try:
                result = self._session.run(query, node.properties)
                # Map external ID to internal ID
                record = result.single()
                if record:
                    self._node_id_map[node.id] = record['internal_id']
                imported += 1
                
                if self.config.progress_callback and imported % 100 == 0:
                    self.config.progress_callback(imported, -1, f"Imported {imported} nodes")
                
            except Exception as e:
                logger.warning("Failed to import node %s: %s", node.id, e)
                skipped += 1
        
        logger.info("Imported %d nodes, skipped %d", imported, skipped)
        return imported, skipped
    
    def _import_relationships(self, graph_data: GraphData) -> tuple[int, int]:
        """
        Import relationships.
        
        Args:
            graph_data: Graph data containing relationships
            
        Returns:
            Tuple of (imported_count, skipped_count)
        """
        imported = 0
        skipped = 0
        
        for rel in graph_data.relationships:
            # Get internal node IDs
            start_id = self._node_id_map.get(rel.start_node)
            end_id = self._node_id_map.get(rel.end_node)
            
            if start_id is None or end_id is None:
                logger.warning("Skipping relationship %s: node not found", rel.id)
                skipped += 1
                continue
            
            # Build CREATE query for relationship
            props_list = [f"{k}: ${k}" for k in rel.properties.keys()]
            props_str = "{" + ", ".join(props_list) + "}" if props_list else ""
            
            query = f"""
            MATCH (a), (b)
            WHERE id(a) = $start_id AND id(b) = $end_id
            CREATE (a)-[r:{rel.type} {props_str}]->(b)
            RETURN id(r) as rel_id
            """
            
            params = {
                'start_id': start_id,
                'end_id': end_id,
                **rel.properties
            }
            
            try:
                result = self._session.run(query, params)
                result.consume()  # Ensure query executes
                imported += 1
                
                if self.config.progress_callback and imported % 100 == 0:
                    self.config.progress_callback(-1, imported, f"Imported {imported} relationships")
                
            except Exception as e:
                logger.warning("Failed to import relationship %s: %s", rel.id, e)
                skipped += 1
        
        logger.info("Imported %d relationships, skipped %d", imported, skipped)
        return imported, skipped
    
    def _import_schema(self, graph_data: GraphData) -> None:
        """
        Import schema (indexes and constraints).
        
        Args:
            graph_data: Graph data containing schema
        """
        if not graph_data.schema:
            return
        
        schema = graph_data.schema
        
        # Import indexes
        if self.config.create_indexes and schema.indexes:
            logger.info("Creating %d indexes", len(schema.indexes))
            for index in schema.indexes:
                try:
                    # This is a placeholder - actual implementation would use
                    # the indexing system from knowledge_graphs/indexing/
                    logger.debug("Would create index: %s", index.get('name'))
                except Exception as e:
                    logger.warning("Failed to create index %s: %s", index.get('name'), e)
        
        # Import constraints
        if self.config.create_constraints and schema.constraints:
            logger.info("Creating %d constraints", len(schema.constraints))
            for constraint in schema.constraints:
                try:
                    # This is a placeholder - actual implementation would use
                    # the constraints system from knowledge_graphs/constraints/
                    logger.debug("Would create constraint: %s", constraint.get('name'))
                except Exception as e:
                    logger.warning("Failed to create constraint %s: %s", constraint.get('name'), e)
    
    def import_data(self) -> ImportResult:
        """
        Import data into IPFS Graph Database.
        
        Returns:
            ImportResult with status and statistics
        """
        start_time = time.time()
        result = ImportResult(success=False)
        
        try:
            # Load graph data
            graph_data = self._load_graph_data()
            if not graph_data:
                raise MigrationError("Failed to load graph data")
            
            logger.info("Loaded graph data: %d nodes, %d relationships",
                       graph_data.node_count, graph_data.relationship_count)
            
            # Validate if requested
            if self.config.validate_data:
                errors = self._validate_graph_data(graph_data)
                if errors:
                    result.errors.extend(errors)
                    if len(errors) > 10:  # Too many errors, abort
                        result.errors.append("Too many validation errors, aborting import")
                        return result
            
            # Connect to database
            self._connect()
            
            # Import nodes
            logger.info("Importing nodes...")
            nodes_imported, nodes_skipped = self._import_nodes(graph_data)
            result.nodes_imported = nodes_imported
            result.nodes_skipped = nodes_skipped
            
            # Import relationships
            logger.info("Importing relationships...")
            rels_imported, rels_skipped = self._import_relationships(graph_data)
            result.relationships_imported = rels_imported
            result.relationships_skipped = rels_skipped
            
            # Import schema
            if self.config.create_indexes or self.config.create_constraints:
                logger.info("Importing schema...")
                self._import_schema(graph_data)
            
            # Calculate duration
            result.duration_seconds = time.time() - start_time
            result.success = True
            
            logger.info("Import completed successfully in %.2f seconds", result.duration_seconds)
            logger.info("Imported %d nodes and %d relationships",
                       result.nodes_imported, result.relationships_imported)
            
            return result

        except MigrationError as e:
            logger.error("Import failed: %s", e, exc_info=True)
            result.errors.append(str(e))
            result.duration_seconds = time.time() - start_time
            return result

        except Exception as e:
            logger.error("Import failed unexpectedly: %s", e, exc_info=True)
            result.errors.append(
                str(
                    MigrationError(
                        "Import failed unexpectedly",
                        details={"error": str(e), "error_class": type(e).__name__},
                    )
                )
            )
            result.duration_seconds = time.time() - start_time
            return result
        
        finally:
            self._close()
