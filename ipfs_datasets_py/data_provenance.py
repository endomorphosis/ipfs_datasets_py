"""
Data Provenance Tracking Module with Detailed Lineage.

This module provides comprehensive mechanisms for tracking the detailed lineage
of data as it flows through the IPFS Datasets Python system. It records the
complete history of transformations, operations, and manipulations that data
undergoes from its original sources to final outputs.

Key features:
- Detailed transformation tracking with operation parameters
- Source attribution with data origin recording
- Multi-level lineage graphs with directed edges
- Immutable history with CID-based chain of operations
- Provenance visualization with graph export
- Audit trail generation for compliance and reproducibility
- Integration with IPLD for content-addressable provenance
- Support for distributed data transformations
"""

import json
import uuid
import time
import hashlib
import datetime
from typing import Dict, List, Any, Optional, Union, Set, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import networkx as nx
import matplotlib.pyplot as plt
import io
import base64

# Define provenance record types
class ProvenanceRecordType(Enum):
    """Types of records in the provenance tracking system.

    This enumeration defines the different types of operations and events that can be
    tracked in a data provenance system. Each type represents a specific kind of
    data processing or handling operation.

    Attributes:
        SOURCE: Represents the original data source or initial data ingestion point.
        TRANSFORMATION: Represents data transformation operations such as cleaning,
            normalization, or format conversion.
        MERGE: Represents operations that combine multiple data sources or datasets
            into a single dataset.
        FILTER: Represents operations that filter or subset data based on specific
            criteria or conditions.
        EXPORT: Represents operations that export data to external formats or systems.
        IMPORT: Represents operations that import data from external sources or formats.
        QUERY: Represents data query operations or database lookups.
        RESULT: Represents the outcome or result of a query, computation, or operation.
        CHECKPOINT: Represents checkpoints or snapshots of data state for recovery
            or versioning purposes.
    """
    SOURCE = "source"                  # Original data source
    TRANSFORMATION = "transformation"  # Data transformation
    MERGE = "merge"                    # Merging multiple data sources
    FILTER = "filter"                  # Filtering data
    EXPORT = "export"                  # Exporting data to another format
    IMPORT = "import"                  # Importing data from another format
    QUERY = "query"                    # Querying data
    RESULT = "result"                  # Result of a query or operation
    CHECKPOINT = "checkpoint"          # Checkpoint/snapshot of data state


@dataclass
class ProvenanceRecord:
    """
    Base class for provenance records.
    
    This class represents a fundamental unit of provenance information, tracking
    the essential details of data operations and transformations within the system.
    Each record captures metadata about what happened, when it happened, who or
    what performed the operation, and how different data entities are related.
    
    Attributes:
        id: Unique identifier for this provenance record
        record_type: Type of provenance operation (source, transformation, etc.)
        timestamp: When this record was created (Unix timestamp)
        agent_id: Identifier of the agent (user, system, tool) that performed the operation
        description: Human-readable description of what this record represents
        metadata: Additional key-value metadata for extensibility
        input_ids: List of data entity IDs that were inputs to this operation
        output_ids: List of data entity IDs that were outputs from this operation
        parameters: Operation-specific parameters and configuration
        cid: Content identifier for IPFS/IPLD storage integration
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    record_type: ProvenanceRecordType = ProvenanceRecordType.TRANSFORMATION
    timestamp: float = field(default_factory=time.time)
    agent_id: Optional[str] = None
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    input_ids: List[str] = field(default_factory=list)
    output_ids: List[str] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    cid: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert record to dictionary representation."""
        result = asdict(self)
        result['record_type'] = self.record_type.value
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProvenanceRecord':
        """Create record from dictionary representation."""
        # Convert string record type to enum
        if 'record_type' in data and isinstance(data['record_type'], str):
            data['record_type'] = ProvenanceRecordType(data['record_type'])
        return cls(**data)


@dataclass
class SourceRecord(ProvenanceRecord):
    """Record for an original data source."""
    record_type: ProvenanceRecordType = ProvenanceRecordType.SOURCE
    source_type: str = ""  # E.g., "file", "database", "api", "web"
    location: str = ""     # Source location
    format: str = ""       # Data format
    size: Optional[int] = None  # Size in bytes if known
    hash: Optional[str] = None  # Content hash if available


@dataclass
class TransformationRecord(ProvenanceRecord):
    """Record for a data transformation operation."""
    record_type: ProvenanceRecordType = ProvenanceRecordType.TRANSFORMATION
    transformation_type: str = ""  # Type of transformation
    tool: str = ""                 # Tool used for transformation
    version: str = ""              # Tool version
    parameters: Dict[str, Any] = field(default_factory=dict)  # Transformation parameters
    execution_time: Optional[float] = None  # Execution time in seconds
    success: bool = True  # Whether transformation succeeded
    error_message: Optional[str] = None  # Error message if transformation failed


@dataclass
class MergeRecord(ProvenanceRecord):
    """Record for merging multiple data sources."""
    record_type: ProvenanceRecordType = ProvenanceRecordType.MERGE
    merge_type: str = ""  # Type of merge (e.g., "union", "join", "concatenate")
    merge_keys: Optional[List[str]] = None  # Keys used for joining if applicable
    merge_strategy: str = ""  # Strategy for conflict resolution


@dataclass
class QueryRecord(ProvenanceRecord):
    """Record for a query operation."""
    record_type: ProvenanceRecordType = ProvenanceRecordType.QUERY
    query_type: str = ""  # Type of query
    query_text: str = ""  # Raw query text or representation
    query_parameters: Dict[str, Any] = field(default_factory=dict)  # Query parameters
    result_count: Optional[int] = None  # Number of results returned
    execution_time: Optional[float] = None  # Execution time in seconds


@dataclass
class ResultRecord(ProvenanceRecord):
    """Record for an operation result."""
    record_type: ProvenanceRecordType = ProvenanceRecordType.RESULT
    result_type: str = ""  # Type of result
    size: Optional[int] = None  # Size of result in bytes if applicable
    record_count: Optional[int] = None  # Number of records in result if applicable
    fields: Optional[List[str]] = None  # Fields in result if applicable
    sample: Optional[str] = None  # Sample of result if applicable
    visualization: Optional[str] = None  # Base64-encoded visualization if applicable


class ProvenanceManager:
    """
    Manages data provenance tracking with detailed lineage.

    This class provides the main interface for tracking provenance
    throughout the data processing lifecycle.
    """

    def __init__(
        self,
        storage_path: Optional[str] = None,
        enable_ipld_storage: bool = False,
        default_agent_id: Optional[str] = None,
        tracking_level: str = "detailed"  # "minimal", "standard", "detailed"
    ):
        """
        Initialize the provenance manager.

        Args:
            storage_path: Path to store provenance data, None for in-memory only
            enable_ipld_storage: Whether to use IPLD for provenance storage
            default_agent_id: Default agent ID for provenance records
            tracking_level: Level of detail for provenance tracking
        """
        self.storage_path = storage_path
        self.enable_ipld_storage = enable_ipld_storage
        self.default_agent_id = default_agent_id or str(uuid.uuid4())
        self.tracking_level = tracking_level

        # Dictionary to store provenance records
        self.records: Dict[str, ProvenanceRecord] = {}

        # Graph representation of the provenance
        self.graph = nx.DiGraph()

        # Cache of data entity IDs to their latest record IDs
        self.entity_latest_record: Dict[str, str] = {}

        # Keep track of current operations for nested tracking
        self.current_operations: List[str] = []

    def record_source(
        self,
        data_id: str,
        source_type: str,
        location: str,
        format: str = "",
        description: str = "",
        size: Optional[int] = None,
        hash: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Record an original data source.

        Args:
            data_id: Identifier for the data entity
            source_type: Type of source (file, database, etc.)
            location: Source location (path, URL, etc.)
            format: Data format
            description: Description of the source
            size: Size in bytes if known
            hash: Content hash if available
            metadata: Additional metadata

        Returns:
            str: ID of the created provenance record
        """
        metadata = metadata or {}

        record = SourceRecord(
            record_type=ProvenanceRecordType.SOURCE,
            agent_id=self.default_agent_id,
            description=description,
            metadata=metadata,
            output_ids=[data_id],
            source_type=source_type,
            location=location,
            format=format,
            size=size,
            hash=hash
        )

        # Store the record
        self.records[record.id] = record

        # Update the entity's latest record
        self.entity_latest_record[data_id] = record.id

        # Add to provenance graph
        self.graph.add_node(record.id,
                            record_type=record.record_type.value,
                            description=description,
                            timestamp=record.timestamp,
                            data_id=data_id)

        # If this is part of a current operation, link it
        if self.current_operations:
            parent_id = self.current_operations[-1]
            self.graph.add_edge(parent_id, record.id, type="includes")

        return record.id

    def begin_transformation(
        self,
        description: str,
        transformation_type: str,
        tool: str = "",
        version: str = "",
        input_ids: Optional[List[str]] = None,
        parameters: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Begin tracking a data transformation.

        Args:
            description: Description of the transformation
            transformation_type: Type of transformation
            tool: Tool used for transformation
            version: Tool version
            input_ids: IDs of input data entities
            parameters: Transformation parameters
            metadata: Additional metadata

        Returns:
            str: ID of the created transformation record
        """
        input_ids = input_ids or []
        parameters = parameters or {}
        metadata = metadata or {}

        # Create a new transformation record
        record = TransformationRecord(
            record_type=ProvenanceRecordType.TRANSFORMATION,
            agent_id=self.default_agent_id,
            description=description,
            metadata=metadata,
            input_ids=input_ids,
            transformation_type=transformation_type,
            tool=tool,
            version=version,
            parameters=parameters,
            execution_time=None  # Will be set when transformation ends
        )

        # Store the record
        self.records[record.id] = record

        # Add to provenance graph
        self.graph.add_node(record.id,
                            record_type=record.record_type.value,
                            description=description,
                            timestamp=record.timestamp)

        # Link to input data entities
        input_record_ids = []
        for input_id in input_ids:
            if input_id in self.entity_latest_record:
                input_record_id = self.entity_latest_record[input_id]
                input_record_ids.append(input_record_id)
                self.graph.add_edge(input_record_id, record.id, type="input")

        # Add to current operations stack
        self.current_operations.append(record.id)

        return record.id

    def end_transformation(
        self,
        transformation_id: str,
        output_ids: Optional[List[str]] = None,
        success: bool = True,
        error_message: Optional[str] = None
    ) -> str:
        """
        End tracking a data transformation.

        Args:
            transformation_id: ID of the transformation record
            output_ids: IDs of output data entities
            success: Whether transformation succeeded
            error_message: Error message if transformation failed

        Returns:
            str: ID of the updated transformation record
        """
        output_ids = output_ids or []

        # Get the transformation record
        if transformation_id not in self.records:
            raise ValueError(f"Transformation record {transformation_id} not found")

        record = self.records[transformation_id]
        if not isinstance(record, TransformationRecord):
            raise TypeError(f"Record {transformation_id} is not a TransformationRecord")

        # Update the record
        record.output_ids = output_ids
        record.success = success
        record.error_message = error_message
        record.execution_time = time.time() - record.timestamp

        # Link to output data entities in the graph
        for output_id in output_ids:
            self.entity_latest_record[output_id] = transformation_id

            # Add data entity node if it doesn't exist
            if not self.graph.has_node(output_id):
                self.graph.add_node(output_id,
                                  record_type="data_entity",
                                  description=f"Data entity {output_id}")

            # Link transformation to output
            self.graph.add_edge(transformation_id, output_id, type="output")

        # Remove from current operations stack
        if self.current_operations and self.current_operations[-1] == transformation_id:
            self.current_operations.pop()

        return transformation_id

    def record_merge(
        self,
        input_ids: List[str],
        output_id: str,
        merge_type: str,
        description: str = "",
        merge_keys: Optional[List[str]] = None,
        merge_strategy: str = "default",
        parameters: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Record a data merge operation.

        Args:
            input_ids: IDs of input data entities
            output_id: ID of output data entity
            merge_type: Type of merge
            description: Description of the merge
            merge_keys: Keys used for joining if applicable
            merge_strategy: Strategy for conflict resolution
            parameters: Merge parameters
            metadata: Additional metadata

        Returns:
            str: ID of the created merge record
        """
        parameters = parameters or {}
        metadata = metadata or {}

        # Create a new merge record
        record = MergeRecord(
            record_type=ProvenanceRecordType.MERGE,
            agent_id=self.default_agent_id,
            description=description,
            metadata=metadata,
            input_ids=input_ids,
            output_ids=[output_id],
            parameters=parameters,
            merge_type=merge_type,
            merge_keys=merge_keys,
            merge_strategy=merge_strategy
        )

        # Store the record
        self.records[record.id] = record

        # Update the entity's latest record
        self.entity_latest_record[output_id] = record.id

        # Add to provenance graph
        self.graph.add_node(record.id,
                          record_type=record.record_type.value,
                          description=description,
                          timestamp=record.timestamp)

        # Link to input data entities
        for input_id in input_ids:
            if input_id in self.entity_latest_record:
                input_record_id = self.entity_latest_record[input_id]
                self.graph.add_edge(input_record_id, record.id, type="input")

        # Link to output data entity
        self.graph.add_edge(record.id, output_id, type="output")

        return record.id

    def record_query(
        self,
        input_ids: List[str],
        query_type: str,
        query_text: str,
        description: str = "",
        query_parameters: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Record a data query operation.

        Args:
            input_ids: IDs of input data entities
            query_type: Type of query
            query_text: Raw query text or representation
            description: Description of the query
            query_parameters: Query parameters
            metadata: Additional metadata

        Returns:
            str: ID of the created query record
        """
        query_parameters = query_parameters or {}
        metadata = metadata or {}

        # Start timing the query
        start_time = time.time()

        # Create a new query record
        record = QueryRecord(
            record_type=ProvenanceRecordType.QUERY,
            agent_id=self.default_agent_id,
            description=description,
            metadata=metadata,
            input_ids=input_ids,
            query_type=query_type,
            query_text=query_text,
            query_parameters=query_parameters
        )

        # Store the record
        self.records[record.id] = record

        # Add to provenance graph
        self.graph.add_node(record.id,
                          record_type=record.record_type.value,
                          description=description,
                          timestamp=record.timestamp)

        # Link to input data entities
        for input_id in input_ids:
            if input_id in self.entity_latest_record:
                input_record_id = self.entity_latest_record[input_id]
                self.graph.add_edge(input_record_id, record.id, type="input")

        # If this is part of a current operation, link it
        if self.current_operations:
            parent_id = self.current_operations[-1]
            self.graph.add_edge(parent_id, record.id, type="includes")

        # Add to current operations stack
        self.current_operations.append(record.id)

        return record.id

    def record_query_result(
        self,
        query_id: str,
        output_id: str,
        result_count: Optional[int] = None,
        result_type: str = "",
        size: Optional[int] = None,
        fields: Optional[List[str]] = None,
        sample: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Record the result of a query operation.

        Args:
            query_id: ID of the query record
            output_id: ID of output data entity
            result_count: Number of results returned
            result_type: Type of result
            size: Size of result in bytes if applicable
            fields: Fields in result if applicable
            sample: Sample of result if applicable
            metadata: Additional metadata

        Returns:
            str: ID of the created result record
        """
        metadata = metadata or {}

        # Get the query record
        if query_id not in self.records:
            raise ValueError(f"Query record {query_id} not found")

        query_record = self.records[query_id]
        if not isinstance(query_record, QueryRecord):
            raise TypeError(f"Record {query_id} is not a QueryRecord")

        # Update the query record with execution time and result count
        query_record.execution_time = time.time() - query_record.timestamp
        query_record.result_count = result_count
        query_record.output_ids = [output_id]

        # Create a new result record
        result_record = ResultRecord(
            record_type=ProvenanceRecordType.RESULT,
            agent_id=self.default_agent_id,
            description=f"Result of query {query_id}",
            metadata=metadata,
            input_ids=[query_id],
            output_ids=[output_id],
            result_type=result_type,
            size=size,
            record_count=result_count,
            fields=fields,
            sample=sample
        )

        # Store the result record
        self.records[result_record.id] = result_record

        # Update the entity's latest record
        self.entity_latest_record[output_id] = result_record.id

        # Add to provenance graph
        self.graph.add_node(result_record.id,
                          record_type=result_record.record_type.value,
                          description=result_record.description,
                          timestamp=result_record.timestamp)

        # Link query to result
        self.graph.add_edge(query_id, result_record.id, type="produces")

        # Link result to output data entity
        self.graph.add_edge(result_record.id, output_id, type="output")

        # Remove query from current operations stack
        if self.current_operations and self.current_operations[-1] == query_id:
            self.current_operations.pop()

        return result_record.id

    def record_checkpoint(
        self,
        data_id: str,
        description: str = "",
        checkpoint_type: str = "snapshot",
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Record a checkpoint/snapshot of a data entity.

        Args:
            data_id: ID of the data entity
            description: Description of the checkpoint
            checkpoint_type: Type of checkpoint
            metadata: Additional metadata

        Returns:
            str: ID of the created checkpoint record
        """
        metadata = metadata or {}

        # Create a new checkpoint record
        record = ProvenanceRecord(
            record_type=ProvenanceRecordType.CHECKPOINT,
            agent_id=self.default_agent_id,
            description=description,
            metadata=metadata,
            input_ids=[data_id],
            output_ids=[data_id],
            parameters={"checkpoint_type": checkpoint_type}
        )

        # Store the record
        self.records[record.id] = record

        # Add to provenance graph
        self.graph.add_node(record.id,
                          record_type=record.record_type.value,
                          description=description,
                          timestamp=record.timestamp)

        # Link to data entity
        if data_id in self.entity_latest_record:
            input_record_id = self.entity_latest_record[data_id]
            self.graph.add_edge(input_record_id, record.id, type="checkpoint")

        # Update the entity's latest record
        self.entity_latest_record[data_id] = record.id

        return record.id

    def export_provenance_to_dict(self) -> Dict[str, Any]:
        """
        Export all provenance records as a dictionary.

        Returns:
            Dict: Provenance records and metadata
        """
        records_dict = {record_id: record.to_dict() for record_id, record in self.records.items()}

        return {
            "metadata": {
                "created_at": datetime.datetime.now().isoformat(),
                "agent_id": self.default_agent_id,
                "tracking_level": self.tracking_level,
                "record_count": len(records_dict)
            },
            "records": records_dict,
            "entity_latest_record": self.entity_latest_record
        }

    def export_provenance_to_json(self, file_path: Optional[str] = None) -> Optional[str]:
        """
        Export all provenance records as JSON.

        Args:
            file_path: Path to write JSON file, None to return JSON string

        Returns:
            str: JSON string if file_path is None
        """
        provenance_dict = self.export_provenance_to_dict()
        json_str = json.dumps(provenance_dict, indent=2)

        if file_path:
            with open(file_path, 'w') as f:
                f.write(json_str)
            return None
        else:
            return json_str

    def import_provenance_from_dict(self, provenance_dict: Dict[str, Any]) -> None:
        """
        Import provenance records from a dictionary.

        Args:
            provenance_dict: Dictionary containing provenance records
        """
        # Import metadata if available
        if "metadata" in provenance_dict:
            metadata = provenance_dict["metadata"]
            if "agent_id" in metadata:
                self.default_agent_id = metadata["agent_id"]
            if "tracking_level" in metadata:
                self.tracking_level = metadata["tracking_level"]

        # Import records
        if "records" in provenance_dict:
            for record_id, record_dict in provenance_dict["records"].items():
                record_type = record_dict.get("record_type")

                if record_type == ProvenanceRecordType.SOURCE.value:
                    record = SourceRecord.from_dict(record_dict)
                elif record_type == ProvenanceRecordType.TRANSFORMATION.value:
                    record = TransformationRecord.from_dict(record_dict)
                elif record_type == ProvenanceRecordType.MERGE.value:
                    record = MergeRecord.from_dict(record_dict)
                elif record_type == ProvenanceRecordType.QUERY.value:
                    record = QueryRecord.from_dict(record_dict)
                elif record_type == ProvenanceRecordType.RESULT.value:
                    record = ResultRecord.from_dict(record_dict)
                else:
                    record = ProvenanceRecord.from_dict(record_dict)

                self.records[record_id] = record

                # Add to provenance graph
                self.graph.add_node(record_id,
                                  record_type=record.record_type.value,
                                  description=record.description,
                                  timestamp=record.timestamp)

                # Link to input and output entities
                for input_id in record.input_ids:
                    # Check if input_id is a record ID
                    if input_id in self.records:
                        self.graph.add_edge(input_id, record_id, type="input")
                    # Otherwise, it's a data entity ID
                    else:
                        # Link to the latest record for this entity if available
                        if input_id in self.entity_latest_record:
                            input_record_id = self.entity_latest_record[input_id]
                            self.graph.add_edge(input_record_id, record_id, type="input")

                for output_id in record.output_ids:
                    # Check if output_id is a record ID
                    if output_id in self.records:
                        self.graph.add_edge(record_id, output_id, type="output")
                    # Otherwise, it's a data entity ID
                    else:
                        # Add data entity node if it doesn't exist
                        if not self.graph.has_node(output_id):
                            self.graph.add_node(output_id,
                                              record_type="data_entity",
                                              description=f"Data entity {output_id}")

                        # Link record to output
                        self.graph.add_edge(record_id, output_id, type="output")

        # Import entity latest records
        if "entity_latest_record" in provenance_dict:
            self.entity_latest_record.update(provenance_dict["entity_latest_record"])

    def import_provenance_from_json(self, json_str: str) -> None:
        """
        Import provenance records from a JSON string.

        Args:
            json_str: JSON string containing provenance records
        """
        provenance_dict = json.loads(json_str)
        self.import_provenance_from_dict(provenance_dict)

    def import_provenance_from_file(self, file_path: str) -> None:
        """
        Import provenance records from a JSON file.

        Args:
            file_path: Path to JSON file
        """
        with open(file_path, 'r') as f:
            json_str = f.read()
        self.import_provenance_from_json(json_str)

    def get_data_lineage(self, data_id: str, max_depth: int = 10) -> Dict[str, Any]:
        """
        Get the lineage of a data entity.

        Args:
            data_id: ID of the data entity
            max_depth: Maximum depth to trace back

        Returns:
            Dict: Lineage information
        """
        # Check if data_id is a record ID or data entity ID
        if data_id in self.records:
            record_id = data_id
        elif data_id in self.entity_latest_record:
            record_id = self.entity_latest_record[data_id]
        else:
            return {"error": f"Data ID {data_id} not found"}

        # Trace back through the graph
        lineage = {
            "data_id": data_id,
            "record_id": record_id,
            "record": self.records[record_id].to_dict(),
            "parents": [],
            "depth": 0
        }

        # Helper function for recursive tracing
        def trace_parents(node_id, current_lineage, current_depth):
            if current_depth >= max_depth:
                return

            # Find parent nodes in the graph
            parents = []
            for parent_id in self.graph.predecessors(node_id):
                parent_record = self.records.get(parent_id)
                if not parent_record:
                    continue

                parent_info = {
                    "record_id": parent_id,
                    "record": parent_record.to_dict(),
                    "parents": [],
                    "depth": current_depth + 1
                }

                # Recursively trace parents
                trace_parents(parent_id, parent_info, current_depth + 1)

                parents.append(parent_info)

            current_lineage["parents"] = parents

        # Start tracing from the record
        trace_parents(record_id, lineage, 0)

        return lineage

    def visualize_provenance(
        self,
        data_ids: Optional[List[str]] = None,
        max_depth: int = 5,
        include_parameters: bool = False,
        show_timestamps: bool = True,
        file_path: Optional[str] = None,
        return_base64: bool = False
    ) -> Optional[str]:
        """
        Visualize the provenance graph for specified data entities.

        Args:
            data_ids: List of data entity IDs to visualize, None for all
            max_depth: Maximum depth to trace back
            include_parameters: Whether to include operation parameters
            show_timestamps: Whether to show timestamps
            file_path: Path to save the visualization
            return_base64: Whether to return the image as base64

        Returns:
            str: Base64-encoded image if return_base64 is True
        """
        import matplotlib
        matplotlib.use('Agg')  # Use non-interactive backend

        # Create a subgraph for visualization
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

        # Set up the plot
        plt.figure(figsize=(12, 8))
        pos = nx.spring_layout(subgraph, seed=42)

        # Define node colors based on record type
        node_colors = []
        for node in subgraph.nodes():
            node_type = subgraph.nodes[node].get('record_type', '')
            if node_type == ProvenanceRecordType.SOURCE.value:
                color = 'lightblue'
            elif node_type == ProvenanceRecordType.TRANSFORMATION.value:
                color = 'lightgreen'
            elif node_type == ProvenanceRecordType.MERGE.value:
                color = 'orange'
            elif node_type == ProvenanceRecordType.QUERY.value:
                color = 'lightcoral'
            elif node_type == ProvenanceRecordType.RESULT.value:
                color = 'yellow'
            elif node_type == ProvenanceRecordType.CHECKPOINT.value:
                color = 'purple'
            elif node_type == 'data_entity':
                color = 'gray'
            else:
                color = 'white'
            node_colors.append(color)

        # Draw nodes
        nx.draw_networkx_nodes(subgraph, pos, node_color=node_colors, node_size=500, alpha=0.8)

        # Draw edges
        nx.draw_networkx_edges(subgraph, pos, arrows=True)

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
                if show_timestamps:
                    timestamp_str = f"\n{datetime.datetime.fromtimestamp(record.timestamp).strftime('%Y-%m-%d %H:%M:%S')}"
                else:
                    timestamp_str = ""

                if include_parameters and hasattr(record, 'parameters') and record.parameters:
                    param_str = f"\nParams: {str(record.parameters)[:20]}..."
                else:
                    param_str = ""

                label = f"{node_type}:\n{description[:20]}{timestamp_str}{param_str}"
            else:
                label = f"{node_type}:\n{description[:20]}"

            node_labels[node] = label

        # Draw node labels
        nx.draw_networkx_labels(subgraph, pos, labels=node_labels, font_size=8, font_family='sans-serif')

        # Set plot title
        if data_ids:
            plt.title(f"Provenance for {', '.join(data_ids[:3])}{' and others' if len(data_ids) > 3 else ''}")
        else:
            plt.title("Full Provenance Graph")

        # Add a legend
        legend_elements = [
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='lightblue', markersize=10, label='Source'),
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='lightgreen', markersize=10, label='Transformation'),
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='orange', markersize=10, label='Merge'),
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='lightcoral', markersize=10, label='Query'),
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='yellow', markersize=10, label='Result'),
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='purple', markersize=10, label='Checkpoint'),
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='gray', markersize=10, label='Data Entity')
        ]
        plt.legend(handles=legend_elements, loc='upper right')

        # Save or return the plot
        if file_path:
            plt.savefig(file_path, bbox_inches='tight')
            plt.close()
            return None
        elif return_base64:
            buf = io.BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight')
            plt.close()
            buf.seek(0)
            img_base64 = base64.b64encode(buf.read()).decode('utf-8')
            return img_base64
        else:
            plt.close()
            return None

    def generate_audit_report(
        self,
        data_ids: Optional[List[str]] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        agent_id: Optional[str] = None,
        operation_types: Optional[List[str]] = None,
        include_parameters: bool = False,
        format: str = "text"  # "text", "html", "json", "md"
    ) -> str:
        """
        Generate an audit report for specified data entities.

        Args:
            data_ids: List of data entity IDs to include, None for all
            start_time: Start time for filtering records
            end_time: End time for filtering records
            agent_id: Agent ID for filtering records
            operation_types: List of operation types to include
            include_parameters: Whether to include operation parameters
            format: Output format

        Returns:
            str: Audit report in the specified format
        """
        # Filter records based on parameters
        filtered_records = {}

        for record_id, record in self.records.items():
            # Filter by data IDs
            if data_ids:
                if not (set(record.input_ids).intersection(data_ids) or
                        set(record.output_ids).intersection(data_ids)):
                    continue

            # Filter by time range
            if start_time and record.timestamp < start_time:
                continue
            if end_time and record.timestamp > end_time:
                continue

            # Filter by agent ID
            if agent_id and record.agent_id != agent_id:
                continue

            # Filter by operation type
            if operation_types and record.record_type.value not in operation_types:
                continue

            # Add to filtered records
            filtered_records[record_id] = record

        # Sort records by timestamp
        sorted_records = sorted(
            filtered_records.values(),
            key=lambda r: r.timestamp
        )

        # Generate report based on format
        if format == "json":
            return self._generate_json_report(sorted_records, include_parameters)
        elif format == "html":
            return self._generate_html_report(sorted_records, include_parameters)
        elif format == "md":
            return self._generate_markdown_report(sorted_records, include_parameters)
        else:  # Default to text
            return self._generate_text_report(sorted_records, include_parameters)

    def _generate_text_report(
        self,
        records: List[ProvenanceRecord],
        include_parameters: bool
    ) -> str:
        """Generate a text audit report."""
        lines = ["# Data Provenance Audit Report", ""]
        lines.append(f"Generated: {datetime.datetime.now().isoformat()}")
        lines.append(f"Total Records: {len(records)}")
        lines.append("")

        # Group records by type
        records_by_type = {}
        for record in records:
            record_type = record.record_type.value
            if record_type not in records_by_type:
                records_by_type[record_type] = []
            records_by_type[record_type].append(record)

        # Add summary by type
        lines.append("## Summary by Record Type")
        for record_type, type_records in records_by_type.items():
            lines.append(f"- {record_type}: {len(type_records)} records")
        lines.append("")

        # Add detailed records
        lines.append("## Detailed Records")
        for record in records:
            record_time = datetime.datetime.fromtimestamp(record.timestamp).strftime('%Y-%m-%d %H:%M:%S')
            lines.append(f"### {record.record_type.value.capitalize()} ({record_time})")
            lines.append(f"ID: {record.id}")
            lines.append(f"Description: {record.description}")

            if record.input_ids:
                lines.append(f"Inputs: {', '.join(record.input_ids)}")
            if record.output_ids:
                lines.append(f"Outputs: {', '.join(record.output_ids)}")

            if include_parameters and hasattr(record, 'parameters') and record.parameters:
                lines.append("Parameters:")
                for key, value in record.parameters.items():
                    lines.append(f"  - {key}: {value}")

            # Add record-specific details
            if isinstance(record, SourceRecord):
                lines.append(f"Source Type: {record.source_type}")
                lines.append(f"Location: {record.location}")
                if record.format:
                    lines.append(f"Format: {record.format}")
                if record.size:
                    lines.append(f"Size: {record.size} bytes")
                if record.hash:
                    lines.append(f"Hash: {record.hash}")

            elif isinstance(record, TransformationRecord):
                lines.append(f"Transformation Type: {record.transformation_type}")
                if record.tool:
                    lines.append(f"Tool: {record.tool} (v{record.version})")
                if record.execution_time:
                    lines.append(f"Execution Time: {record.execution_time:.2f} seconds")
                lines.append(f"Success: {record.success}")
                if not record.success and record.error_message:
                    lines.append(f"Error: {record.error_message}")

            elif isinstance(record, MergeRecord):
                lines.append(f"Merge Type: {record.merge_type}")
                if record.merge_keys:
                    lines.append(f"Merge Keys: {', '.join(record.merge_keys)}")
                lines.append(f"Merge Strategy: {record.merge_strategy}")

            elif isinstance(record, QueryRecord):
                lines.append(f"Query Type: {record.query_type}")
                lines.append(f"Query: {record.query_text}")
                if record.execution_time:
                    lines.append(f"Execution Time: {record.execution_time:.2f} seconds")
                if record.result_count is not None:
                    lines.append(f"Result Count: {record.result_count}")

            elif isinstance(record, ResultRecord):
                lines.append(f"Result Type: {record.result_type}")
                if record.size:
                    lines.append(f"Size: {record.size} bytes")
                if record.record_count:
                    lines.append(f"Record Count: {record.record_count}")
                if record.fields:
                    lines.append(f"Fields: {', '.join(record.fields)}")
                if record.sample:
                    lines.append(f"Sample: {record.sample}")

            lines.append("")

        return "\n".join(lines)

    def _generate_json_report(
        self,
        records: List[ProvenanceRecord],
        include_parameters: bool
    ) -> str:
        """Generate a JSON audit report."""
        report = {
            "generated_at": datetime.datetime.now().isoformat(),
            "record_count": len(records),
            "records": []
        }

        for record in records:
            record_dict = record.to_dict()

            # Remove parameters if not included
            if not include_parameters and 'parameters' in record_dict:
                del record_dict['parameters']

            report["records"].append(record_dict)

        return json.dumps(report, indent=2)

    def _generate_html_report(
        self,
        records: List[ProvenanceRecord],
        include_parameters: bool
    ) -> str:
        """Generate an HTML audit report."""
        # Simple HTML report template
        html_parts = [
            "<!DOCTYPE html>",
            "<html>",
            "<head>",
            "  <title>Data Provenance Audit Report</title>",
            "  <style>",
            "    body { font-family: Arial, sans-serif; margin: 20px; }",
            "    h1 { color: #2c3e50; }",
            "    h2 { color: #3498db; margin-top: 30px; }",
            "    h3 { color: #2980b9; margin-top: 20px; }",
            "    table { border-collapse: collapse; margin: 15px 0; }",
            "    th, td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; }",
            "    th { background-color: #f2f2f2; }",
            "    .source { background-color: #d1ecf1; }",
            "    .transformation { background-color: #d4edda; }",
            "    .merge { background-color: #fff3cd; }",
            "    .query { background-color: #f8d7da; }",
            "    .result { background-color: #ffeeba; }",
            "    .checkpoint { background-color: #e2d8f0; }",
            "  </style>",
            "</head>",
            "<body>",
            "  <h1>Data Provenance Audit Report</h1>",
            f"  <p>Generated: {datetime.datetime.now().isoformat()}</p>",
            f"  <p>Total Records: {len(records)}</p>"
        ]

        # Group records by type
        records_by_type = {}
        for record in records:
            record_type = record.record_type.value
            if record_type not in records_by_type:
                records_by_type[record_type] = []
            records_by_type[record_type].append(record)

        # Add summary by type
        html_parts.append("  <h2>Summary by Record Type</h2>")
        html_parts.append("  <table>")
        html_parts.append("    <tr><th>Record Type</th><th>Count</th></tr>")
        for record_type, type_records in records_by_type.items():
            html_parts.append(f"    <tr><td>{record_type}</td><td>{len(type_records)}</td></tr>")
        html_parts.append("  </table>")

        # Add detailed records
        html_parts.append("  <h2>Detailed Records</h2>")
        for record in records:
            record_time = datetime.datetime.fromtimestamp(record.timestamp).strftime('%Y-%m-%d %H:%M:%S')
            record_type = record.record_type.value
            html_parts.append(f'  <div class="{record_type}">')
            html_parts.append(f'    <h3>{record_type.capitalize()} ({record_time})</h3>')
            html_parts.append(f'    <p><strong>ID:</strong> {record.id}</p>')
            html_parts.append(f'    <p><strong>Description:</strong> {record.description}</p>')

            if record.input_ids:
                html_parts.append(f'    <p><strong>Inputs:</strong> {", ".join(record.input_ids)}</p>')
            if record.output_ids:
                html_parts.append(f'    <p><strong>Outputs:</strong> {", ".join(record.output_ids)}</p>')

            # Add record-specific details
            if isinstance(record, SourceRecord):
                html_parts.append(f'    <p><strong>Source Type:</strong> {record.source_type}</p>')
                html_parts.append(f'    <p><strong>Location:</strong> {record.location}</p>')
                if record.format:
                    html_parts.append(f'    <p><strong>Format:</strong> {record.format}</p>')
                if record.size:
                    html_parts.append(f'    <p><strong>Size:</strong> {record.size} bytes</p>')
                if record.hash:
                    html_parts.append(f'    <p><strong>Hash:</strong> {record.hash}</p>')

            elif isinstance(record, TransformationRecord):
                html_parts.append(f'    <p><strong>Transformation Type:</strong> {record.transformation_type}</p>')
                if record.tool:
                    html_parts.append(f'    <p><strong>Tool:</strong> {record.tool} (v{record.version})</p>')
                if record.execution_time:
                    html_parts.append(f'    <p><strong>Execution Time:</strong> {record.execution_time:.2f} seconds</p>')
                html_parts.append(f'    <p><strong>Success:</strong> {record.success}</p>')
                if not record.success and record.error_message:
                    html_parts.append(f'    <p><strong>Error:</strong> {record.error_message}</p>')

            elif isinstance(record, MergeRecord):
                html_parts.append(f'    <p><strong>Merge Type:</strong> {record.merge_type}</p>')
                if record.merge_keys:
                    html_parts.append(f'    <p><strong>Merge Keys:</strong> {", ".join(record.merge_keys)}</p>')
                html_parts.append(f'    <p><strong>Merge Strategy:</strong> {record.merge_strategy}</p>')

            elif isinstance(record, QueryRecord):
                html_parts.append(f'    <p><strong>Query Type:</strong> {record.query_type}</p>')
                html_parts.append(f'    <p><strong>Query:</strong> {record.query_text}</p>')
                if record.execution_time:
                    html_parts.append(f'    <p><strong>Execution Time:</strong> {record.execution_time:.2f} seconds</p>')
                if record.result_count is not None:
                    html_parts.append(f'    <p><strong>Result Count:</strong> {record.result_count}</p>')

            elif isinstance(record, ResultRecord):
                html_parts.append(f'    <p><strong>Result Type:</strong> {record.result_type}</p>')
                if record.size:
                    html_parts.append(f'    <p><strong>Size:</strong> {record.size} bytes</p>')
                if record.record_count:
                    html_parts.append(f'    <p><strong>Record Count:</strong> {record.record_count}</p>')
                if record.fields:
                    html_parts.append(f'    <p><strong>Fields:</strong> {", ".join(record.fields)}</p>')
                if record.sample:
                    html_parts.append(f'    <p><strong>Sample:</strong> {record.sample}</p>')

            # Include parameters if requested
            if include_parameters and hasattr(record, 'parameters') and record.parameters:
                html_parts.append('    <div><strong>Parameters:</strong></div>')
                html_parts.append('    <table>')
                for key, value in record.parameters.items():
                    html_parts.append(f'      <tr><td>{key}</td><td>{value}</td></tr>')
                html_parts.append('    </table>')

            html_parts.append('  </div>')

        html_parts.extend([
            "</body>",
            "</html>"
        ])

        return '\n'.join(html_parts)

    def _generate_markdown_report(
        self,
        records: List[ProvenanceRecord],
        include_parameters: bool
    ) -> str:
        """Generate a Markdown audit report."""
        lines = ["# Data Provenance Audit Report", ""]
        lines.append(f"Generated: {datetime.datetime.now().isoformat()}")
        lines.append(f"Total Records: {len(records)}")
        lines.append("")

        # Group records by type
        records_by_type = {}
        for record in records:
            record_type = record.record_type.value
            if record_type not in records_by_type:
                records_by_type[record_type] = []
            records_by_type[record_type].append(record)

        # Add summary by type
        lines.append("## Summary by Record Type")
        lines.append("")
        lines.append("| Record Type | Count |")
        lines.append("| ----------- | ----- |")
        for record_type, type_records in records_by_type.items():
            lines.append(f"| {record_type} | {len(type_records)} |")
        lines.append("")

        # Add detailed records
        lines.append("## Detailed Records")
        for record in records:
            record_time = datetime.datetime.fromtimestamp(record.timestamp).strftime('%Y-%m-%d %H:%M:%S')
            lines.append(f"### {record.record_type.value.capitalize()} ({record_time})")
            lines.append(f"**ID:** {record.id}")
            lines.append(f"**Description:** {record.description}")

            if record.input_ids:
                lines.append(f"**Inputs:** {', '.join(record.input_ids)}")
            if record.output_ids:
                lines.append(f"**Outputs:** {', '.join(record.output_ids)}")

            # Add record-specific details
            if isinstance(record, SourceRecord):
                lines.append(f"**Source Type:** {record.source_type}")
                lines.append(f"**Location:** {record.location}")
                if record.format:
                    lines.append(f"**Format:** {record.format}")
                if record.size:
                    lines.append(f"**Size:** {record.size} bytes")
                if record.hash:
                    lines.append(f"**Hash:** {record.hash}")

            elif isinstance(record, TransformationRecord):
                lines.append(f"**Transformation Type:** {record.transformation_type}")
                if record.tool:
                    lines.append(f"**Tool:** {record.tool} (v{record.version})")
                if record.execution_time:
                    lines.append(f"**Execution Time:** {record.execution_time:.2f} seconds")
                lines.append(f"**Success:** {record.success}")
                if not record.success and record.error_message:
                    lines.append(f"**Error:** {record.error_message}")

            elif isinstance(record, MergeRecord):
                lines.append(f"**Merge Type:** {record.merge_type}")
                if record.merge_keys:
                    lines.append(f"**Merge Keys:** {', '.join(record.merge_keys)}")
                lines.append(f"**Merge Strategy:** {record.merge_strategy}")

            elif isinstance(record, QueryRecord):
                lines.append(f"**Query Type:** {record.query_type}")
                lines.append(f"**Query:** {record.query_text}")
                if record.execution_time:
                    lines.append(f"**Execution Time:** {record.execution_time:.2f} seconds")
                if record.result_count is not None:
                    lines.append(f"**Result Count:** {record.result_count}")

            elif isinstance(record, ResultRecord):
                lines.append(f"**Result Type:** {record.result_type}")
                if record.size:
                    lines.append(f"**Size:** {record.size} bytes")
                if record.record_count:
                    lines.append(f"**Record Count:** {record.record_count}")
                if record.fields:
                    lines.append(f"**Fields:** {', '.join(record.fields)}")
                if record.sample:
                    lines.append(f"**Sample:** {record.sample}")

            # Include parameters if requested
            if include_parameters and hasattr(record, 'parameters') and record.parameters:
                lines.append("**Parameters:**")
                for key, value in record.parameters.items():
                    lines.append(f"- {key}: {value}")

            lines.append("")

        return "\n".join(lines)


class ProvenanceContext:
    """
    Context manager for tracking data provenance.

    This class provides a convenient way to track data transformations
    using a context manager.
    """

    def __init__(
        self,
        provenance_manager: ProvenanceManager,
        description: str,
        transformation_type: str,
        tool: str = "",
        version: str = "",
        input_ids: Optional[List[str]] = None,
        parameters: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize the provenance context.

        Args:
            provenance_manager: Provenance manager to use
            description: Description of the transformation
            transformation_type: Type of transformation
            tool: Tool used for transformation
            version: Tool version
            input_ids: IDs of input data entities
            parameters: Transformation parameters
            metadata: Additional metadata
        """
        self.provenance_manager = provenance_manager
        self.description = description
        self.transformation_type = transformation_type
        self.tool = tool
        self.version = version
        self.input_ids = input_ids
        self.parameters = parameters
        self.metadata = metadata
        self.transformation_id = None
        self.success = True
        self.error_message = None

    def __enter__(self) -> 'ProvenanceContext':
        """Begin tracking a data transformation."""
        self.transformation_id = self.provenance_manager.begin_transformation(
            description=self.description,
            transformation_type=self.transformation_type,
            tool=self.tool,
            version=self.version,
            input_ids=self.input_ids,
            parameters=self.parameters,
            metadata=self.metadata
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """End tracking a data transformation."""
        if exc_type is not None:
            self.success = False
            self.error_message = str(exc_val)

        if self.transformation_id:
            self.provenance_manager.end_transformation(
                transformation_id=self.transformation_id,
                output_ids=self.output_ids if hasattr(self, 'output_ids') else None,
                success=self.success,
                error_message=self.error_message
            )

        # Don't suppress exceptions
        return False

    def set_output_ids(self, output_ids: List[str]) -> None:
        """Set the output data entity IDs."""
        self.output_ids = output_ids


# Example usage
def example_usage():
    """Example usage of the provenance tracking system."""
    # Initialize provenance manager
    provenance_manager = ProvenanceManager(
        storage_path=None,  # In-memory only
        enable_ipld_storage=False,
        default_agent_id="example_user",
        tracking_level="detailed"
    )

    # Record a source
    source_id = provenance_manager.record_source(
        data_id="raw_data_001",
        source_type="file",
        location="/path/to/data.csv",
        format="csv",
        description="Raw data from customer survey",
        size=1024 * 1024,  # 1 MB
        hash="sha256:abc123"
    )

    # Record a transformation
    with ProvenanceContext(
        provenance_manager=provenance_manager,
        description="Clean and preprocess survey data",
        transformation_type="preprocessing",
        tool="pandas",
        version="1.5.3",
        input_ids=["raw_data_001"],
        parameters={"dropna": True, "normalize": True}
    ) as context:
        # Simulate processing
        # ... actual data processing code here ...

        # Set output IDs
        context.set_output_ids(["preprocessed_data_001"])

    # Record a query
    query_id = provenance_manager.record_query(
        input_ids=["preprocessed_data_001"],
        query_type="sql",
        query_text="SELECT * FROM survey_data WHERE age > 30",
        description="Filter survey data for respondents over 30",
        query_parameters={"min_age": 30}
    )

    # Record the query result
    result_id = provenance_manager.record_query_result(
        query_id=query_id,
        output_id="filtered_data_001",
        result_count=250,
        result_type="filtered_dataset",
        size=512 * 1024,  # 512 KB
        fields=["id", "age", "gender", "response"]
    )

    # Record a merge operation
    merge_id = provenance_manager.record_merge(
        input_ids=["preprocessed_data_001", "external_data_001"],
        output_id="merged_data_001",
        merge_type="join",
        description="Merge survey data with external demographic data",
        merge_keys=["respondent_id"],
        merge_strategy="left_join",
        parameters={"how": "left", "on": "respondent_id"}
    )

    # Record a checkpoint
    checkpoint_id = provenance_manager.record_checkpoint(
        data_id="merged_data_001",
        description="Checkpoint after merging data",
        checkpoint_type="snapshot"
    )

    # Export provenance to JSON
    json_str = provenance_manager.export_provenance_to_json()

    # Visualize provenance
    provenance_manager.visualize_provenance(
        data_ids=["filtered_data_001", "merged_data_001"],
        max_depth=3,
        file_path="provenance_graph.png"
    )

    # Generate audit report
    audit_report = provenance_manager.generate_audit_report(
        include_parameters=True,
        format="html"
    )

    print("Provenance tracking example completed.")

    return {
        "json": json_str,
        "audit_report": audit_report,
        "provenance_manager": provenance_manager
    }


if __name__ == "__main__":
    example_usage()
