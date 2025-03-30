"""
Enhanced Data Provenance Tracking Module with Detailed Lineage.

This module builds upon the base data_provenance.py implementation to provide
advanced provenance tracking features:
- Interactive visualization with export to multiple formats
- Enhanced IPLD integration for distributed provenance
- Advanced graph-based lineage analysis with metrics
- Bidirectional integration with audit logging
- Improved reporting with custom templates and formats
- Data provenance validation and verification
- Semantic search for provenance records
- Time-aware provenance analysis
- Cryptographic verification of provenance records
- IPLD-based content-addressable storage with advanced traversal
- Incremental loading of partial provenance graphs
- Optimized batch operations for IPLD storage
- Integration with IPLD DAG-PB for efficient storage
- IPLD-based cryptographic verification of linked data integrity
- CAR file import/export support with selective loading
"""

import json
import uuid
import time
import hashlib
import datetime
import os
import io
import base64
import tempfile
import logging
import secrets
from typing import Dict, List, Any, Optional, Union, Set, Tuple, Callable, Iterator, TypeVar
from dataclasses import dataclass, field, asdict
from enum import Enum
import networkx as nx
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import numpy as np
import hmac  # For cryptographic verification

# Import from base provenance module
from ipfs_datasets_py.data_provenance import (
    ProvenanceRecordType, ProvenanceRecord, SourceRecord, 
    TransformationRecord, MergeRecord, QueryRecord, ResultRecord,
    ProvenanceManager as BaseProvenanceManager,
    ProvenanceContext as BaseProvenanceContext
)

# Optional imports for enhanced features
try:
    from ipfs_datasets_py.audit.audit_logger import AuditLogger, AuditEvent, AuditLevel, AuditCategory
    AUDIT_AVAILABLE = True
except ImportError:
    AUDIT_AVAILABLE = False

try:
    import plotly.graph_objects as go
    import plotly.io as pio
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

try:
    import dash
    from dash import dcc, html
    import dash_cytoscape as cyto
    DASH_AVAILABLE = True
except ImportError:
    DASH_AVAILABLE = False

# IPLD storage integration
try:
    from ipfs_datasets_py.ipld.storage import IPLDStorage
    from ipfs_datasets_py.ipld.dag_pb import DAGNode, DAGLink
    IPLD_AVAILABLE = True
    DAGPB_AVAILABLE = True
except ImportError:
    IPLD_AVAILABLE = False
    DAGPB_AVAILABLE = False

# Type variable for generic methods
T = TypeVar('T')

# Additional record types for enhanced provenance
class EnhancedProvenanceRecordType(Enum):
    """Additional record types for enhanced provenance tracking."""
    VERIFICATION = "verification"      # Data verification/validation
    ANNOTATION = "annotation"          # Manual annotation/note
    ACCESS = "access"                  # Data access event
    DELETION = "deletion"              # Data deletion event
    AGGREGATION = "aggregation"        # Data aggregation
    ENRICHMENT = "enrichment"          # Data enrichment
    MODEL_TRAINING = "model_training"  # Model training event
    MODEL_INFERENCE = "model_inference" # Model inference event


class ProvenanceCryptoVerifier:
    """
    Cryptographic verification and signing for provenance records.
    
    This class provides mechanisms to cryptographically sign and verify 
    provenance records, ensuring their integrity and authenticity.
    """
    
    def __init__(self, secret_key: Optional[str] = None):
        """
        Initialize the crypto verifier.
        
        Args:
            secret_key: Secret key for signing (generated if not provided)
        """
        self.secret_key = secret_key or secrets.token_hex(32)
        self._hmac_cache = {}  # Cache of computed HMACs
    
    def sign_record(self, record: 'ProvenanceRecord') -> str:
        """
        Create a cryptographic signature for a provenance record.
        
        Args:
            record: The provenance record to sign
            
        Returns:
            str: Hexadecimal signature
        """
        # Create a canonical representation of the record for signing
        # Exclude the signature field itself
        record_dict = asdict(record)
        if 'signature' in record_dict:
            del record_dict['signature']
        
        # Sort keys to ensure consistent ordering
        canonical_json = json.dumps(record_dict, sort_keys=True)
        
        # Create and return the HMAC
        h = hmac.new(
            key=self.secret_key.encode('utf-8'),
            msg=canonical_json.encode('utf-8'),
            digestmod=hashlib.sha256
        )
        return h.hexdigest()
    
    def verify_record(self, record: 'ProvenanceRecord') -> bool:
        """
        Verify the cryptographic signature of a provenance record.
        
        Args:
            record: The provenance record to verify
            
        Returns:
            bool: Whether the signature is valid
        """
        if not hasattr(record, 'signature') or not record.signature:
            return False
        
        # Get the stored signature
        stored_signature = record.signature
        
        # Compute expected signature
        expected_signature = self.sign_record(record)
        
        # Compare signatures using constant-time comparison to prevent timing attacks
        return hmac.compare_digest(stored_signature, expected_signature)
    
    def bulk_sign_records(self, records: List['ProvenanceRecord']) -> Dict[str, str]:
        """
        Sign multiple records efficiently.
        
        Args:
            records: List of provenance records to sign
            
        Returns:
            Dict[str, str]: Map from record ID to signature
        """
        signatures = {}
        for record in records:
            signatures[record.id] = self.sign_record(record)
        return signatures
    
    def verify_graph_integrity(self, records: Dict[str, 'ProvenanceRecord']) -> Dict[str, bool]:
        """
        Verify the integrity of a provenance graph.
        
        This checks both the signatures of individual records and the
        consistency of relationships between records.
        
        Args:
            records: Dictionary of record ID to ProvenanceRecord
            
        Returns:
            Dict[str, bool]: Map from record ID to verification result
        """
        # First verify individual record signatures
        verification_results = {}
        for record_id, record in records.items():
            verification_results[record_id] = self.verify_record(record)
        
        # Then verify relationship consistency
        for record_id, record in records.items():
            # Skip records with invalid signatures
            if not verification_results[record_id]:
                continue
            
            # Check input references
            if hasattr(record, 'input_ids'):
                for input_id in record.input_ids:
                    if input_id not in records:
                        # Referenced input record doesn't exist
                        verification_results[record_id] = False
                        break
            
            # Check output references
            if hasattr(record, 'output_ids'):
                for output_id in record.output_ids:
                    if output_id not in records:
                        # Referenced output record doesn't exist
                        verification_results[record_id] = False
                        break
        
        return verification_results
    
    def rotate_key(self, new_secret_key: Optional[str] = None) -> str:
        """
        Rotate the secret key and return the old one.
        
        This should be followed by re-signing all records with the new key.
        
        Args:
            new_secret_key: New secret key (generated if not provided)
            
        Returns:
            str: The old secret key
        """
        old_key = self.secret_key
        self.secret_key = new_secret_key or secrets.token_hex(32)
        self._hmac_cache = {}  # Clear cache
        return old_key


@dataclass
class VerificationRecord(ProvenanceRecord):
    """Record for data verification/validation."""
    record_type: ProvenanceRecordType = field(default_factory=lambda: ProvenanceRecordType.TRANSFORMATION)
    verification_type: str = ""  # Type of verification (schema, integrity, etc.)
    schema: Optional[Dict[str, Any]] = None  # Schema used for verification
    validation_rules: List[Dict[str, Any]] = field(default_factory=list)  # Rules applied
    pass_count: int = 0  # Number of records/fields that passed
    fail_count: int = 0  # Number of records/fields that failed
    error_samples: List[Dict[str, Any]] = field(default_factory=list)  # Samples of validation errors
    is_valid: bool = True  # Overall validation result


@dataclass
class AnnotationRecord(ProvenanceRecord):
    """Record for manual annotation or note."""
    record_type: ProvenanceRecordType = field(default_factory=lambda: ProvenanceRecordType.TRANSFORMATION)
    annotation_type: str = ""  # Type of annotation
    content: str = ""  # Annotation content
    author: str = ""  # Author of annotation
    tags: List[str] = field(default_factory=list)  # Tags for categorization


@dataclass
class ModelTrainingRecord(ProvenanceRecord):
    """Record for model training event."""
    record_type: ProvenanceRecordType = field(default_factory=lambda: ProvenanceRecordType.TRANSFORMATION)
    model_type: str = ""  # Type of model
    model_framework: str = ""  # Framework used (PyTorch, TensorFlow, etc.)
    hyperparameters: Dict[str, Any] = field(default_factory=dict)  # Training hyperparameters
    metrics: Dict[str, float] = field(default_factory=dict)  # Training metrics
    execution_time: Optional[float] = None  # Training time in seconds
    model_size: Optional[int] = None  # Model size in bytes
    model_hash: Optional[str] = None  # Model hash for verification


@dataclass 
class ModelInferenceRecord(ProvenanceRecord):
    """Record for model inference event."""
    record_type: ProvenanceRecordType = field(default_factory=lambda: ProvenanceRecordType.TRANSFORMATION)
    model_id: str = ""  # ID of the model used
    model_version: str = ""  # Model version
    batch_size: Optional[int] = None  # Size of inference batch
    execution_time: Optional[float] = None  # Inference time in seconds
    output_type: str = ""  # Type of output (predictions, embeddings, etc.)
    performance_metrics: Dict[str, float] = field(default_factory=dict)  # Inference performance metrics


# Define advanced graph metrics for provenance analysis
class ProvenanceMetrics:
    """Calculates metrics for provenance graphs."""
    
    @staticmethod
    def calculate_data_impact(graph: nx.DiGraph, node_id: str) -> float:
        """
        Calculate the impact factor of a data node by counting downstream nodes.
        
        Args:
            graph: The provenance graph
            node_id: ID of the node to analyze
            
        Returns:
            float: Impact factor score
        """
        if not graph.has_node(node_id):
            return 0.0
            
        # Get all descendants (downstream nodes)
        descendants = nx.descendants(graph, node_id)
        
        # Calculate impact based on number of descendants and their distance
        impact = 0.0
        for desc in descendants:
            try:
                # Weight by inverse of path length (closer nodes have higher impact)
                path_length = nx.shortest_path_length(graph, node_id, desc)
                impact += 1.0 / max(1, path_length)
            except nx.NetworkXNoPath:
                continue
                
        return impact
    
    @staticmethod
    def calculate_centrality(graph: nx.DiGraph, node_type: Optional[str] = None) -> Dict[str, float]:
        """
        Calculate centrality measures for nodes in the provenance graph.
        
        Args:
            graph: The provenance graph
            node_type: Optional filter by node type
            
        Returns:
            Dict[str, float]: Node IDs to centrality score
        """
        # Use betweenness centrality as a measure of node importance
        centrality = nx.betweenness_centrality(graph)
        
        # Filter by node type if specified
        if node_type:
            filtered_centrality = {}
            for node, score in centrality.items():
                node_attrs = graph.nodes[node]
                if 'record_type' in node_attrs and node_attrs['record_type'] == node_type:
                    filtered_centrality[node] = score
            return filtered_centrality
        else:
            return centrality
    
    @staticmethod
    def calculate_complexity(graph: nx.DiGraph, data_id: str) -> Dict[str, float]:
        """
        Calculate complexity metrics for a data entity's provenance.
        
        Args:
            graph: The provenance graph
            data_id: ID of the data entity
            
        Returns:
            Dict[str, float]: Dictionary of complexity metrics
        """
        # Get the subgraph for this data entity
        if data_id not in graph:
            return {"error": "Data ID not found in graph"}
            
        # Try to get data provenance as a subgraph
        try:
            # Find ancestors (all upstream nodes)
            ancestors = nx.ancestors(graph, data_id)
            ancestors.add(data_id)
            subgraph = graph.subgraph(ancestors)
            
            # Calculate various complexity metrics
            n_nodes = subgraph.number_of_nodes()
            n_edges = subgraph.number_of_edges()
            
            # Calculate max depth (longest path)
            max_depth = 0
            source_nodes = [n for n, d in subgraph.in_degree() if d == 0]
            
            for source in source_nodes:
                try:
                    path_length = nx.shortest_path_length(subgraph, source, data_id)
                    max_depth = max(max_depth, path_length)
                except nx.NetworkXNoPath:
                    continue
            
            # Calculate branch factor (average out-degree)
            branch_factor = sum(d for _, d in subgraph.out_degree()) / max(1, n_nodes)
            
            # Calculate density (ratio of actual to possible edges)
            density = nx.density(subgraph)
            
            return {
                "node_count": n_nodes,
                "edge_count": n_edges,
                "max_depth": max_depth,
                "branch_factor": branch_factor,
                "density": density,
                "transformation_count": sum(1 for n in subgraph.nodes if 
                                          subgraph.nodes[n].get("record_type") == "transformation"),
                "merge_count": sum(1 for n in subgraph.nodes if 
                                 subgraph.nodes[n].get("record_type") == "merge")
            }
        except Exception as e:
            return {"error": f"Error calculating complexity: {str(e)}"}


# Define IPLD schema for provenance records
class ProvenanceIPLDSchema:
    """Defines IPLD schemas for provenance records and related structures."""
    
    # Schema for base provenance record
    PROVENANCE_RECORD = {
        "type": "object",
        "required": ["id", "record_type", "timestamp", "agent_id"],
        "properties": {
            "id": {"type": "string"},
            "record_type": {"type": "string"},
            "timestamp": {"type": "number"},
            "agent_id": {"type": "string"},
            "description": {"type": "string"},
            "metadata": {"type": "object"},
            "input_ids": {"type": "array", "items": {"type": "string"}},
            "output_ids": {"type": "array", "items": {"type": "string"}},
            "signature": {"type": "string"}
        }
    }
    
    # Schema for source record
    SOURCE_RECORD = {
        "type": "object",
        "required": ["id", "record_type", "timestamp", "agent_id", "source_type", "format"],
        "properties": {
            "id": {"type": "string"},
            "record_type": {"type": "string"},
            "timestamp": {"type": "number"},
            "agent_id": {"type": "string"},
            "description": {"type": "string"},
            "metadata": {"type": "object"},
            "input_ids": {"type": "array", "items": {"type": "string"}},
            "output_ids": {"type": "array", "items": {"type": "string"}},
            "signature": {"type": "string"},
            "source_type": {"type": "string"},
            "format": {"type": "string"},
            "location": {"type": "string"},
            "version": {"type": "string"}
        }
    }
    
    # Schema for transformation record
    TRANSFORMATION_RECORD = {
        "type": "object",
        "required": ["id", "record_type", "timestamp", "agent_id", "transformation_type"],
        "properties": {
            "id": {"type": "string"},
            "record_type": {"type": "string"},
            "timestamp": {"type": "number"},
            "agent_id": {"type": "string"},
            "description": {"type": "string"},
            "metadata": {"type": "object"},
            "input_ids": {"type": "array", "items": {"type": "string"}},
            "output_ids": {"type": "array", "items": {"type": "string"}},
            "signature": {"type": "string"},
            "transformation_type": {"type": "string"},
            "tool": {"type": "string"},
            "parameters": {"type": "object"},
            "version": {"type": "string"}
        }
    }
    
    # Schema for verification record
    VERIFICATION_RECORD = {
        "type": "object",
        "required": ["id", "record_type", "timestamp", "agent_id", "verification_type", "is_valid"],
        "properties": {
            "id": {"type": "string"},
            "record_type": {"type": "string"},
            "timestamp": {"type": "number"},
            "agent_id": {"type": "string"},
            "description": {"type": "string"},
            "metadata": {"type": "object"},
            "input_ids": {"type": "array", "items": {"type": "string"}},
            "output_ids": {"type": "array", "items": {"type": "string"}},
            "signature": {"type": "string"},
            "verification_type": {"type": "string"},
            "schema": {"type": "object"},
            "validation_rules": {"type": "array"},
            "pass_count": {"type": "number"},
            "fail_count": {"type": "number"},
            "error_samples": {"type": "array"},
            "is_valid": {"type": "boolean"}
        }
    }
    
    # Schema for provenance graph
    PROVENANCE_GRAPH = {
        "type": "object",
        "required": ["records", "links", "root_records"],
        "properties": {
            "records": {"type": "object"},  # Map of record_id -> record
            "links": {"type": "array", "items": {
                "type": "object",
                "required": ["source", "target", "type"],
                "properties": {
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                    "type": {"type": "string"}
                }
            }},
            "root_records": {"type": "array", "items": {"type": "string"}},
            "metadata": {"type": "object"},
            "created_at": {"type": "number"},
            "updated_at": {"type": "number"},
            "version": {"type": "string"}
        }
    }
    
    # Enhanced schemas for distributed provenance
    PROVENANCE_PARTITION = {
        "type": "object",
        "required": ["partition_id", "nodes", "boundary_nodes"],
        "properties": {
            "partition_id": {"type": "string"},
            "nodes": {"type": "object"},  # Map of node_id -> record_cid
            "boundary_nodes": {"type": "array", "items": {"type": "string"}},
            "metadata": {"type": "object"},
            "parent_partition": {"type": "string"},
            "child_partitions": {"type": "array", "items": {"type": "string"}},
            "timestamp_range": {
                "type": "object",
                "properties": {
                    "start": {"type": "number"},
                    "end": {"type": "number"}
                }
            }
        }
    }
    
    PROVENANCE_INDEX = {
        "type": "object",
        "required": ["by_data_id", "by_timestamp", "by_agent", "by_type"],
        "properties": {
            "by_data_id": {"type": "object"},  # Map of data_id -> array of record_ids
            "by_timestamp": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "timestamp": {"type": "number"},
                    "record_id": {"type": "string"}
                }
            }},
            "by_agent": {"type": "object"},  # Map of agent_id -> array of record_ids
            "by_type": {"type": "object"},  # Map of record_type -> array of record_ids
            "by_tag": {"type": "object"}  # Map of tag -> array of record_ids
        }
    }


class IPLDProvenanceStorage:
    """
    Enhanced IPLD-based storage for provenance data with advanced traversal capabilities.
    
    This class provides specialized storage, retrieval, and traversal functionality
    for provenance data using IPLD as the underlying storage layer. It supports
    incremental loading, efficient batch operations, and integration with DAG-PB.
    
    Features:
    - Content-addressable storage and retrieval of provenance records
    - Advanced graph traversal using IPLD links
    - Incremental loading of partial provenance graphs
    - Batch operations for efficient processing
    - Integration with DAG-PB for efficient storage
    - IPLD-based cryptographic verification of linked data integrity
    - Graph partitioning for working with large provenance graphs
    - Time-based and entity-based slicing of provenance
    """
    
    def __init__(
        self, 
        ipld_storage: Optional[IPLDStorage] = None,
        base_dir: Optional[str] = None,
        ipfs_api: str = "/ip4/127.0.0.1/tcp/5001",
        enable_dagpb: bool = True,
        batch_size: int = 100,
        enable_partitioning: bool = True,
        partition_size_limit: int = 1000,
        crypto_verifier: Optional['ProvenanceCryptoVerifier'] = None
    ):
        """
        Initialize the IPLD provenance storage.
        
        Args:
            ipld_storage: Optional IPLDStorage instance to use
            base_dir: Base directory for local storage
            ipfs_api: IPFS API endpoint
            enable_dagpb: Use DAG-PB for storage when available
            batch_size: Default batch size for operations
            enable_partitioning: Enable graph partitioning for large graphs
            partition_size_limit: Maximum records per partition
            crypto_verifier: Cryptographic verifier for record integrity
        """
        if ipld_storage:
            self.ipld_storage = ipld_storage
        elif IPLD_AVAILABLE:
            self.ipld_storage = IPLDStorage(base_dir=base_dir, ipfs_api=ipfs_api)
        else:
            raise ImportError("IPLD storage is required but not available")
            
        self.enable_dagpb = enable_dagpb and DAGPB_AVAILABLE
        self.batch_size = batch_size
        self.enable_partitioning = enable_partitioning
        self.partition_size_limit = partition_size_limit
        self.crypto_verifier = crypto_verifier
        
        # Storage for various CIDs and indexes
        self.record_cids = {}  # Record ID to CID mapping
        self.partition_cids = {}  # Partition ID to CID mapping
        self.root_graph_cid = None  # Root graph CID
        self.index_cid = None  # Provenance index CID
        
        # Register schemas
        self._register_schemas()
    
    def _register_schemas(self):
        """Register all provenance schemas with IPLD storage."""
        schemas = {
            "provenance_record": ProvenanceIPLDSchema.PROVENANCE_RECORD,
            "source_record": ProvenanceIPLDSchema.SOURCE_RECORD,
            "transformation_record": ProvenanceIPLDSchema.TRANSFORMATION_RECORD,
            "verification_record": ProvenanceIPLDSchema.VERIFICATION_RECORD,
            "provenance_graph": ProvenanceIPLDSchema.PROVENANCE_GRAPH,
            "provenance_partition": ProvenanceIPLDSchema.PROVENANCE_PARTITION,
            "provenance_index": ProvenanceIPLDSchema.PROVENANCE_INDEX
        }
        
        for name, schema in schemas.items():
            self.ipld_storage.register_schema(name, schema)
    
    def store_record(self, record: 'ProvenanceRecord', sign: bool = True) -> str:
        """
        Store a provenance record with content addressing.
        
        Args:
            record: The provenance record to store
            sign: Whether to sign the record (if crypto_verifier is available)
            
        Returns:
            str: CID of the stored record
        """
        # Sign the record if requested and possible
        if sign and self.crypto_verifier:
            if not hasattr(record, 'signature') or not record.signature:
                record.signature = self.crypto_verifier.sign_record(record)
        
        # Convert record to dictionary
        record_dict = self._record_to_dict(record)
        
        # Determine the schema based on record type
        schema_name = self._get_schema_name_for_record(record)
        
        # Store with DAG-PB if enabled
        if self.enable_dagpb:
            # Create DAG-PB node for the record
            dagnode = self._create_dagnode_for_record(record, record_dict)
            # Store the node
            cid = self.ipld_storage.store_dagpb(dagnode)
        else:
            # Store with regular IPLD schema
            cid = self.ipld_storage.store_with_schema(record_dict, schema_name)
        
        # Update record_cids mapping
        self.record_cids[record.id] = cid
        
        return cid
    
    def _create_dagnode_for_record(self, record: 'ProvenanceRecord', record_dict: dict) -> DAGNode:
        """
        Create a DAG-PB node for a provenance record.
        
        Args:
            record: The provenance record
            record_dict: Dictionary representation of the record
            
        Returns:
            DAGNode: DAG-PB node for the record
        """
        # Convert to JSON for the data portion
        data = json.dumps(record_dict).encode('utf-8')
        
        # Create links for related records
        links = []
        
        # Add links based on record type
        if hasattr(record, 'input_ids') and record.input_ids:
            for input_id in record.input_ids:
                if input_id in self.record_cids:
                    links.append(DAGLink(
                        name=f"input/{input_id}",
                        cid=self.record_cids[input_id],
                        size=0  # Size will be calculated during encoding
                    ))
        
        if hasattr(record, 'output_id') and record.output_id:
            if record.output_id in self.record_cids:
                links.append(DAGLink(
                    name=f"output/{record.output_id}",
                    cid=self.record_cids[record.output_id],
                    size=0
                ))
        
        if hasattr(record, 'data_id') and record.data_id:
            # Link to related data
            if record.data_id in self.record_cids:
                links.append(DAGLink(
                    name=f"data/{record.data_id}",
                    cid=self.record_cids[record.data_id],
                    size=0
                ))
        
        # Create and return the DAG node
        return DAGNode(data=data, links=links)
    
    def _get_schema_name_for_record(self, record: 'ProvenanceRecord') -> str:
        """
        Get the schema name for a given record type.
        
        Args:
            record: Provenance record
            
        Returns:
            str: Schema name
        """
        record_type_map = {
            "source": "source_record",
            "transformation": "transformation_record",
            "verification": "verification_record"
        }
        
        # Get record_type attribute as string
        if hasattr(record, 'record_type'):
            if isinstance(record.record_type, Enum):
                record_type_str = record.record_type.value
            else:
                record_type_str = str(record.record_type)
                
            # Map to schema name or use generic
            return record_type_map.get(record_type_str, "provenance_record")
        
        # Fallback to provenance_record
        return "provenance_record"
    
    def _record_to_dict(self, record: 'ProvenanceRecord') -> dict:
        """
        Convert a provenance record to a dictionary.
        
        Args:
            record: Provenance record
            
        Returns:
            dict: Dictionary representation of the record
        """
        if hasattr(record, 'to_dict'):
            return record.to_dict()
        elif hasattr(record, '__dict__'):
            result = {}
            for key, value in record.__dict__.items():
                if isinstance(value, Enum):
                    result[key] = value.value
                elif hasattr(value, 'to_dict'):
                    result[key] = value.to_dict()
                else:
                    result[key] = value
            return result
        else:
            return asdict(record)
    
    def store_records_batch(self, records: List['ProvenanceRecord'], sign: bool = True) -> Dict[str, str]:
        """
        Store multiple records in a batch operation.
        
        Args:
            records: List of provenance records to store
            sign: Whether to sign the records
            
        Returns:
            Dict[str, str]: Mapping from record ID to CID
        """
        # Sign records if requested
        if sign and self.crypto_verifier:
            signatures = self.crypto_verifier.bulk_sign_records(records)
            for record in records:
                if record.id in signatures and not hasattr(record, 'signature'):
                    record.signature = signatures[record.id]
        
        # Process records by schema type
        records_by_schema = {}
        for record in records:
            schema_name = self._get_schema_name_for_record(record)
            if schema_name not in records_by_schema:
                records_by_schema[schema_name] = []
            records_by_schema[schema_name].append((record, self._record_to_dict(record)))
        
        # Store records by schema
        results = {}
        for schema_name, record_pairs in records_by_schema.items():
            if self.enable_dagpb:
                # Store each record as DAG-PB
                for record, record_dict in record_pairs:
                    dagnode = self._create_dagnode_for_record(record, record_dict)
                    cid = self.ipld_storage.store_dagpb(dagnode)
                    self.record_cids[record.id] = cid
                    results[record.id] = cid
            else:
                # Bulk store with regular IPLD schema
                dicts_with_ids = [(record.id, record_dict) for record, record_dict in record_pairs]
                batch_results = self.ipld_storage.store_many_with_schema(dicts_with_ids, schema_name)
                
                # Update record CIDs mapping
                for record_id, cid in batch_results.items():
                    self.record_cids[record_id] = cid
                    results[record_id] = cid
        
        return results
    
    def load_record(self, cid: str, record_class=None) -> 'ProvenanceRecord':
        """
        Load a provenance record from IPLD storage.
        
        Args:
            cid: CID of the record to load
            record_class: Optional class to use for instantiation
            
        Returns:
            ProvenanceRecord: The loaded record
        """
        # Check if the record is stored as DAG-PB
        try:
            if self.enable_dagpb:
                dagnode = self.ipld_storage.load_dagpb(cid)
                if dagnode and dagnode.data:
                    # Extract the record data from the DAG-PB node
                    record_dict = json.loads(dagnode.data.decode('utf-8'))
                    return self._dict_to_record(record_dict, record_class)
        except Exception:
            # Fall back to regular IPLD loading if DAG-PB fails
            pass
            
        # Load using regular IPLD storage
        record_dict = self.ipld_storage.load(cid)
        return self._dict_to_record(record_dict, record_class)
    
    def _dict_to_record(self, record_dict: dict, record_class=None) -> 'ProvenanceRecord':
        """
        Convert a dictionary to a provenance record.
        
        Args:
            record_dict: Dictionary representation of record
            record_class: Optional class to use for instantiation
            
        Returns:
            ProvenanceRecord: The constructed record
        """
        if record_class:
            # Use provided class
            return record_class(**record_dict)
        
        # Determine class based on record_type
        record_type = record_dict.get('record_type')
        if record_type == 'source':
            from ipfs_datasets_py.data_provenance import SourceRecord
            return SourceRecord(**record_dict)
        elif record_type == 'transformation':
            from ipfs_datasets_py.data_provenance import TransformationRecord
            return TransformationRecord(**record_dict)
        elif record_type == 'verification':
            return VerificationRecord(**record_dict)
        else:
            # Generic provenance record
            from ipfs_datasets_py.data_provenance import ProvenanceRecord
            return ProvenanceRecord(**record_dict)
    
    def load_records_batch(self, cids: List[str]) -> Dict[str, 'ProvenanceRecord']:
        """
        Load multiple records in a batch operation.
        
        Args:
            cids: List of CIDs to load
            
        Returns:
            Dict[str, ProvenanceRecord]: Mapping from CID to record
        """
        results = {}
        
        # If DAG-PB is enabled, try to load each record individually
        # as we need special handling for DAG-PB nodes
        if self.enable_dagpb:
            for cid in cids:
                try:
                    record = self.load_record(cid)
                    results[cid] = record
                except Exception as e:
                    print(f"Error loading record {cid}: {e}")
            return results
        
        # Bulk load using IPLD storage
        raw_records = self.ipld_storage.load_many(cids)
        
        # Convert dictionaries to records
        for cid, record_dict in raw_records.items():
            try:
                record = self._dict_to_record(record_dict)
                results[cid] = record
            except Exception as e:
                print(f"Error converting record {cid}: {e}")
        
        return results
    
    def store_graph(self, graph: nx.DiGraph, partition: bool = None) -> str:
        """
        Store a provenance graph in IPLD.
        
        Args:
            graph: NetworkX directed graph of provenance records
            partition: Whether to partition the graph (None=use default setting)
            
        Returns:
            str: CID of the root graph
        """
        # Use the instance setting if partition not specified
        if partition is None:
            partition = self.enable_partitioning
        
        # Convert graph to IPLD-friendly structure
        if partition and len(graph.nodes) > self.partition_size_limit:
            return self._store_partitioned_graph(graph)
        else:
            return self._store_single_graph(graph)
    
    def _store_single_graph(self, graph: nx.DiGraph) -> str:
        """
        Store a provenance graph as a single IPLD structure.
        
        Args:
            graph: NetworkX directed graph
            
        Returns:
            str: CID of the graph
        """
        # Ensure all nodes are stored in IPLD
        for node_id in graph.nodes:
            if node_id not in self.record_cids:
                # Get the record from graph node attributes
                record = graph.nodes[node_id].get('record')
                if record:
                    # Store the record
                    self.store_record(record)
        
        # Create graph representation
        graph_dict = {
            "records": {node_id: self.record_cids[node_id] for node_id in graph.nodes if node_id in self.record_cids},
            "links": [{"source": src, "target": dst, "type": data.get("relation", "related_to")} 
                     for src, dst, data in graph.edges(data=True)],
            "root_records": [node_id for node_id in graph.nodes if graph.in_degree(node_id) == 0],
            "metadata": {
                "timestamp": time.time(),
                "node_count": len(graph.nodes),
                "edge_count": len(graph.edges)
            },
            "created_at": time.time(),
            "updated_at": time.time(),
            "version": "1.0"
        }
        
        # Store the graph with schema validation
        cid = self.ipld_storage.store_with_schema(graph_dict, "provenance_graph")
        self.root_graph_cid = cid
        
        return cid
    
    def _store_partitioned_graph(self, graph: nx.DiGraph) -> str:
        """
        Store a provenance graph as multiple partitions in IPLD.
        
        Args:
            graph: NetworkX directed graph
            
        Returns:
            str: CID of the root partition index
        """
        # Partition the graph
        partitions = self._partition_graph(graph)
        
        # Process each partition
        partition_cids = {}
        for partition_id, subgraph in partitions.items():
            # Ensure all nodes in this partition are stored
            for node_id in subgraph.nodes:
                if node_id not in self.record_cids:
                    record = subgraph.nodes[node_id].get('record')
                    if record:
                        self.store_record(record)
            
            # Store the partition
            partition_dict = {
                "partition_id": partition_id,
                "nodes": {node_id: self.record_cids[node_id] for node_id in subgraph.nodes if node_id in self.record_cids},
                "boundary_nodes": [n for n in subgraph.nodes if any(neighbor not in subgraph for neighbor in graph.neighbors(n))],
                "metadata": {
                    "timestamp": time.time(),
                    "node_count": len(subgraph.nodes),
                    "edge_count": len(subgraph.edges)
                },
                "parent_partition": None,  # Will be set later
                "child_partitions": [],  # Will be set later
                "timestamp_range": {
                    "start": min(subgraph.nodes[n].get("record").timestamp for n in subgraph.nodes if "record" in subgraph.nodes[n]),
                    "end": max(subgraph.nodes[n].get("record").timestamp for n in subgraph.nodes if "record" in subgraph.nodes[n])
                }
            }
            
            # Store the partition
            partition_cid = self.ipld_storage.store_with_schema(partition_dict, "provenance_partition")
            partition_cids[partition_id] = partition_cid
            self.partition_cids[partition_id] = partition_cid
        
        # Create index of partitions
        partition_index = {
            "partitions": partition_cids,
            "metadata": {
                "timestamp": time.time(),
                "partition_count": len(partition_cids),
                "total_nodes": len(graph.nodes),
                "total_edges": len(graph.edges)
            }
        }
        
        # Store the partition index
        index_cid = self.ipld_storage.store(partition_index)
        self.root_graph_cid = index_cid
        
        return index_cid
    
    def _partition_graph(self, graph: nx.DiGraph) -> Dict[str, nx.DiGraph]:
        """
        Partition a large provenance graph into manageable subgraphs.
        
        Args:
            graph: NetworkX directed graph
            
        Returns:
            Dict[str, nx.DiGraph]: Mapping from partition ID to subgraph
        """
        partitions = {}
        
        # Temporal partitioning - group records by time windows
        node_times = {
            node_id: graph.nodes[node_id].get("record").timestamp 
            for node_id in graph.nodes 
            if "record" in graph.nodes[node_id]
        }
        
        if not node_times:
            # Fall back to simple partitioning if no timestamps
            return self._simple_partition_graph(graph)
        
        # Sort nodes by timestamp
        sorted_nodes = sorted(node_times.items(), key=lambda x: x[1])
        
        # Create partitions of approximately equal size
        partition_size = min(self.partition_size_limit, max(100, len(graph.nodes) // 10))
        
        for i in range(0, len(sorted_nodes), partition_size):
            partition_nodes = [node_id for node_id, _ in sorted_nodes[i:i+partition_size]]
            partition_id = f"partition_{i//partition_size}"
            
            # Create subgraph
            subgraph = graph.subgraph(partition_nodes).copy()
            partitions[partition_id] = subgraph
        
        return partitions
    
    def incremental_load(self, root_cid: str, criteria: Optional[Dict] = None) -> nx.DiGraph:
        """
        Incrementally load parts of a provenance graph based on criteria.
        
        Args:
            root_cid: CID of the root graph
            criteria: Filtering criteria (time range, data_ids, record types)
            
        Returns:
            nx.DiGraph: Partial provenance graph
        """
        # Default criteria loads everything
        if criteria is None:
            criteria = {}
        
        try:
            # Try as partitioned graph first
            return self._incremental_load_partitioned(root_cid, criteria)
        except Exception:
            # Fall back to filtered single graph
            return self._incremental_load_single(root_cid, criteria)
    
    def traverse_graph_from_node(self, start_node_id: str, max_depth: int = 3, 
                                direction: str = "both", relation_filter: Optional[List[str]] = None) -> nx.DiGraph:
        """
        Traverse the provenance graph from a starting node.
        
        Args:
            start_node_id: ID of the starting node
            max_depth: Maximum traversal depth
            direction: Direction of traversal ("in", "out", or "both")
            relation_filter: Optional list of relation types to follow
            
        Returns:
            nx.DiGraph: Subgraph reachable from the start node
        """
        # Create a subgraph for the traversal result
        subgraph = nx.DiGraph()
        
        # Check if node exists in our CID mapping
        if start_node_id not in self.record_cids:
            raise ValueError(f"Start node {start_node_id} not found")
        
        # Add start node to subgraph
        node_cid = self.record_cids[start_node_id]
        record = self.load_record(node_cid)
        subgraph.add_node(start_node_id, record=record, cid=node_cid)
        
        # Queue for BFS traversal: (node_id, depth)
        queue = [(start_node_id, 0)]
        visited = {start_node_id}
        
        # Traverse graph
        while queue:
            node_id, depth = queue.pop(0)
            
            if depth >= max_depth:
                continue
            
            # Get linked nodes from DAG-PB links
            if self.enable_dagpb and node_id in self.record_cids:
                try:
                    dagnode = self.ipld_storage.load_dagpb(self.record_cids[node_id])
                    
                    if dagnode and dagnode.links:
                        for link in dagnode.links:
                            # Process links based on name pattern (input/ID, output/ID, etc.)
                            link_parts = link.name.split('/')
                            if len(link_parts) >= 2:
                                link_type, linked_id = link_parts[0], link_parts[1]
                                
                                # Skip if relation filter is provided and link type doesn't match
                                if relation_filter and link_type not in relation_filter:
                                    continue
                                
                                # Handle direction filter
                                if direction == "out" and link_type != "output":
                                    continue
                                if direction == "in" and link_type != "input":
                                    continue
                                
                                # Process if not visited
                                if linked_id not in visited:
                                    visited.add(linked_id)
                                    queue.append((linked_id, depth + 1))
                                    
                                    # Load the linked record
                                    linked_cid = link.cid
                                    self.record_cids[linked_id] = linked_cid
                                    linked_record = self.load_record(linked_cid)
                                    
                                    # Add to subgraph
                                    subgraph.add_node(linked_id, record=linked_record, cid=linked_cid)
                                    
                                    # Add edge with appropriate direction
                                    if link_type == "input":
                                        subgraph.add_edge(linked_id, node_id, relation="input_to")
                                    else:  # output or other types
                                        subgraph.add_edge(node_id, linked_id, relation=link_type)
                except Exception as e:
                    print(f"Error traversing DAG-PB links for {node_id}: {e}")
            
            # Get linked nodes from graph structure
            if self.root_graph_cid:
                try:
                    graph_data = self.ipld_storage.load(self.root_graph_cid)
                    
                    if "links" in graph_data:
                        for link in graph_data["links"]:
                            source = link["source"]
                            target = link["target"]
                            relation = link.get("type", "related_to")
                            
                            # Skip if relation filter is provided and link type doesn't match
                            if relation_filter and relation not in relation_filter:
                                continue
                            
                            # Process outgoing links
                            if direction in ["out", "both"] and source == node_id and target not in visited:
                                visited.add(target)
                                queue.append((target, depth + 1))
                                
                                # Load target record
                                if target in self.record_cids:
                                    target_cid = self.record_cids[target]
                                    target_record = self.load_record(target_cid)
                                    subgraph.add_node(target, record=target_record, cid=target_cid)
                                    subgraph.add_edge(node_id, target, relation=relation)
                            
                            # Process incoming links
                            if direction in ["in", "both"] and target == node_id and source not in visited:
                                visited.add(source)
                                queue.append((source, depth + 1))
                                
                                # Load source record
                                if source in self.record_cids:
                                    source_cid = self.record_cids[source]
                                    source_record = self.load_record(source_cid)
                                    subgraph.add_node(source, record=source_record, cid=source_cid)
                                    subgraph.add_edge(source, node_id, relation=relation)
                except Exception as e:
                    print(f"Error traversing graph links for {node_id}: {e}")
        
        return subgraph
    
    def verify_integrity(self, crypto_verifier: Optional['ProvenanceCryptoVerifier'] = None) -> Dict[str, bool]:
        """
        Verify the cryptographic integrity of all provenance records.
        
        Args:
            crypto_verifier: Verifier to use (uses instance verifier if None)
            
        Returns:
            Dict[str, bool]: Mapping from record ID to verification result
        """
        verifier = crypto_verifier or self.crypto_verifier
        if not verifier:
            raise ValueError("No crypto verifier provided or available")
        
        # Load all records
        records = {}
        for record_id, cid in self.record_cids.items():
            try:
                record = self.load_record(cid)
                records[record_id] = record
            except Exception as e:
                print(f"Error loading record {record_id}: {e}")
        
        # Verify all records
        return verifier.verify_graph_integrity(records)
    
    def export_to_car(self, output_path: str, include_records: bool = True,
                     include_graph: bool = True, records: Optional[List[str]] = None) -> str:
        """
        Export provenance data to a CAR file.
        
        Args:
            output_path: Path to output CAR file
            include_records: Whether to include individual records
            include_graph: Whether to include the graph structure
            records: Optional list of specific record IDs to include
            
        Returns:
            str: Root CID of exported data
        """
        # Collect CIDs to export
        cids_to_export = set()
        
        # Add records
        if include_records:
            if records:
                # Only specific records
                for record_id in records:
                    if record_id in self.record_cids:
                        cids_to_export.add(self.record_cids[record_id])
            else:
                # All records
                cids_to_export.update(self.record_cids.values())
        
        # Add graph and partitions
        if include_graph:
            if self.root_graph_cid:
                cids_to_export.add(self.root_graph_cid)
            cids_to_export.update(self.partition_cids.values())
        
        # Create export metadata
        export_meta = {
            "type": "provenance_export",
            "timestamp": time.time(),
            "records": list(self.record_cids.values()) if not records else 
                       [self.record_cids[r] for r in records if r in self.record_cids],
            "graph": self.root_graph_cid,
            "partitions": list(self.partition_cids.values()),
            "record_count": len(self.record_cids),
            "metadata": {
                "exported_at": datetime.datetime.now().isoformat(),
                "export_version": "1.0"
            }
        }
        
        # Store export metadata
        meta_cid = self.ipld_storage.store(export_meta)
        cids_to_export.add(meta_cid)
        
        # Export to CAR file
        self.ipld_storage.export_to_car(list(cids_to_export), output_path)
        
        return meta_cid


class EnhancedProvenanceManager(BaseProvenanceManager):
    """
    Enhanced provenance manager with advanced features for detailed lineage tracking.
    
    This class extends the base ProvenanceManager with additional capabilities:
    - Interactive visualization with multiple formats and layouts
    - Advanced reporting with custom templates
    - Integration with audit logging system
    - Enhanced IPLD storage with cryptographic verification
    - Time-based analysis and temporal queries
    - Semantic search for provenance records
    - Cryptographic verification of provenance records
    - IPLD-based content-addressable storage with advanced traversal
    - Incremental loading of partial provenance graphs
    - Graph partitioning for efficient storage and retrieval
    - DAG-PB integration for optimized linked data
    - CAR file import/export support with selective loading
    """
    
    def __init__(
        self,
        storage_path: Optional[str] = None,
        enable_ipld_storage: bool = False,
        default_agent_id: Optional[str] = None,
        tracking_level: str = "detailed",  # "minimal", "standard", "detailed", "comprehensive"
        audit_logger: Optional[Any] = None,  # AuditLogger instance if available
        visualization_engine: str = "matplotlib",  # "matplotlib", "plotly", "dash"
        enable_crypto_verification: bool = False,  # Whether to enable cryptographic verification
        crypto_secret_key: Optional[str] = None,  # Secret key for crypto verification
        ipfs_api: str = "/ip4/127.0.0.1/tcp/5001"  # IPFS API endpoint for IPLD storage
    ):
        """
        Initialize the enhanced provenance manager.
        
        Args:
            storage_path: Path to store provenance data, None for in-memory only
            enable_ipld_storage: Whether to use IPLD for provenance storage
            default_agent_id: Default agent ID for provenance records
            tracking_level: Level of detail for provenance tracking
            audit_logger: AuditLogger instance for audit integration
            visualization_engine: Engine to use for visualizations
            enable_crypto_verification: Whether to enable cryptographic verification
            crypto_secret_key: Secret key for crypto verification (generated if not provided)
            ipfs_api: IPFS API endpoint for IPLD storage
        """
        # Initialize base class
        super().__init__(
            storage_path=storage_path,
            enable_ipld_storage=enable_ipld_storage,
            default_agent_id=default_agent_id,
            tracking_level=tracking_level
        )
        
        # Additional attributes for enhanced features
        self.audit_logger = audit_logger
        self.visualization_engine = visualization_engine
        
        # Set up cryptographic verification
        self.enable_crypto_verification = enable_crypto_verification
        if enable_crypto_verification:
            self.crypto_verifier = ProvenanceCryptoVerifier(crypto_secret_key)
        else:
            self.crypto_verifier = None
        
        # Set up IPLD storage if enabled
        self.enable_ipld_storage = enable_ipld_storage
        self.ipld_storage = None
        self.ipld_provenance_storage = None
        self.ipld_root_cid = None
        self.record_cids = {}  # Record ID to CID mapping
        
        if enable_ipld_storage:
            if IPLD_AVAILABLE:
                # Initialize regular IPLD storage
                self.ipld_storage = IPLDStorage(
                    base_dir=storage_path,
                    ipfs_api=ipfs_api
                )
                
                # Initialize enhanced IPLD provenance storage
                self.ipld_provenance_storage = IPLDProvenanceStorage(
                    ipld_storage=self.ipld_storage,
                    enable_dagpb=DAGPB_AVAILABLE,
                    crypto_verifier=self.crypto_verifier if enable_crypto_verification else None
                )
                
                # Register schemas for provenance records
                self._register_ipld_schemas()
            else:
                self.logger.warning("IPLD storage requested but ipfs_datasets_py.ipld.storage not available")
                self.enable_ipld_storage = False
        
        # Set up logging
        self.logger = logging.getLogger(__name__)
        
        # Extended record types mapping
        self.extended_record_types = {
            **{t.value: t for t in ProvenanceRecordType},
            **{t.value: t for t in EnhancedProvenanceRecordType}
        }
        
        # Additional index for semantic search
        self.semantic_index = {}  # Map from keywords to record IDs
        
        # Record versioning
        self.record_versions = {}  # Map from record ID to list of versions
        
        # Time index for temporal queries
        self.time_index = {}  # Map from time buckets to record IDs
        
        # Integrity verification results cache
        self.verification_results = {}  # Map from record ID to verification result
        
        # IPLD CID mapping (record_id -> CID)
        self.record_cids = {}  # Map from record ID to IPLD CID
        
    def record_verification(
        self,
        data_id: str,
        verification_type: str,
        schema: Optional[Dict[str, Any]] = None,
        validation_rules: Optional[List[Dict[str, Any]]] = None,
        pass_count: int = 0,
        fail_count: int = 0,
        error_samples: Optional[List[Dict[str, Any]]] = None,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Record a data verification/validation event.
        
        Args:
            data_id: ID of the data entity being verified
            verification_type: Type of verification (schema, integrity, etc.)
            schema: Schema used for verification
            validation_rules: Rules applied in validation
            pass_count: Number of records/fields that passed
            fail_count: Number of records/fields that failed
            error_samples: Samples of validation errors
            description: Description of the verification
            metadata: Additional metadata
            
        Returns:
            str: ID of the created verification record
        """
        metadata = metadata or {}
        validation_rules = validation_rules or []
        error_samples = error_samples or []
        
        # Create verification record
        record = VerificationRecord(
            record_type=ProvenanceRecordType.TRANSFORMATION,
            agent_id=self.default_agent_id,
            description=description,
            metadata=metadata,
            input_ids=[data_id],
            output_ids=[data_id],  # Verification doesn't change the data
            verification_type=verification_type,
            schema=schema,
            validation_rules=validation_rules,
            pass_count=pass_count,
            fail_count=fail_count,
            error_samples=error_samples,
            is_valid=(fail_count == 0)
        )
        
        # Store the record
        self.records[record.id] = record
        
        # Add to provenance graph
        self.graph.add_node(record.id, 
                           record_type="verification",
                           description=description,
                           timestamp=record.timestamp,
                           is_valid=record.is_valid)
        
        # Link to data entity
        if data_id in self.entity_latest_record:
            input_record_id = self.entity_latest_record[data_id]
            self.graph.add_edge(input_record_id, record.id, type="verifies")
        
        # Update the entity's latest record
        self.entity_latest_record[data_id] = record.id
        
        # Add cryptographic signature if enabled
        if self.enable_crypto_verification:
            self.sign_record(record)
        
        # Store in IPLD if enabled
        if self.enable_ipld_storage and self.ipld_storage:
            self._store_record_in_ipld(record)
            
        # Log to audit system if available
        self._audit_log_record(record, "verification")
        
        # Index for semantic search
        self._index_for_semantic_search(record)
        
        # Index for temporal queries
        self._index_for_temporal_queries(record)
        
        return record.id
    
    def record_annotation(
        self,
        data_id: str,
        content: str,
        annotation_type: str = "note",
        author: str = "",
        tags: Optional[List[str]] = None,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Record a manual annotation or note about a data entity.
        
        Args:
            data_id: ID of the data entity being annotated
            content: Annotation content
            annotation_type: Type of annotation
            author: Author of annotation
            tags: Tags for categorization
            description: Description of the annotation
            metadata: Additional metadata
            
        Returns:
            str: ID of the created annotation record
        """
        metadata = metadata or {}
        tags = tags or []
        
        # Create annotation record
        record = AnnotationRecord(
            record_type=ProvenanceRecordType.TRANSFORMATION,
            agent_id=self.default_agent_id,
            description=description,
            metadata=metadata,
            input_ids=[data_id],
            output_ids=[data_id],  # Annotation doesn't change the data
            annotation_type=annotation_type,
            content=content,
            author=author or self.default_agent_id,
            tags=tags
        )
        
        # Store the record
        self.records[record.id] = record
        
        # Add to provenance graph
        self.graph.add_node(record.id, 
                           record_type="annotation",
                           description=description,
                           timestamp=record.timestamp,
                           author=record.author,
                           tags=",".join(tags))
        
        # Link to data entity
        if data_id in self.entity_latest_record:
            input_record_id = self.entity_latest_record[data_id]
            self.graph.add_edge(input_record_id, record.id, type="annotates")
        
        # Update the entity's latest record
        self.entity_latest_record[data_id] = record.id
        
        # Add cryptographic signature if enabled
        if self.enable_crypto_verification:
            self.sign_record(record)
        
        # Store in IPLD if enabled
        if self.enable_ipld_storage and self.ipld_storage:
            self._store_record_in_ipld(record)
            
        # Log to audit system if available
        self._audit_log_record(record, "annotation")
        
        # Index for semantic search
        self._index_for_semantic_search(record)
        
        # Index for temporal queries
        self._index_for_temporal_queries(record)
        
        return record.id
    
    def record_model_training(
        self,
        input_ids: List[str],
        output_id: str,
        model_type: str,
        model_framework: str = "",
        hyperparameters: Optional[Dict[str, Any]] = None,
        metrics: Optional[Dict[str, float]] = None,
        model_size: Optional[int] = None,
        model_hash: Optional[str] = None,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Record a model training event.
        
        Args:
            input_ids: IDs of input data entities (training data)
            output_id: ID of output data entity (trained model)
            model_type: Type of model
            model_framework: Framework used (PyTorch, TensorFlow, etc.)
            hyperparameters: Training hyperparameters
            metrics: Training metrics
            model_size: Model size in bytes
            model_hash: Model hash for verification
            description: Description of the training
            metadata: Additional metadata
            
        Returns:
            str: ID of the created model training record
        """
        metadata = metadata or {}
        hyperparameters = hyperparameters or {}
        metrics = metrics or {}
        
        # Start timing if not already provided
        start_time = time.time()
        
        # Create model training record
        record = ModelTrainingRecord(
            record_type=ProvenanceRecordType.TRANSFORMATION,
            agent_id=self.default_agent_id,
            description=description,
            metadata=metadata,
            input_ids=input_ids,
            output_ids=[output_id],
            model_type=model_type,
            model_framework=model_framework,
            hyperparameters=hyperparameters,
            metrics=metrics,
            model_size=model_size,
            model_hash=model_hash
        )
        
        # Store the record
        self.records[record.id] = record
        
        # Add to provenance graph
        self.graph.add_node(record.id, 
                           record_type="model_training",
                           description=description,
                           timestamp=record.timestamp,
                           model_type=model_type)
        
        # Link to input data entities
        for input_id in input_ids:
            if input_id in self.entity_latest_record:
                input_record_id = self.entity_latest_record[input_id]
                self.graph.add_edge(input_record_id, record.id, type="input")
        
        # Link to output model entity
        self.graph.add_edge(record.id, output_id, type="output")
        
        # Update the entity's latest record
        self.entity_latest_record[output_id] = record.id
        
        # Calculate execution time
        record.execution_time = time.time() - start_time
        
        # Add cryptographic signature if enabled
        if self.enable_crypto_verification:
            self.sign_record(record)
        
        # Store in IPLD if enabled
        if self.enable_ipld_storage and self.ipld_storage:
            self._store_record_in_ipld(record)
            
        # Log to audit system if available
        self._audit_log_record(record, "model_training")
        
        # Index for semantic search
        self._index_for_semantic_search(record)
        
        # Index for temporal queries
        self._index_for_temporal_queries(record)
        
        return record.id
    
    def record_model_inference(
        self,
        model_id: str,
        input_ids: List[str],
        output_id: str,
        model_version: str = "",
        batch_size: Optional[int] = None,
        output_type: str = "",
        performance_metrics: Optional[Dict[str, float]] = None,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Record a model inference event.
        
        Args:
            model_id: ID of the model used
            input_ids: IDs of input data entities
            output_id: ID of output data entity (inference results)
            model_version: Model version
            batch_size: Size of inference batch
            output_type: Type of output (predictions, embeddings, etc.)
            performance_metrics: Inference performance metrics
            description: Description of the inference
            metadata: Additional metadata
            
        Returns:
            str: ID of the created model inference record
        """
        metadata = metadata or {}
        performance_metrics = performance_metrics or {}
        
        # Start timing if not already provided
        start_time = time.time()
        
        # Create model inference record
        record = ModelInferenceRecord(
            record_type=ProvenanceRecordType.TRANSFORMATION,
            agent_id=self.default_agent_id,
            description=description,
            metadata=metadata,
            input_ids=[model_id] + input_ids,  # Include model as input
            output_ids=[output_id],
            model_id=model_id,
            model_version=model_version,
            batch_size=batch_size,
            output_type=output_type,
            performance_metrics=performance_metrics
        )
        
        # Store the record
        self.records[record.id] = record
        
        # Add to provenance graph
        self.graph.add_node(record.id, 
                           record_type="model_inference",
                           description=description,
                           timestamp=record.timestamp,
                           model_id=model_id)
        
        # Link to model entity
        if model_id in self.entity_latest_record:
            model_record_id = self.entity_latest_record[model_id]
            self.graph.add_edge(model_record_id, record.id, type="model")
        
        # Link to input data entities
        for input_id in input_ids:
            if input_id in self.entity_latest_record:
                input_record_id = self.entity_latest_record[input_id]
                self.graph.add_edge(input_record_id, record.id, type="input")
        
        # Link to output entity
        self.graph.add_edge(record.id, output_id, type="output")
        
        # Update the entity's latest record
        self.entity_latest_record[output_id] = record.id
        
        # Calculate execution time
        record.execution_time = time.time() - start_time
        
        # Add cryptographic signature if enabled
        if self.enable_crypto_verification:
            self.sign_record(record)
        
        # Store in IPLD if enabled
        if self.enable_ipld_storage and self.ipld_storage:
            self._store_record_in_ipld(record)
            
        # Log to audit system if available
        self._audit_log_record(record, "model_inference")
        
        # Index for semantic search
        self._index_for_semantic_search(record)
        
        # Index for temporal queries
        self._index_for_temporal_queries(record)
        
        return record.id
    
    def _audit_log_record(self, record: ProvenanceRecord, operation_type: str) -> None:
        """
        Log a provenance record to the audit system if available.
        
        Args:
            record: The provenance record to log
            operation_type: Type of operation for categorization
        """
        if not AUDIT_AVAILABLE or self.audit_logger is None:
            return
            
        try:
            # Create details with basic record information
            details = {
                "record_id": record.id,
                "record_type": record.record_type.value,
                "description": record.description,
                "timestamp": record.timestamp
            }
            
            # Add cryptographic signature information if available
            if self.enable_crypto_verification and hasattr(record, 'signature') and record.signature:
                details["signature"] = record.signature
                details["verification_result"] = self.verification_results.get(record.id, None)
            
            # Create audit event
            event = AuditEvent(
                level=AuditLevel.INFO,
                category=AuditCategory.DATA_OPERATIONS,
                operation=operation_type,
                subject=f"data:{','.join(record.input_ids)}",
                object=f"data:{','.join(record.output_ids)}",
                status="success",
                details=details
            )
            
            # Log the event
            self.audit_logger.log_event(event)
        except Exception as e:
            self.logger.warning(f"Failed to log audit event: {str(e)}")
    
    def _index_for_semantic_search(self, record: ProvenanceRecord) -> None:
        """
        Index a record for semantic search.
        
        Args:
            record: The provenance record to index
        """
        # Extract keywords from record
        keywords = set()
        
        # Add record type
        keywords.add(record.record_type.value)
        
        # Add words from description
        if record.description:
            for word in record.description.lower().split():
                if len(word) > 3:  # Skip short words
                    keywords.add(word)
        
        # Add input and output IDs
        for input_id in record.input_ids:
            keywords.add(f"input:{input_id}")
        for output_id in record.output_ids:
            keywords.add(f"output:{output_id}")
        
        # Add record-specific keywords
        if isinstance(record, SourceRecord):
            keywords.add(f"source_type:{record.source_type}")
            keywords.add(f"format:{record.format}")
        elif isinstance(record, TransformationRecord):
            keywords.add(f"transformation_type:{record.transformation_type}")
            keywords.add(f"tool:{record.tool}")
        elif isinstance(record, VerificationRecord):
            keywords.add(f"verification_type:{record.verification_type}")
            keywords.add("valid" if record.is_valid else "invalid")
        elif isinstance(record, AnnotationRecord):
            keywords.add(f"annotation_type:{record.annotation_type}")
            keywords.add(f"author:{record.author}")
            for tag in record.tags:
                keywords.add(f"tag:{tag}")
        elif isinstance(record, ModelTrainingRecord):
            keywords.add(f"model_type:{record.model_type}")
            keywords.add(f"framework:{record.model_framework}")
        
        # Add to semantic index
        for keyword in keywords:
            if keyword not in self.semantic_index:
                self.semantic_index[keyword] = set()
            self.semantic_index[keyword].add(record.id)
    
    def _index_for_temporal_queries(self, record: ProvenanceRecord) -> None:
        """
        Index a record for temporal queries.
        
        Args:
            record: The provenance record to index
        """
        # Create time buckets for different granularities
        timestamp = record.timestamp
        dt = datetime.datetime.fromtimestamp(timestamp)
        
        # Daily bucket: YYYY-MM-DD
        daily_bucket = dt.strftime("%Y-%m-%d")
        if daily_bucket not in self.time_index:
            self.time_index[daily_bucket] = set()
        self.time_index[daily_bucket].add(record.id)
        
        # Hourly bucket: YYYY-MM-DD-HH
        hourly_bucket = dt.strftime("%Y-%m-%d-%H")
        if hourly_bucket not in self.time_index:
            self.time_index[hourly_bucket] = set()
        self.time_index[hourly_bucket].add(record.id)
        
        # Monthly bucket: YYYY-MM
        monthly_bucket = dt.strftime("%Y-%m")
        if monthly_bucket not in self.time_index:
            self.time_index[monthly_bucket] = set()
        self.time_index[monthly_bucket].add(record.id)
    
    def sign_record(self, record: ProvenanceRecord) -> bool:
        """
        Add a cryptographic signature to a provenance record.
        
        Args:
            record: The provenance record to sign
            
        Returns:
            bool: Whether the signing was successful
        """
        if not self.enable_crypto_verification or not self.crypto_verifier:
            self.logger.warning("Cryptographic verification is not enabled")
            return False
        
        try:
            # Generate signature
            signature = self.crypto_verifier.sign_record(record)
            
            # Add signature to record
            # We use a somewhat intrusive approach by adding a new attribute for simplicity
            record.signature = signature
            
            # Update verification results cache
            self.verification_results[record.id] = True
            
            return True
        except Exception as e:
            self.logger.error(f"Error signing record {record.id}: {str(e)}")
            return False
    
    def verify_record(self, record_id: str) -> bool:
        """
        Verify the cryptographic signature of a provenance record.
        
        Args:
            record_id: ID of the record to verify
            
        Returns:
            bool: Whether the signature is valid
        """
        if not self.enable_crypto_verification or not self.crypto_verifier:
            self.logger.warning("Cryptographic verification is not enabled")
            return False
        
        if record_id not in self.records:
            self.logger.warning(f"Record {record_id} not found")
            return False
        
        record = self.records[record_id]
        
        # Use cached result if available
        if record_id in self.verification_results:
            return self.verification_results[record_id]
        
        try:
            # Verify signature
            result = self.crypto_verifier.verify_record(record)
            
            # Cache result
            self.verification_results[record_id] = result
            
            return result
        except Exception as e:
            self.logger.error(f"Error verifying record {record_id}: {str(e)}")
            return False
    
    def verify_all_records(self) -> Dict[str, bool]:
        """
        Verify the cryptographic signatures of all records.
        
        Returns:
            Dict[str, bool]: Map from record ID to verification result
        """
        if not self.enable_crypto_verification or not self.crypto_verifier:
            self.logger.warning("Cryptographic verification is not enabled")
            return {}
        
        try:
            # Verify all records and update cache
            self.verification_results = self.crypto_verifier.verify_graph_integrity(self.records)
            return self.verification_results
        except Exception as e:
            self.logger.error(f"Error verifying all records: {str(e)}")
            return {}
    
    def sign_all_records(self) -> Dict[str, bool]:
        """
        Add cryptographic signatures to all records.
        
        Returns:
            Dict[str, bool]: Map from record ID to success status
        """
        if not self.enable_crypto_verification or not self.crypto_verifier:
            self.logger.warning("Cryptographic verification is not enabled")
            return {}
        
        results = {}
        
        try:
            # Get signatures for all records efficiently
            signatures = self.crypto_verifier.bulk_sign_records(list(self.records.values()))
            
            # Add signatures to records
            for record_id, signature in signatures.items():
                if record_id in self.records:
                    self.records[record_id].signature = signature
                    results[record_id] = True
                    
                    # If using IPLD storage, update the stored record with the signature
                    if self.enable_ipld_storage and self.ipld_storage and record_id in self.record_cids:
                        self._store_record_in_ipld(self.records[record_id])
                else:
                    results[record_id] = False
            
            # Update verification results cache
            for record_id in signatures:
                self.verification_results[record_id] = True
            
            return results
        except Exception as e:
            self.logger.error(f"Error signing all records: {str(e)}")
            return results
            
    # IPLD storage integration methods
    def _register_ipld_schemas(self) -> None:
        """Register provenance record schemas with IPLD storage."""
        if not self.enable_ipld_storage or not self.ipld_storage:
            return
            
        try:
            # Register base provenance record schema
            self.ipld_storage.register_schema(
                "provenance_record", 
                ProvenanceIPLDSchema.PROVENANCE_RECORD
            )
            
            # Register specific record type schemas
            self.ipld_storage.register_schema(
                "source_record", 
                ProvenanceIPLDSchema.SOURCE_RECORD
            )
            
            self.ipld_storage.register_schema(
                "transformation_record", 
                ProvenanceIPLDSchema.TRANSFORMATION_RECORD
            )
            
            self.ipld_storage.register_schema(
                "verification_record", 
                ProvenanceIPLDSchema.VERIFICATION_RECORD
            )
            
            # Register provenance graph schema
            self.ipld_storage.register_schema(
                "provenance_graph", 
                ProvenanceIPLDSchema.PROVENANCE_GRAPH
            )
            
            self.logger.info("Registered IPLD schemas for provenance records")
        except Exception as e:
            self.logger.error(f"Error registering IPLD schemas: {str(e)}")
    
    def _store_record_in_ipld(self, record: ProvenanceRecord) -> Optional[str]:
        """
        Store a provenance record in IPLD.
        
        Args:
            record: The provenance record to store
            
        Returns:
            Optional[str]: CID of the stored record, or None if storage failed
        """
        if not self.enable_ipld_storage:
            return None
            
        try:
            # If enhanced IPLD provenance storage is available, use it
            if self.ipld_provenance_storage:
                # Store with cryptographic signing if verification is enabled
                use_signing = self.enable_crypto_verification and self.crypto_verifier is not None
                cid = self.ipld_provenance_storage.store_record(record, sign=use_signing)
            else:
                # Fall back to basic IPLD storage
                # Convert record to dict
                record_dict = record.to_dict()
                
                # Determine schema based on record type
                schema_name = "provenance_record"  # Default schema
                if isinstance(record, SourceRecord):
                    schema_name = "source_record"
                elif isinstance(record, TransformationRecord):
                    schema_name = "transformation_record"
                elif isinstance(record, VerificationRecord):
                    schema_name = "verification_record"
                
                # Store with schema validation
                cid = self.ipld_storage.store_with_schema(record_dict, schema_name)
            
            # Update CID mapping
            self.record_cids[record.id] = cid
            
            return cid
        except Exception as e:
            self.logger.error(f"Error storing record {record.id} in IPLD: {str(e)}")
            return None
    
    def _update_ipld_graph(self) -> Optional[str]:
        """
        Update the IPLD representation of the full provenance graph.
        
        Returns:
            Optional[str]: CID of the graph root, or None if update failed
        """
        if not self.enable_ipld_storage or not self.ipld_storage:
            return None
            
        try:
            # Create a graph representation compatible with IPLD
            graph_dict = {
                "records": {},                 # Map of record_id -> record CID
                "links": [],                   # List of source -> target links
                "root_records": [],            # List of root record IDs
                "metadata": {
                    "record_count": len(self.records),
                    "link_count": self.graph.number_of_edges(),
                    "tracking_level": self.tracking_level,
                },
                "created_at": time.time(),
                "updated_at": time.time(),
                "version": "1.0"
            }
            
            # Add record CIDs to the graph
            for record_id, cid in self.record_cids.items():
                graph_dict["records"][record_id] = cid
            
            # Add links (edges) from the graph
            for u, v, data in self.graph.edges(data=True):
                link = {
                    "source": u,
                    "target": v,
                    "type": data.get("type", "default")
                }
                graph_dict["links"].append(link)
            
            # Identify root records (no incoming edges)
            for node in self.graph.nodes():
                if self.graph.in_degree(node) == 0:
                    graph_dict["root_records"].append(node)
            
            # Store the graph with schema validation
            self.ipld_root_cid = self.ipld_storage.store_with_schema(
                graph_dict, 
                "provenance_graph"
            )
            
            return self.ipld_root_cid
        except Exception as e:
            self.logger.error(f"Error updating IPLD graph: {str(e)}")
            return None
    
    def export_to_car(self, output_path: str) -> Optional[str]:
        """
        Export the entire provenance graph to a CAR file.
        
        Args:
            output_path: Path to write the CAR file
            
        Returns:
            Optional[str]: Root CID of the exported data, or None if export failed
        """
        if not self.enable_ipld_storage:
            self.logger.warning("IPLD storage not enabled, cannot export to CAR")
            return None
            
        try:
            if self.ipld_provenance_storage:
                # Use enhanced provenance storage for export
                # First, build a NetworkX graph from our records
                graph = nx.DiGraph()
                
                # Add nodes (records)
                for record_id, record in self.records.items():
                    graph.add_node(record_id, record=record)
                
                # Add edges based on relationships
                for record_id, record in self.records.items():
                    if hasattr(record, 'input_ids') and record.input_ids:
                        for input_id in record.input_ids:
                            if input_id in self.records:
                                graph.add_edge(input_id, record_id, relation="input_to")
                    
                    if hasattr(record, 'output_id') and record.output_id:
                        if record.output_id in self.records:
                            graph.add_edge(record_id, record.output_id, relation="output_to")
                
                # Use enhanced storage to export the graph
                result_cid = self.ipld_provenance_storage.export_to_car(
                    output_path=output_path,
                    include_records=True,
                    include_graph=True
                )
                
                self.logger.info(f"Exported provenance graph to CAR file using enhanced storage: {output_path}")
                return result_cid
            else:
                # Fall back to basic IPLD storage if enhanced storage is unavailable
                # First ensure all records are stored in IPLD
                for record_id, record in self.records.items():
                    if record_id not in self.record_cids:
                        self._store_record_in_ipld(record)
                
                # Update the graph representation
                root_cid = self._update_ipld_graph()
                if not root_cid:
                    raise ValueError("Failed to generate IPLD graph representation")
                
                # Export everything to CAR
                cids_to_export = [root_cid]  # Start with the graph root
                
                # Add all record CIDs
                cids_to_export.extend(self.record_cids.values())
                
                # Export to CAR
                result_cid = self.ipld_storage.export_to_car(cids_to_export, output_path)
                
                self.logger.info(f"Exported provenance graph to CAR file: {output_path}")
                return result_cid
        except Exception as e:
            self.logger.error(f"Error exporting to CAR: {str(e)}")
            return None
            return None
    
    def import_from_car(self, car_path: str) -> bool:
        """
        Import a provenance graph from a CAR file.
        
        Args:
            car_path: Path to the CAR file to import
            
        Returns:
            bool: Whether the import was successful
        """
        if not self.enable_ipld_storage:
            self.logger.warning("IPLD storage not enabled, cannot import from CAR")
            return False
            
        try:
            if self.ipld_provenance_storage:
                # Use enhanced provenance storage for import
                self.logger.info(f"Importing provenance graph from CAR file using enhanced storage: {car_path}")
                
                # Import using the enhanced storage
                success = self.ipld_provenance_storage.import_from_car(car_path, load_graph=True)
                
                if success:
                    # Load the graph into our records
                    imported_graph = self.ipld_provenance_storage.load_graph()
                    
                    # Import records from the graph
                    imported_count = 0
                    for node_id in imported_graph.nodes:
                        if 'record' in imported_graph.nodes[node_id]:
                            record = imported_graph.nodes[node_id]['record']
                            self.records[node_id] = record
                            imported_count += 1
                    
                    # Rebuild indices
                    self._rebuild_indices()
                    
                    self.logger.info(f"Successfully imported {imported_count} records from CAR file")
                    return True
                else:
                    self.logger.error("Failed to import from CAR file using enhanced storage")
                    return False
            else:
                # Fall back to basic IPLD storage
                # Import the CAR file
                root_cids = self.ipld_storage.import_from_car(car_path)
                if not root_cids:
                    raise ValueError("No root CIDs found in CAR file")
                
                # Find the graph root CID
                graph_root = None
                for cid in root_cids:
                    try:
                        # Try to parse as a graph
                        graph_data = self.ipld_storage.get_with_schema(cid, "provenance_graph")
                        graph_root = cid
                        break
                    except:
                        # Not a graph root, continue to next CID
                        continue
                
                if not graph_root:
                    raise ValueError("No valid provenance graph found in CAR file")
                
                # Store the root CID
                self.ipld_root_cid = graph_root
                
                # Get the graph data
                graph_data = self.ipld_storage.get_with_schema(graph_root, "provenance_graph")
                
                # Import records
                imported_count = 0
                for record_id, record_cid in graph_data.get("records", {}).items():
                    # Get the record data
                    try:
                        record_data = self.ipld_storage.get_json(record_cid)
                    
                    # Create a record instance based on the record type
                    record_type = record_data.get("record_type")
                    if record_type == "source":
                        record = SourceRecord.from_dict(record_data)
                    elif record_type == "transformation":
                        record = TransformationRecord.from_dict(record_data)
                    elif record_type == "verification":
                        record = VerificationRecord.from_dict(record_data)
                    else:
                        # Generic record type
                        record = ProvenanceRecord.from_dict(record_data)
                    
                    # Add to records dictionary
                    self.records[record_id] = record
                    self.record_cids[record_id] = record_cid
                    imported_count += 1
                except Exception as e:
                    self.logger.warning(f"Error importing record {record_id}: {str(e)}")
            
            # Rebuild the graph
            self.graph = nx.DiGraph()
            
            # Add nodes
            for record_id in self.records:
                record = self.records[record_id]
                record_type = getattr(record, "record_type", ProvenanceRecordType.SOURCE).value
                self.graph.add_node(record_id, record_type=record_type)
            
            # Add edges from the imported graph data
            for link in graph_data.get("links", []):
                source = link.get("source")
                target = link.get("target")
                link_type = link.get("type", "default")
                
                if source in self.records and target in self.records:
                    self.graph.add_edge(source, target, type=link_type)
            
            # Rebuild indices
            self._rebuild_indices()
            
            self.logger.info(f"Imported {imported_count} records from CAR file: {car_path}")
            return True
        except Exception as e:
            self.logger.error(f"Error importing from CAR: {str(e)}")
            return False
    
    def _rebuild_indices(self) -> None:
        """Rebuild all indices after importing records."""
        # Clear existing indices
        self.entity_latest_record = {}
        self.semantic_index = {}
        self.time_index = {}
        
        # Rebuild entity latest record index
        for record_id, record in self.records.items():
            if hasattr(record, "output_ids"):
                for entity_id in record.output_ids:
                    # For each entity, record is the latest if it's newer than current latest
                    if entity_id not in self.entity_latest_record or \
                       record.timestamp > self.records[self.entity_latest_record[entity_id]].timestamp:
                        self.entity_latest_record[entity_id] = record_id
        
        # Rebuild semantic index
        for record_id, record in self.records.items():
            self._index_for_semantic_search(record)
        
        # Rebuild time index
        for record_id, record in self.records.items():
            self._index_for_temporal_queries(record)
        
        # Verify signatures if crypto verification is enabled
        if self.enable_crypto_verification and self.crypto_verifier:
            self.verification_results = self.crypto_verifier.verify_graph_integrity(self.records)
    
    def add_record(self, record: ProvenanceRecord) -> str:
        """
        Add a provenance record directly to the manager.
        
        This is a utility method for incorporating externally created records.
        
        Args:
            record: The provenance record to add
            
        Returns:
            str: ID of the added record
        """
        # Store the record
        self.records[record.id] = record
        
        # Add to provenance graph
        self.graph.add_node(record.id, 
                            record_type=record.record_type.value,
                            timestamp=record.timestamp)
        
        # Add edges based on inputs and outputs
        if hasattr(record, 'input_ids'):
            for input_id in record.input_ids:
                if input_id in self.entity_latest_record:
                    input_record_id = self.entity_latest_record[input_id]
                    self.graph.add_edge(input_record_id, record.id, type="input")
        
        if hasattr(record, 'output_ids'):
            for output_id in record.output_ids:
                # Update the entity's latest record
                self.entity_latest_record[output_id] = record.id
        
        # Add cryptographic signature if enabled
        if self.enable_crypto_verification and not hasattr(record, 'signature'):
            self.sign_record(record)
        
        # Store in IPLD if enabled
        if self.enable_ipld_storage and self.ipld_storage:
            self._store_record_in_ipld(record)
        
        # Index for semantic search
        self._index_for_semantic_search(record)
        
        # Index for temporal queries
        self._index_for_temporal_queries(record)
        
        return record.id
    
    def semantic_search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Search for provenance records using keywords.
        
        Args:
            query: Search query string
            limit: Maximum number of results to return
            
        Returns:
            List[Dict[str, Any]]: Matching records with relevance scores
        """
        # Parse query into keywords
        keywords = query.lower().split()
        
        # Find matching records
        record_scores = {}
        for keyword in keywords:
            # Look for exact matches
            if keyword in self.semantic_index:
                for record_id in self.semantic_index[keyword]:
                    if record_id not in record_scores:
                        record_scores[record_id] = 0
                    record_scores[record_id] += 1
            
            # Look for partial matches
            for index_keyword, record_ids in self.semantic_index.items():
                if keyword in index_keyword and keyword != index_keyword:
                    for record_id in record_ids:
                        if record_id not in record_scores:
                            record_scores[record_id] = 0
                        record_scores[record_id] += 0.5  # Lower score for partial match
        
        # Sort results by score (descending)
        sorted_results = sorted(
            [(record_id, score) for record_id, score in record_scores.items()],
            key=lambda x: x[1],
            reverse=True
        )
        
        # Format results
        results = []
        for record_id, score in sorted_results[:limit]:
            record = self.records[record_id]
            results.append({
                "record_id": record_id,
                "record_type": record.record_type.value,
                "description": record.description,
                "timestamp": record.timestamp,
                "score": score,
                "record": record.to_dict()
            })
        
        return results
    
    def temporal_query(
        self,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        time_bucket: str = "daily",
        record_types: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Query records based on time ranges.
        
        Args:
            start_time: Start timestamp (Unix time)
            end_time: End timestamp (Unix time)
            time_bucket: Time bucket granularity ("daily", "hourly", "monthly")
            record_types: Types of records to include
            
        Returns:
            List[Dict[str, Any]]: Matching records
        """
        # Convert timestamps to datetime objects
        start_dt = datetime.datetime.fromtimestamp(start_time) if start_time else None
        end_dt = datetime.datetime.fromtimestamp(end_time) if end_time else datetime.datetime.now()
        
        # Generate time bucket keys for the date range
        bucket_keys = []
        if time_bucket == "hourly":
            fmt = "%Y-%m-%d-%H"
        elif time_bucket == "monthly":
            fmt = "%Y-%m"
        else:  # daily (default)
            fmt = "%Y-%m-%d"
        
        # If start_time is None, use all indexed buckets
        if start_dt is None:
            matching_buckets = [b for b in self.time_index.keys() if len(b.split("-")) == len(fmt.split("-"))]
        else:
            # Generate all bucket keys in the date range
            current_dt = start_dt
            while current_dt <= end_dt:
                bucket_key = current_dt.strftime(fmt)
                bucket_keys.append(bucket_key)
                
                # Increment based on bucket type
                if time_bucket == "hourly":
                    current_dt += datetime.timedelta(hours=1)
                elif time_bucket == "monthly":
                    # Move to next month
                    if current_dt.month == 12:
                        current_dt = current_dt.replace(year=current_dt.year + 1, month=1)
                    else:
                        current_dt = current_dt.replace(month=current_dt.month + 1)
                else:  # daily
                    current_dt += datetime.timedelta(days=1)
            
            # Find matching buckets
            matching_buckets = [b for b in bucket_keys if b in self.time_index]
        
        # Collect record IDs from matching buckets
        record_ids = set()
        for bucket in matching_buckets:
            record_ids.update(self.time_index[bucket])
        
        # Filter by record type if specified
        if record_types:
            filtered_ids = set()
            for record_id in record_ids:
                if record_id in self.records:
                    record = self.records[record_id]
                    if record.record_type.value in record_types:
                        filtered_ids.add(record_id)
            record_ids = filtered_ids
        
        # Convert to list of record dictionaries
        results = []
        for record_id in sorted(record_ids, key=lambda x: self.records[x].timestamp if x in self.records else 0):
            if record_id in self.records:
                record = self.records[record_id]
                results.append({
                    "record_id": record_id,
                    "record_type": record.record_type.value,
                    "description": record.description,
                    "timestamp": record.timestamp,
                    "record": record.to_dict()
                })
        
        return results
    
    def calculate_data_metrics(self, data_id: str) -> Dict[str, Any]:
        """
        Calculate comprehensive metrics for a data entity's provenance.
        
        Args:
            data_id: ID of the data entity
            
        Returns:
            Dict[str, Any]: Dictionary of metrics
        """
        metrics = {}
        
        # Basic complexity metrics
        complexity = ProvenanceMetrics.calculate_complexity(self.graph, data_id)
        metrics["complexity"] = complexity
        
        # Impact metrics
        metrics["impact"] = ProvenanceMetrics.calculate_data_impact(self.graph, data_id)
        
        # Time metrics
        if data_id in self.entity_latest_record:
            latest_record_id = self.entity_latest_record[data_id]
            latest_record = self.records.get(latest_record_id)
            
            if latest_record:
                first_timestamp = float('inf')
                last_timestamp = 0
                
                # Find first and last timestamps for this entity
                for record_id, record in self.records.items():
                    if data_id in record.input_ids or data_id in record.output_ids:
                        first_timestamp = min(first_timestamp, record.timestamp)
                        last_timestamp = max(last_timestamp, record.timestamp)
                
                if first_timestamp < float('inf'):
                    metrics["first_timestamp"] = first_timestamp
                    metrics["last_timestamp"] = last_timestamp
                    metrics["age_seconds"] = last_timestamp - first_timestamp
                    metrics["update_frequency"] = complexity["node_count"] / max(1, metrics["age_seconds"] / 86400)  # per day
        
        # Record type counts
        record_type_counts = {}
        for record_id, record in self.records.items():
            if data_id in record.input_ids or data_id in record.output_ids:
                record_type = record.record_type.value
                if record_type not in record_type_counts:
                    record_type_counts[record_type] = 0
                record_type_counts[record_type] += 1
        
        metrics["record_type_counts"] = record_type_counts
        
        # Data quality metrics (if verification records exist)
        verification_metrics = {
            "verifications": 0,
            "passed": 0,
            "failed": 0,
            "last_verification": None,
            "is_valid": None
        }
        
        for record_id, record in self.records.items():
            if isinstance(record, VerificationRecord) and data_id in record.input_ids:
                verification_metrics["verifications"] += 1
                if record.is_valid:
                    verification_metrics["passed"] += 1
                else:
                    verification_metrics["failed"] += 1
                
                # Track last verification
                if verification_metrics["last_verification"] is None or record.timestamp > verification_metrics["last_verification"]:
                    verification_metrics["last_verification"] = record.timestamp
                    verification_metrics["is_valid"] = record.is_valid
        
        metrics["verification"] = verification_metrics
        
        return metrics
    
    def get_lineage_graph(self, record_id: str, depth: int = 5) -> nx.DiGraph:
        """
        Get the lineage graph for a specific record.
        
        Args:
            record_id: ID of the record to get lineage for
            depth: Maximum depth to traverse
            
        Returns:
            nx.DiGraph: Lineage graph
        """
        # If enhanced IPLD provenance storage is available, use its advanced traversal
        if self.enable_ipld_storage and self.ipld_provenance_storage:
            try:
                # Ensure the record is stored in IPLD first
                if record_id in self.records and record_id not in self.record_cids:
                    self._store_record_in_ipld(self.records[record_id])
                
                # Use the enhanced traversal capabilities
                if record_id in self.record_cids:
                    return self.ipld_provenance_storage.traverse_graph_from_node(
                        start_node_id=record_id,
                        max_depth=depth,
                        direction="both"
                    )
            except Exception as e:
                self.logger.warning(f"Error using enhanced traversal, falling back to basic: {str(e)}")
                # Fall back to basic traversal if error occurs
        
        # Basic traversal implementation
        graph = nx.DiGraph()
        
        # Start with the requested record
        if record_id not in self.records:
            return graph
            
        record = self.records[record_id]
        graph.add_node(record_id, record=record)
        
        # Queue for breadth-first traversal
        queue = [(record_id, 0)]  # (record_id, depth)
        visited = {record_id}
        
        while queue:
            current_id, current_depth = queue.pop(0)
            
            if current_depth >= depth:
                continue
                
            current_record = self.records[current_id]
            
            # Add upstream connections (inputs)
            if hasattr(current_record, 'input_ids') and current_record.input_ids:
                for input_id in current_record.input_ids:
                    if input_id in self.records and input_id not in visited:
                        input_record = self.records[input_id]
                        graph.add_node(input_id, record=input_record)
                        graph.add_edge(input_id, current_id)
                        queue.append((input_id, current_depth + 1))
                        visited.add(input_id)
            
            # Add downstream connections (where this record is an input)
            for other_id, other_record in self.records.items():
                if hasattr(other_record, 'input_ids') and other_record.input_ids and current_id in other_record.input_ids:
                    if other_id not in visited:
                        graph.add_node(other_id, record=other_record)
                        graph.add_edge(current_id, other_id)
                        queue.append((other_id, current_depth + 1))
                        visited.add(other_id)
        
        return graph
        
    def traverse_provenance(self, record_id: str, max_depth: int = 3, 
                           direction: str = "both", relation_filter: Optional[List[str]] = None) -> nx.DiGraph:
        """
        Advanced traversal of the provenance graph from a starting record.
        
        This method uses the enhanced IPLD provenance storage capabilities to perform
        efficient graph traversal with fine-grained control over traversal direction
        and relation types.
        
        Args:
            record_id: ID of the starting record
            max_depth: Maximum traversal depth
            direction: Direction of traversal ("in", "out", or "both")
                - "in": Only traverse to records that input to this record
                - "out": Only traverse to records that this record outputs to
                - "both": Traverse in both directions
            relation_filter: Optional list of relation types to follow
            
        Returns:
            nx.DiGraph: Subgraph reachable from the starting record
        """
        if not self.enable_ipld_storage or not self.ipld_provenance_storage:
            # Fall back to regular lineage graph with less control
            self.logger.warning("Enhanced IPLD storage not available, falling back to basic lineage graph")
            return self.get_lineage_graph(record_id, depth=max_depth)
        
        try:
            # Ensure the record is stored in IPLD
            if record_id in self.records and record_id not in self.record_cids:
                self._store_record_in_ipld(self.records[record_id])
            
            # Use the enhanced traversal
            if record_id in self.record_cids:
                return self.ipld_provenance_storage.traverse_graph_from_node(
                    start_node_id=record_id,
                    max_depth=max_depth,
                    direction=direction,
                    relation_filter=relation_filter
                )
            else:
                self.logger.warning(f"Record {record_id} not found in IPLD storage")
                return nx.DiGraph()
        except Exception as e:
            self.logger.error(f"Error during advanced traversal: {str(e)}")
            return nx.DiGraph()
    
    def incremental_load_provenance(self, criteria: Dict) -> nx.DiGraph:
        """
        Incrementally load parts of the provenance graph based on criteria.
        
        This allows loading only relevant portions of large provenance graphs,
        which is more efficient than loading the entire graph.
        
        Args:
            criteria: Filtering criteria with any of these keys:
                - time_start: Minimum timestamp
                - time_end: Maximum timestamp
                - data_ids: List of data IDs to include
                - record_types: List of record types to include
                
        Returns:
            nx.DiGraph: Partial provenance graph matching criteria
        """
        if not self.enable_ipld_storage or not self.ipld_provenance_storage:
            # Fall back to filtering the in-memory graph
            self.logger.warning("Enhanced IPLD storage not available, filtering in-memory graph")
            return self._filter_graph_by_criteria(criteria)
        
        try:
            # Use enhanced incremental loading
            if self.ipld_provenance_storage.root_graph_cid:
                return self.ipld_provenance_storage.incremental_load(
                    self.ipld_provenance_storage.root_graph_cid,
                    criteria=criteria
                )
            else:
                self.logger.warning("No root graph CID available for incremental loading")
                return nx.DiGraph()
        except Exception as e:
            self.logger.error(f"Error during incremental loading: {str(e)}")
            return self._filter_graph_by_criteria(criteria)
    
    def _filter_graph_by_criteria(self, criteria: Dict) -> nx.DiGraph:
        """
        Filter the in-memory graph based on criteria.
        
        Args:
            criteria: Filtering criteria
            
        Returns:
            nx.DiGraph: Filtered graph
        """
        # Extract criteria
        time_start = criteria.get("time_start")
        time_end = criteria.get("time_end")
        data_ids = set(criteria.get("data_ids", []))
        record_types = set(criteria.get("record_types", []))
        
        # Create a new graph
        graph = nx.DiGraph()
        
        # Filter records based on criteria
        for record_id, record in self.records.items():
            # Check timestamp
            if time_start is not None and record.timestamp < time_start:
                continue
            if time_end is not None and record.timestamp > time_end:
                continue
            
            # Check data_id
            if data_ids and hasattr(record, 'data_id') and record.data_id not in data_ids:
                continue
            
            # Check record_type
            record_type = record.record_type.value if isinstance(record.record_type, Enum) else record.record_type
            if record_types and record_type not in record_types:
                continue
            
            # Record passes all filters, add it to the graph
            graph.add_node(record_id, record=record)
        
        # Add edges between nodes in the graph
        for record_id in graph.nodes:
            record = self.records[record_id]
            
            # Add input edges
            if hasattr(record, 'input_ids') and record.input_ids:
                for input_id in record.input_ids:
                    if input_id in graph:
                        graph.add_edge(input_id, record_id, relation="input_to")
        
        return graph
    
    def visualize_provenance_enhanced(
        self, 
        data_ids: Optional[List[str]] = None,
        max_depth: int = 5,
        include_parameters: bool = False,
        show_timestamps: bool = True,
        layout: str = "hierarchical",  # "hierarchical", "spring", "circular", "spectral"
        highlight_critical_path: bool = False,
        include_metrics: bool = False,
        file_path: Optional[str] = None,
        format: str = "png",  # "png", "svg", "html", "json"
        return_base64: bool = False,
        width: int = 1200,
        height: int = 800,
        custom_colors: Optional[Dict[str, str]] = None
    ) -> Optional[Union[str, Dict[str, Any]]]:
        """
        Enhanced visualization of the provenance graph.
        
        Args:
            data_ids: List of data entity IDs to visualize, None for all
            max_depth: Maximum depth to trace back
            include_parameters: Whether to include operation parameters
            show_timestamps: Whether to show timestamps
            layout: Layout algorithm to use
            highlight_critical_path: Whether to highlight the critical path
            include_metrics: Whether to include metrics in the visualization
            file_path: Path to save the visualization
            format: Output format
            return_base64: Whether to return the image as base64
            width: Width of the visualization
            height: Height of the visualization
            custom_colors: Custom colors for node types
            
        Returns:
            Optional[Union[str, Dict[str, Any]]]: Visualization result
        """
        # Create subgraph for visualization
        subgraph = self._create_visualization_subgraph(data_ids, max_depth)
        
        # If no subgraph, return None
        if not subgraph or subgraph.number_of_nodes() == 0:
            return None
        
        # Choose visualization method based on engine and format
        if self.visualization_engine == "plotly" and PLOTLY_AVAILABLE and format in ["html", "json"]:
            return self._visualize_with_plotly(
                subgraph, include_parameters, show_timestamps, layout,
                highlight_critical_path, include_metrics, file_path, format,
                width, height, custom_colors
            )
        elif self.visualization_engine == "dash" and DASH_AVAILABLE and format == "html":
            return self._visualize_with_dash(
                subgraph, include_parameters, show_timestamps, layout,
                highlight_critical_path, include_metrics, file_path,
                width, height, custom_colors
            )
        else:
            # Default to matplotlib
            return self._visualize_with_matplotlib(
                subgraph, include_parameters, show_timestamps, layout,
                highlight_critical_path, include_metrics, file_path, format,
                return_base64, width, height, custom_colors
            )
    
    def _create_visualization_subgraph(self, data_ids: Optional[List[str]], max_depth: int) -> nx.DiGraph:
        """
        Create a subgraph for visualization based on specified data IDs.
        
        Args:
            data_ids: List of data entity IDs to visualize, None for all
            max_depth: Maximum depth to trace back
            
        Returns:
            nx.DiGraph: Subgraph for visualization
        """
        if data_ids:
            # Start with the latest records for the specified data entities
            record_ids = []
            for data_id in data_ids:
                if data_id in self.entity_latest_record:
                    record_ids.append(self.entity_latest_record[data_id])
                elif data_id in self.records:
                    record_ids.append(data_id)
            
            # Create a subgraph by tracing back from these records
            subgraph_nodes = set()
            for record_id in record_ids:
                # BFS to find ancestors up to max_depth
                queue = [(record_id, 0)]
                while queue:
                    node_id, depth = queue.pop(0)
                    if depth > max_depth:
                        continue
                        
                    subgraph_nodes.add(node_id)
                    
                    # Add predecessors to queue
                    for pred in self.graph.predecessors(node_id):
                        queue.append((pred, depth + 1))
            
            # Create subgraph
            subgraph = self.graph.subgraph(subgraph_nodes)
        else:
            # Use the full graph
            subgraph = self.graph
            
        return subgraph
    
    def _visualize_with_matplotlib(
        self,
        subgraph: nx.DiGraph,
        include_parameters: bool,
        show_timestamps: bool,
        layout: str,
        highlight_critical_path: bool,
        include_metrics: bool,
        file_path: Optional[str],
        format: str,
        return_base64: bool,
        width: int,
        height: int,
        custom_colors: Optional[Dict[str, str]]
    ) -> Optional[str]:
        """
        Visualize provenance graph using matplotlib.
        
        Args:
            subgraph: Subgraph to visualize
            include_parameters: Whether to include operation parameters
            show_timestamps: Whether to show timestamps
            layout: Layout algorithm to use
            highlight_critical_path: Whether to highlight the critical path
            include_metrics: Whether to include metrics in the visualization
            file_path: Path to save the visualization
            format: Output format
            return_base64: Whether to return the image as base64
            width: Width of the visualization
            height: Height of the visualization
            custom_colors: Custom colors for node types
            
        Returns:
            Optional[str]: Base64-encoded image if return_base64 is True
        """
        import matplotlib
        matplotlib.use('Agg')  # Use non-interactive backend
        
        # Set up figure size
        plt.figure(figsize=(width/100, height/100), dpi=100)
        
        # Choose layout algorithm
        if layout == "hierarchical":
            pos = nx.multipartite_layout(subgraph, subset_key="depth", scale=0.9)
        elif layout == "circular":
            pos = nx.circular_layout(subgraph)
        elif layout == "spectral":
            pos = nx.spectral_layout(subgraph)
        else:  # default to spring layout
            pos = nx.spring_layout(subgraph, k=0.2, iterations=50, seed=42)
        
        # Define node colors based on record type
        default_colors = {
            "source": "lightblue",
            "transformation": "lightgreen",
            "merge": "orange",
            "query": "lightcoral",
            "result": "yellow",
            "checkpoint": "purple",
            "verification": "cyan",
            "annotation": "pink",
            "model_training": "lightseagreen", 
            "model_inference": "lightskyblue",
            "data_entity": "gray"
        }
        
        # Override with custom colors if provided
        node_color_map = {**default_colors, **(custom_colors or {})}
        
        # Calculate node sizes based on importance or metrics
        node_sizes = []
        node_colors = []
        for node in subgraph.nodes():
            node_type = subgraph.nodes[node].get('record_type', '')
            
            # Determine node color
            color = node_color_map.get(node_type, "white")
            node_colors.append(color)
            
            # Determine node size
            if include_metrics and node in self.records:
                # Size based on centrality or importance
                try:
                    # Use node degree as a simple measure of importance
                    degree = subgraph.degree(node)
                    size = 300 + (degree * 50)  # Scale up size based on degree
                except:
                    size = 500
            else:
                size = 500
                
            node_sizes.append(size)
        
        # Draw nodes
        nx.draw_networkx_nodes(subgraph, pos, node_color=node_colors, 
                               node_size=node_sizes, alpha=0.8)
        
        # Draw edges with different styles based on type
        edge_styles = {
            "input": {"color": "blue", "width": 1.5, "arrow": True, "style": "solid"},
            "output": {"color": "green", "width": 1.5, "arrow": True, "style": "solid"},
            "includes": {"color": "gray", "width": 1.0, "arrow": True, "style": "dashed"},
            "produces": {"color": "red", "width": 1.5, "arrow": True, "style": "solid"},
            "checkpoint": {"color": "purple", "width": 1.0, "arrow": True, "style": "dotted"},
            "verifies": {"color": "cyan", "width": 1.0, "arrow": True, "style": "dashdot"},
            "annotates": {"color": "pink", "width": 1.0, "arrow": True, "style": "dashdot"}
        }
        
        # Group edges by type
        edges_by_type = {}
        for u, v, data in subgraph.edges(data=True):
            edge_type = data.get("type", "default")
            if edge_type not in edges_by_type:
                edges_by_type[edge_type] = []
            edges_by_type[edge_type].append((u, v))
        
        # Draw edges by type
        for edge_type, edges in edges_by_type.items():
            style = edge_styles.get(edge_type, {"color": "black", "width": 1.0, "arrow": True, "style": "solid"})
            nx.draw_networkx_edges(
                subgraph, pos, edgelist=edges, 
                width=style["width"],
                edge_color=style["color"],
                arrows=style["arrow"],
                style=style["style"]
            )
        
        # Highlight critical path if requested
        if highlight_critical_path and len(subgraph) > 0:
            try:
                # Find terminal nodes (no outgoing edges)
                terminal_nodes = [n for n in subgraph.nodes() if subgraph.out_degree(n) == 0]
                
                # Find source nodes (no incoming edges)
                source_nodes = [n for n in subgraph.nodes() if subgraph.in_degree(n) == 0]
                
                # If we have both terminal and source nodes, find critical path
                if terminal_nodes and source_nodes:
                    # Find longest path from any source to any terminal
                    longest_path = []
                    for s in source_nodes:
                        for t in terminal_nodes:
                            try:
                                path = nx.shortest_path(subgraph, s, t)
                                if len(path) > len(longest_path):
                                    longest_path = path
                            except nx.NetworkXNoPath:
                                continue
                    
                    # Highlight the critical path
                    if longest_path:
                        critical_edges = [(longest_path[i], longest_path[i+1]) 
                                        for i in range(len(longest_path)-1)]
                        nx.draw_networkx_edges(
                            subgraph, pos,
                            edgelist=critical_edges,
                            width=3.0,
                            edge_color="red",
                            arrows=True
                        )
            except Exception as e:
                self.logger.warning(f"Failed to highlight critical path: {str(e)}")
        
        # Prepare node labels
        node_labels = {}
        for node in subgraph.nodes():
            node_type = subgraph.nodes[node].get('record_type', '')
            description = subgraph.nodes[node].get('description', '')
            
            # For data entities, just use the node ID
            if node_type == 'data_entity':
                node_labels[node] = node
                continue
                
            # For other nodes, include more information
            if node in self.records:
                record = self.records[node]
                label_parts = [f"{node_type}:\n{description[:20]}"]
                
                if show_timestamps:
                    timestamp_str = datetime.datetime.fromtimestamp(record.timestamp).strftime('%Y-%m-%d %H:%M:%S')
                    label_parts.append(timestamp_str)
                    
                if include_parameters and hasattr(record, 'parameters') and record.parameters:
                    param_str = str(record.parameters)
                    if len(param_str) > 30:
                        param_str = param_str[:27] + "..."
                    label_parts.append(f"Params: {param_str}")
                    
                node_labels[node] = "\n".join(label_parts)
            else:
                node_labels[node] = f"{node_type}:\n{description[:20]}"
        
        # Draw node labels
        nx.draw_networkx_labels(subgraph, pos, labels=node_labels, 
                               font_size=8, font_family='sans-serif')
        
        # Set plot title
        plt.title("Provenance Graph", fontsize=16)
        
        # Add a legend
        legend_elements = []
        for record_type, color in node_color_map.items():
            legend_elements.append(plt.Line2D([0], [0], marker='o', color='w', 
                                  markerfacecolor=color, markersize=10, label=record_type))
        plt.legend(handles=legend_elements, loc='upper right')
        
        # Add metrics if requested
        if include_metrics:
            metrics_text = "Graph Metrics:\n"
            metrics_text += f"Nodes: {subgraph.number_of_nodes()}\n"
            metrics_text += f"Edges: {subgraph.number_of_edges()}\n"
            
            # Add centrality metrics for top nodes
            try:
                centrality = ProvenanceMetrics.calculate_centrality(subgraph)
                top_centrality = sorted(centrality.items(), key=lambda x: x[1], reverse=True)[:3]
                metrics_text += "Top central nodes:\n"
                for node, score in top_centrality:
                    node_type = subgraph.nodes[node].get('record_type', '')
                    metrics_text += f"- {node_type} ({score:.3f})\n"
            except:
                pass
                
            plt.figtext(0.02, 0.02, metrics_text, fontsize=8, 
                      bbox={"facecolor": "white", "alpha": 0.7, "pad": 5})
        
        # Set tight layout
        plt.tight_layout()
        
        # Save or return the plot
        if file_path:
            plt.savefig(file_path, format=format, bbox_inches='tight', dpi=100)
            plt.close()
            return None
        elif return_base64:
            buf = io.BytesIO()
            plt.savefig(buf, format=format, bbox_inches='tight', dpi=100)
            plt.close()
            buf.seek(0)
            img_base64 = base64.b64encode(buf.read()).decode('utf-8')
            return img_base64
        else:
            plt.close()
            return None
    
    def _visualize_with_plotly(
        self,
        subgraph: nx.DiGraph,
        include_parameters: bool,
        show_timestamps: bool,
        layout: str,
        highlight_critical_path: bool,
        include_metrics: bool,
        file_path: Optional[str],
        format: str,
        width: int,
        height: int,
        custom_colors: Optional[Dict[str, str]]
    ) -> Optional[Union[str, Dict[str, Any]]]:
        """
        Visualize provenance graph using plotly.
        
        Args:
            subgraph: Subgraph to visualize
            include_parameters: Whether to include operation parameters
            show_timestamps: Whether to show timestamps
            layout: Layout algorithm to use
            highlight_critical_path: Whether to highlight the critical path
            include_metrics: Whether to include metrics in the visualization
            file_path: Path to save the visualization
            format: Output format
            width: Width of the visualization
            height: Height of the visualization
            custom_colors: Custom colors for node types
            
        Returns:
            Optional[Union[str, Dict[str, Any]]]: HTML string or JSON dict if format is "html" or "json"
        """
        if not PLOTLY_AVAILABLE:
            return None
            
        import plotly.graph_objects as go
        
        # Define node colors based on record type
        default_colors = {
            "source": "#ADD8E6",  # lightblue
            "transformation": "#90EE90",  # lightgreen
            "merge": "#FFA500",  # orange
            "query": "#F08080",  # lightcoral
            "result": "#FFFF99",  # yellow
            "checkpoint": "#9370DB",  # purple
            "verification": "#00FFFF",  # cyan
            "annotation": "#FFC0CB",  # pink
            "model_training": "#20B2AA",  # lightseagreen
            "model_inference": "#87CEEB",  # lightskyblue
            "data_entity": "#D3D3D3"  # gray
        }
        
        # Override with custom colors if provided
        node_color_map = {**default_colors, **(custom_colors or {})}
        
        # Choose layout for positioning
        if layout == "hierarchical":
            pos = nx.multipartite_layout(subgraph, subset_key="depth")
        elif layout == "circular":
            pos = nx.circular_layout(subgraph)
        elif layout == "spectral":
            pos = nx.spectral_layout(subgraph)
        else:  # default to spring layout
            pos = nx.spring_layout(subgraph, k=0.2, iterations=50, seed=42)
        
        # Create node trace
        node_x = []
        node_y = []
        node_text = []
        node_colors = []
        node_sizes = []
        
        for node in subgraph.nodes():
            x, y = pos[node]
            node_x.append(x)
            node_y.append(y)
            
            # Color based on record type
            node_type = subgraph.nodes[node].get('record_type', '')
            color = node_color_map.get(node_type, "#FFFFFF")  # white default
            node_colors.append(color)
            
            # Size based on importance if metrics included
            if include_metrics:
                # Use degree as a simple measure of importance
                degree = subgraph.degree(node)
                size = 15 + (degree * 2)  # Scale size based on degree
            else:
                size = 15
            node_sizes.append(size)
            
            # Node text/hover info
            if node in self.records:
                record = self.records[node]
                text_parts = [f"Type: {node_type}", f"ID: {node}", f"Description: {record.description}"]
                
                if show_timestamps:
                    timestamp_str = datetime.datetime.fromtimestamp(record.timestamp).strftime('%Y-%m-%d %H:%M:%S')
                    text_parts.append(f"Time: {timestamp_str}")
                
                if hasattr(record, 'input_ids') and record.input_ids:
                    text_parts.append(f"Inputs: {', '.join(record.input_ids)}")
                
                if hasattr(record, 'output_ids') and record.output_ids:
                    text_parts.append(f"Outputs: {', '.join(record.output_ids)}")
                
                if include_parameters and hasattr(record, 'parameters') and record.parameters:
                    param_str = str(record.parameters)
                    text_parts.append(f"Parameters: {param_str}")
                    
                node_text.append("<br>".join(text_parts))
            else:
                node_text.append(f"Type: {node_type}<br>ID: {node}")
        
        node_trace = go.Scatter(
            x=node_x, y=node_y,
            mode='markers',
            hoverinfo='text',
            text=node_text,
            marker=dict(
                showscale=False,
                color=node_colors,
                size=node_sizes,
                line=dict(width=2, color='#888')
            )
        )
        
        # Create edge traces
        edge_traces = []
        
        # Define styles for different edge types
        edge_styles = {
            "input": {"color": "blue", "width": 2, "dash": "solid"},
            "output": {"color": "green", "width": 2, "dash": "solid"},
            "includes": {"color": "gray", "width": 1, "dash": "dash"},
            "produces": {"color": "red", "width": 2, "dash": "solid"},
            "checkpoint": {"color": "purple", "width": 1, "dash": "dot"},
            "verifies": {"color": "cyan", "width": 1, "dash": "dashdot"},
            "annotates": {"color": "pink", "width": 1, "dash": "dashdot"}
        }
        
        # Group edges by type
        edges_by_type = {}
        for u, v, data in subgraph.edges(data=True):
            edge_type = data.get("type", "default")
            if edge_type not in edges_by_type:
                edges_by_type[edge_type] = []
            edges_by_type[edge_type].append((u, v))
            
        # Create traces for each edge type
        for edge_type, edges in edges_by_type.items():
            style = edge_styles.get(edge_type, {"color": "black", "width": 1, "dash": "solid"})
            
            edge_x = []
            edge_y = []
            edge_text = []
            
            for edge in edges:
                x0, y0 = pos[edge[0]]
                x1, y1 = pos[edge[1]]
                
                # Add the starting point, ending point, and None to create a clean line
                edge_x.extend([x0, x1, None])
                edge_y.extend([y0, y1, None])
                edge_text.append(f"Type: {edge_type}<br>From: {edge[0]}<br>To: {edge[1]}")
                
            edge_trace = go.Scatter(
                x=edge_x, y=edge_y,
                line=dict(width=style["width"], color=style["color"], dash=style["dash"]),
                hoverinfo='text',
                text=edge_text,
                mode='lines'
            )
            
            edge_traces.append(edge_trace)
        
        # Add arrow annotations for directed edges
        annotations = []
        for u, v, data in subgraph.edges(data=True):
            edge_type = data.get("type", "default")
            style = edge_styles.get(edge_type, {"color": "black", "width": 1, "dash": "solid"})
            
            # Calculate the position for the arrow
            x0, y0 = pos[u]
            x1, y1 = pos[v]
            
            # Create arrow annotation
            annotations.append(
                dict(
                    ax=x0, ay=y0,
                    axref='x', ayref='y',
                    x=x1, y=y1,
                    xref='x', yref='y',
                    showarrow=True,
                    arrowhead=2,
                    arrowsize=1,
                    arrowwidth=style["width"],
                    arrowcolor=style["color"]
                )
            )
        
        # Create figure
        fig = go.Figure(data=[*edge_traces, node_trace],
                      layout=go.Layout(
                          title='Provenance Graph',
                          titlefont=dict(size=16),
                          showlegend=False,
                          hovermode='closest',
                          margin=dict(b=20, l=5, r=5, t=40),
                          annotations=annotations,
                          xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                          yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                          width=width,
                          height=height
                      )
                  )
        
        # Add legend
        for record_type, color in node_color_map.items():
            fig.add_trace(go.Scatter(
                x=[None], y=[None],
                mode='markers',
                marker=dict(size=10, color=color),
                showlegend=True,
                name=record_type
            ))
        
        # Add metrics if requested
        if include_metrics:
            metrics_text = "Graph Metrics:<br>"
            metrics_text += f"Nodes: {subgraph.number_of_nodes()}<br>"
            metrics_text += f"Edges: {subgraph.number_of_edges()}<br>"
            
            # Add centrality metrics for top nodes
            try:
                centrality = ProvenanceMetrics.calculate_centrality(subgraph)
                top_centrality = sorted(centrality.items(), key=lambda x: x[1], reverse=True)[:3]
                metrics_text += "Top central nodes:<br>"
                for node, score in top_centrality:
                    node_type = subgraph.nodes[node].get('record_type', '')
                    metrics_text += f"- {node_type} ({score:.3f})<br>"
            except:
                pass
                
            fig.add_annotation(
                x=0.01,
                y=0.01,
                xref="paper",
                yref="paper",
                text=metrics_text,
                showarrow=False,
                font=dict(size=10),
                align="left",
                bgcolor="white",
                bordercolor="black",
                borderwidth=1
            )
        
        # Save or return the visualization
        if file_path:
            if format == "html":
                fig.write_html(file_path)
            else:  # json
                with open(file_path, 'w') as f:
                    f.write(fig.to_json())
            return None
        else:
            if format == "html":
                return fig.to_html()
            else:  # json
                return json.loads(fig.to_json())
    
    def _visualize_with_dash(
        self,
        subgraph: nx.DiGraph,
        include_parameters: bool,
        show_timestamps: bool,
        layout: str,
        highlight_critical_path: bool,
        include_metrics: bool,
        file_path: Optional[str],
        width: int,
        height: int,
        custom_colors: Optional[Dict[str, str]]
    ) -> Optional[str]:
        """
        Visualize provenance graph using Dash with Cytoscape.
        
        Args:
            subgraph: Subgraph to visualize
            include_parameters: Whether to include operation parameters
            show_timestamps: Whether to show timestamps
            layout: Layout algorithm to use
            highlight_critical_path: Whether to highlight the critical path
            include_metrics: Whether to include metrics in the visualization
            file_path: Path to save the visualization
            width: Width of the visualization
            height: Height of the visualization
            custom_colors: Custom colors for node types
            
        Returns:
            Optional[str]: HTML string if successful
        """
        if not DASH_AVAILABLE:
            return None
            
        import dash
        from dash import dcc, html
        import dash_cytoscape as cyto
        
        # Register Cytoscape layout extensions
        cyto.load_extra_layouts()
        
        # Define node colors based on record type
        default_colors = {
            "source": "#ADD8E6",  # lightblue
            "transformation": "#90EE90",  # lightgreen
            "merge": "#FFA500",  # orange
            "query": "#F08080",  # lightcoral
            "result": "#FFFF99",  # yellow
            "checkpoint": "#9370DB",  # purple
            "verification": "#00FFFF",  # cyan
            "annotation": "#FFC0CB",  # pink
            "model_training": "#20B2AA",  # lightseagreen
            "model_inference": "#87CEEB",  # lightskyblue
            "data_entity": "#D3D3D3"  # gray
        }
        
        # Override with custom colors if provided
        node_color_map = {**default_colors, **(custom_colors or {})}
        
        # Map NetworkX layout to Cytoscape layout
        if layout == "hierarchical":
            cyto_layout = {"name": "dagre", "rankDir": "TB"}
        elif layout == "circular":
            cyto_layout = {"name": "circle"}
        elif layout == "spectral":
            cyto_layout = {"name": "cose"}
        else:  # spring layout
            cyto_layout = {"name": "cose"}
        
        # Prepare nodes and edges for Cytoscape
        cyto_nodes = []
        for node in subgraph.nodes():
            node_type = subgraph.nodes[node].get('record_type', '')
            description = subgraph.nodes[node].get('description', '')
            
            node_data = {
                "id": str(node),
                "label": description[:20] if description else str(node),
                "type": node_type
            }
            
            # Add timestamp if requested
            if show_timestamps and node in self.records:
                record = self.records[node]
                node_data["timestamp"] = datetime.datetime.fromtimestamp(record.timestamp).strftime('%Y-%m-%d %H:%M:%S')
            
            # Add parameters if requested
            if include_parameters and node in self.records:
                record = self.records[node]
                if hasattr(record, 'parameters') and record.parameters:
                    node_data["parameters"] = str(record.parameters)
            
            cyto_nodes.append({
                "data": node_data,
                "style": {
                    "background-color": node_color_map.get(node_type, "#FFFFFF"),
                    "label": "data(label)",
                    "width": 30,
                    "height": 30
                }
            })
        
        # Prepare edges
        cyto_edges = []
        edge_styles = {
            "input": {"line-color": "blue", "width": 2, "line-style": "solid"},
            "output": {"line-color": "green", "width": 2, "line-style": "solid"},
            "includes": {"line-color": "gray", "width": 1, "line-style": "dashed"},
            "produces": {"line-color": "red", "width": 2, "line-style": "solid"},
            "checkpoint": {"line-color": "purple", "width": 1, "line-style": "dotted"},
            "verifies": {"line-color": "cyan", "width": 1, "line-style": "dashed"},
            "annotates": {"line-color": "pink", "width": 1, "line-style": "dashed"}
        }
        
        for u, v, data in subgraph.edges(data=True):
            edge_type = data.get("type", "default")
            style = edge_styles.get(edge_type, {"line-color": "black", "width": 1, "line-style": "solid"})
            
            cyto_edges.append({
                "data": {
                    "source": str(u),
                    "target": str(v),
                    "type": edge_type
                },
                "style": style
            })
        
        # Create Dash app
        app = dash.Dash(__name__)
        
        # Define the layout
        app.layout = html.Div([
            html.H1("Provenance Graph Visualization", style={"textAlign": "center"}),
            html.Div([
                cyto.Cytoscape(
                    id='provenance-graph',
                    layout=cyto_layout,
                    style={'width': width, 'height': height},
                    elements=cyto_nodes + cyto_edges,
                    stylesheet=[
                        # Group selectors
                        {
                            'selector': 'node',
                            'style': {
                                'content': 'data(label)',
                                'text-opacity': 0.8,
                                'text-valign': 'center',
                                'text-halign': 'center',
                                'font-size': '12px'
                            }
                        },
                        {
                            'selector': 'edge',
                            'style': {
                                'width': 'data(width)',
                                'target-arrow-shape': 'triangle',
                                'curve-style': 'bezier'
                            }
                        }
                    ]
                )
            ], style={"display": "flex", "justifyContent": "center"}),
            
            # Add legend
            html.Div([
                html.H3("Legend"),
                html.Div([
                    html.Div([
                        html.Div(style={
                            "width": "20px", 
                            "height": "20px", 
                            "backgroundColor": color,
                            "display": "inline-block",
                            "marginRight": "10px"
                        }),
                        html.Span(record_type)
                    ], style={"marginBottom": "5px"})
                    for record_type, color in node_color_map.items()
                ])
            ], style={"margin": "20px"})
        ])
        
        # Generate HTML output
        if file_path:
            # Save as a standalone HTML file
            app_html = app.index_string
            with open(file_path, 'w') as f:
                f.write(app_html)
            return None
        else:
            # Return the HTML string
            return app.index_string


def _provenance_ipld_example():
    """
    Example demonstrating the enhanced data provenance tracking with IPLD integration.
    
    This function shows how to:
    1. Create a provenance manager with enhanced IPLD storage
    2. Record provenance for data processing operations
    3. Use advanced graph traversal for lineage tracking
    4. Export/import provenance with CAR files
    5. Perform efficient incremental loading of large provenance graphs
    """
    import os
    import time
    import tempfile
    import numpy as np
    
    # Create provenance manager with IPLD storage enabled
    temp_dir = tempfile.mkdtemp()
    manager = EnhancedProvenanceManager(
        storage_path=temp_dir,
        enable_ipld_storage=True,
        enable_crypto_verification=True,
        default_agent_id="example_agent"
    )
    
    # Record source data provenance
    source_id = manager.record_source(
        data_id="raw_data",
        source_type="synthetic",
        source_uri="memory://raw_data",
        format="numpy",
        description="Raw synthetic data for example"
    )
    
    # Record transformation
    transform_id = manager.record_transformation(
        input_ids=[source_id],
        output_id="processed_data",
        operation="normalization",
        parameters={"method": "min-max", "axis": 0},
        description="Normalize raw data to [0,1] range"
    )
    
    # Record another transformation
    transform2_id = manager.record_transformation(
        input_ids=[transform_id],
        output_id="model_input",
        operation="split",
        parameters={"test_size": 0.2, "random_state": 42},
        description="Split data into train/test sets"
    )
    
    # Record model training
    training_record = manager.add_record(
        VerificationRecord(
            id=str(uuid.uuid4()),
            record_type="verification",
            timestamp=time.time(),
            agent_id=manager.default_agent_id,
            description="Validate processed data",
            data_id="processed_data",
            verification_type="schema",
            schema={"type": "numeric", "range": [0, 1]},
            validation_rules=[{"rule": "range", "min": 0, "max": 1}],
            pass_count=950,
            fail_count=50,
            error_samples=[{"value": 1.2, "reason": "above range"}],
            is_valid=True
        )
    )
    
    # Get lineage graph using enhanced traversal
    lineage = manager.get_lineage_graph("model_input", depth=3)
    print(f"Basic lineage graph has {len(lineage.nodes)} nodes and {len(lineage.edges)} edges")
    
    # Use advanced traversal with direction control
    upstream = manager.traverse_provenance(
        record_id="model_input",
        max_depth=2,
        direction="in"  # Only traverse upstream
    )
    print(f"Upstream traversal has {len(upstream.nodes)} nodes and {len(upstream.edges)} edges")
    
    # Filter by relation type
    filtered = manager.traverse_provenance(
        record_id="processed_data",
        max_depth=3,
        relation_filter=["verification"]  # Only follow verification links
    )
    print(f"Relation-filtered traversal has {len(filtered.nodes)} nodes")
    
    # Export to CAR file
    car_path = os.path.join(temp_dir, "provenance.car")
    cid = manager.export_to_car(car_path)
    print(f"Exported provenance to CAR file with root CID: {cid}")
    
    # Create a new manager and import from CAR
    new_manager = EnhancedProvenanceManager(
        storage_path=os.path.join(temp_dir, "import"),
        enable_ipld_storage=True
    )
    success = new_manager.import_from_car(car_path)
    print(f"Imported provenance from CAR file: {success}")
    
    # Incremental loading with time filter
    recent_records = new_manager.incremental_load_provenance({
        "time_start": time.time() - 3600,  # Last hour
        "record_types": ["transformation"]
    })
    print(f"Incrementally loaded {len(recent_records.nodes)} recent transformation records")
    
    return manager


if __name__ == "__main__":
    # Run the example
    _provenance_ipld_example()