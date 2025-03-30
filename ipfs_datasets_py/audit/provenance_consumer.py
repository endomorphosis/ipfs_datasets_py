"""
Provenance Consumer Interface

This module provides a standardized interface for consuming provenance information
from both the audit logging and data provenance systems. It enables applications
to access integrated provenance data through a unified API.
"""

import json
import logging
import datetime
import uuid
from typing import Dict, List, Any, Optional, Union, Set, Tuple, Callable, Iterator
from dataclasses import dataclass, field

# Try to import audit components
try:
    from ipfs_datasets_py.audit.audit_logger import (
        AuditLogger, AuditEvent, AuditLevel, AuditCategory
    )
    from ipfs_datasets_py.audit.integration import AuditProvenanceIntegrator
    AUDIT_AVAILABLE = True
except ImportError:
    AUDIT_AVAILABLE = False

# Try to import provenance components
try:
    from ipfs_datasets_py.data_provenance_enhanced import (
        EnhancedProvenanceManager, ProvenanceRecord, 
        SourceRecord, TransformationRecord
    )
    PROVENANCE_AVAILABLE = True
except ImportError:
    PROVENANCE_AVAILABLE = False


@dataclass
class IntegratedProvenanceRecord:
    """
    Unified representation of a provenance record with audit information.
    
    This class combines data from both the provenance system and audit logging
    system into a single record for easier consumption by applications.
    """
    # Core identity
    record_id: str
    record_type: str
    timestamp: float
    
    # Provenance data
    input_ids: List[str] = field(default_factory=list)
    output_ids: List[str] = field(default_factory=list)
    description: str = ""
    agent_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    parameters: Dict[str, Any] = field(default_factory=dict)
    
    # Audit data
    audit_events: List[str] = field(default_factory=list)
    user: Optional[str] = None
    status: str = "success"
    
    # Verification
    signature: Optional[str] = None
    is_verified: Optional[bool] = None
    
    # Lineage metrics
    impact_score: Optional[float] = None
    complexity_score: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the integrated record to a dictionary."""
        return {
            "record_id": self.record_id,
            "record_type": self.record_type,
            "timestamp": self.timestamp,
            "input_ids": self.input_ids,
            "output_ids": self.output_ids,
            "description": self.description,
            "agent_id": self.agent_id,
            "metadata": self.metadata,
            "parameters": self.parameters,
            "audit_events": self.audit_events,
            "user": self.user,
            "status": self.status,
            "signature": self.signature,
            "is_verified": self.is_verified,
            "impact_score": self.impact_score,
            "complexity_score": self.complexity_score
        }
    
    def to_json(self, pretty=False) -> str:
        """Serialize the integrated record to JSON."""
        if pretty:
            return json.dumps(self.to_dict(), indent=2)
        return json.dumps(self.to_dict())


class ProvenanceConsumer:
    """
    Unified interface for consuming integrated provenance information.
    
    This class provides methods to access, query, and process provenance
    information from both the audit logging and data provenance systems.
    """
    
    def __init__(
        self,
        provenance_manager: Optional[Any] = None,
        audit_logger: Optional[Any] = None,
        integrator: Optional[Any] = None
    ):
        """
        Initialize the provenance consumer.
        
        Args:
            provenance_manager: EnhancedProvenanceManager instance
            audit_logger: AuditLogger instance
            integrator: AuditProvenanceIntegrator instance
        """
        self.logger = logging.getLogger(__name__)
        
        # Check availability of components
        if not PROVENANCE_AVAILABLE:
            self.logger.warning("Provenance system not available")
        
        if not AUDIT_AVAILABLE:
            self.logger.warning("Audit system not available")
        
        # Store components
        self.provenance_manager = provenance_manager
        self.audit_logger = audit_logger
        self.integrator = integrator
        
        # Create required components if not provided
        if PROVENANCE_AVAILABLE and not self.provenance_manager:
            self.provenance_manager = EnhancedProvenanceManager()
        
        if AUDIT_AVAILABLE and not self.audit_logger:
            self.audit_logger = AuditLogger.get_instance()
        
        if AUDIT_AVAILABLE and PROVENANCE_AVAILABLE and not self.integrator:
            self.integrator = AuditProvenanceIntegrator(
                audit_logger=self.audit_logger,
                provenance_manager=self.provenance_manager
            )
    
    def get_integrated_record(self, record_id: str) -> Optional[IntegratedProvenanceRecord]:
        """
        Get an integrated provenance record by ID.
        
        Args:
            record_id: ID of the provenance record
            
        Returns:
            IntegratedProvenanceRecord or None if not found
        """
        if not PROVENANCE_AVAILABLE or not self.provenance_manager:
            self.logger.warning("Provenance system not available")
            return None
        
        # Get provenance record
        if record_id not in self.provenance_manager.records:
            return None
        
        record = self.provenance_manager.records[record_id]
        
        # Create base integrated record
        integrated_record = IntegratedProvenanceRecord(
            record_id=record.id,
            record_type=record.record_type.value if hasattr(record.record_type, 'value') else str(record.record_type),
            timestamp=record.timestamp,
            input_ids=record.input_ids if hasattr(record, 'input_ids') else [],
            output_ids=record.output_ids if hasattr(record, 'output_ids') else [],
            description=record.description,
            agent_id=record.agent_id,
            metadata=record.metadata
        )
        
        # Add parameters if available
        if hasattr(record, 'parameters'):
            integrated_record.parameters = record.parameters
        
        # Add signature if available
        if hasattr(record, 'signature'):
            integrated_record.signature = record.signature
            
            # Add verification status if available
            if hasattr(self.provenance_manager, 'verify_record'):
                integrated_record.is_verified = self.provenance_manager.verify_record(record_id)
        
        # Add lineage metrics if available
        if hasattr(self.provenance_manager, 'calculate_data_metrics'):
            for output_id in integrated_record.output_ids:
                try:
                    metrics = self.provenance_manager.calculate_data_metrics(output_id)
                    integrated_record.impact_score = metrics.get('impact', None)
                    
                    if 'complexity' in metrics:
                        complexity = metrics['complexity']
                        if isinstance(complexity, dict) and 'node_count' in complexity:
                            integrated_record.complexity_score = complexity['node_count']
                    
                    break  # Just use the first output for metrics
                except:
                    pass
        
        # Find linked audit events if integrator is available
        if AUDIT_AVAILABLE and self.integrator:
            if hasattr(record, 'metadata') and 'linked_audit_event_id' in record.metadata:
                integrated_record.audit_events.append(record.metadata['linked_audit_event_id'])
                
                # Try to get user from audit event
                try:
                    # This is a conceptual example; actual implementation would depend
                    # on how audit events are stored and retrieved
                    pass
                except:
                    pass
        
        return integrated_record
    
    def search_integrated_records(
        self,
        query: str = "",
        record_types: Optional[List[str]] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        data_ids: Optional[List[str]] = None,
        limit: int = 100
    ) -> List[IntegratedProvenanceRecord]:
        """
        Search for integrated provenance records.
        
        Args:
            query: Search query string
            record_types: Types of records to include
            start_time: Start timestamp
            end_time: End timestamp
            data_ids: Data entity IDs to filter by
            limit: Maximum number of results
            
        Returns:
            List[IntegratedProvenanceRecord]: Matching records
        """
        if not PROVENANCE_AVAILABLE or not self.provenance_manager:
            self.logger.warning("Provenance system not available")
            return []
        
        results = []
        
        # Use semantic search if query is provided
        if query and hasattr(self.provenance_manager, 'semantic_search'):
            search_results = self.provenance_manager.semantic_search(query, limit=limit)
            for result in search_results:
                record_id = result['record_id']
                integrated_record = self.get_integrated_record(record_id)
                if integrated_record:
                    results.append(integrated_record)
        
        # Use temporal query if time range is provided
        elif (start_time or end_time) and hasattr(self.provenance_manager, 'temporal_query'):
            temporal_results = self.provenance_manager.temporal_query(
                start_time=start_time,
                end_time=end_time,
                time_bucket="daily",
                record_types=record_types
            )
            
            for result in temporal_results[:limit]:
                record_id = result['record_id']
                integrated_record = self.get_integrated_record(record_id)
                if integrated_record:
                    results.append(integrated_record)
        
        # Filter by data IDs if provided
        elif data_ids:
            for data_id in data_ids:
                if data_id in self.provenance_manager.entity_latest_record:
                    record_id = self.provenance_manager.entity_latest_record[data_id]
                    integrated_record = self.get_integrated_record(record_id)
                    if integrated_record:
                        results.append(integrated_record)
                        
                        # Follow lineage back to find more records
                        self._add_lineage_records(record_id, results, limit)
        
        # Default to most recent records
        else:
            count = 0
            for record_id in sorted(
                self.provenance_manager.records.keys(),
                key=lambda x: self.provenance_manager.records[x].timestamp,
                reverse=True
            ):
                if count >= limit:
                    break
                    
                record = self.provenance_manager.records[record_id]
                
                # Filter by record type if specified
                if record_types and record.record_type.value not in record_types:
                    continue
                
                integrated_record = self.get_integrated_record(record_id)
                if integrated_record:
                    results.append(integrated_record)
                    count += 1
        
        return results
    
    def _add_lineage_records(
        self,
        record_id: str,
        results: List[IntegratedProvenanceRecord],
        limit: int,
        depth: int = 0,
        visited: Optional[Set[str]] = None
    ) -> None:
        """
        Helper method to add lineage records recursively.
        
        Args:
            record_id: Starting record ID
            results: List to add results to
            limit: Maximum number of records to add
            depth: Current recursion depth
            visited: Set of already visited record IDs
        """
        if depth > 10 or len(results) >= limit:
            return
            
        if visited is None:
            visited = set()
            
        if record_id in visited:
            return
            
        visited.add(record_id)
        
        # Get the record
        if record_id not in self.provenance_manager.records:
            return
            
        record = self.provenance_manager.records[record_id]
        
        # Add input records (following lineage backwards)
        if hasattr(record, 'input_ids'):
            for input_id in record.input_ids:
                if input_id in self.provenance_manager.entity_latest_record:
                    input_record_id = self.provenance_manager.entity_latest_record[input_id]
                    
                    # Add the record if we haven't already
                    if input_record_id not in visited:
                        integrated_record = self.get_integrated_record(input_record_id)
                        if integrated_record:
                            results.append(integrated_record)
                            
                            # Recursively add more records
                            self._add_lineage_records(
                                input_record_id, results, limit, depth + 1, visited
                            )
    
    def get_lineage_graph(
        self,
        data_id: str,
        max_depth: int = 5,
        include_audit_events: bool = True
    ) -> Dict[str, Any]:
        """
        Get lineage graph for a data entity.
        
        Args:
            data_id: ID of the data entity
            max_depth: Maximum depth of the lineage graph
            include_audit_events: Whether to include audit events in the graph
            
        Returns:
            Dict[str, Any]: Graph representation with nodes and edges
        """
        if not PROVENANCE_AVAILABLE or not self.provenance_manager:
            self.logger.warning("Provenance system not available")
            return {"nodes": [], "edges": []}
        
        # Find the latest record for the data entity
        if data_id not in self.provenance_manager.entity_latest_record:
            return {"nodes": [], "edges": []}
            
        record_id = self.provenance_manager.entity_latest_record[data_id]
        
        # Get the record and build lineage graph
        nodes = []
        edges = []
        visited = set()
        
        self._build_lineage_graph(
            record_id, nodes, edges, visited, 0, max_depth, include_audit_events
        )
        
        return {
            "nodes": nodes,
            "edges": edges
        }
    
    def _build_lineage_graph(
        self,
        record_id: str,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        visited: Set[str],
        depth: int,
        max_depth: int,
        include_audit_events: bool
    ) -> None:
        """
        Helper method to build lineage graph recursively.
        
        Args:
            record_id: Current record ID
            nodes: List to add nodes to
            edges: List to add edges to
            visited: Set of already visited record IDs
            depth: Current recursion depth
            max_depth: Maximum recursion depth
            include_audit_events: Whether to include audit events
        """
        if depth > max_depth or record_id in visited:
            return
            
        visited.add(record_id)
        
        # Get the record
        if record_id not in self.provenance_manager.records:
            return
            
        record = self.provenance_manager.records[record_id]
        
        # Add node for this record
        integrated_record = self.get_integrated_record(record_id)
        if integrated_record:
            nodes.append({
                "id": record_id,
                "type": integrated_record.record_type,
                "label": integrated_record.description or integrated_record.record_type,
                "timestamp": integrated_record.timestamp,
                "data": integrated_record.to_dict()
            })
            
            # Add audit event nodes if requested
            if include_audit_events and integrated_record.audit_events:
                for event_id in integrated_record.audit_events:
                    # Add audit event node
                    nodes.append({
                        "id": event_id,
                        "type": "audit_event",
                        "label": f"Audit: {event_id}",
                        "timestamp": integrated_record.timestamp,
                        "data": {"event_id": event_id}
                    })
                    
                    # Add edge from record to audit event
                    edges.append({
                        "source": record_id,
                        "target": event_id,
                        "type": "has_audit_event"
                    })
            
            # Add edges for inputs
            if hasattr(record, 'input_ids'):
                for input_id in record.input_ids:
                    if input_id in self.provenance_manager.entity_latest_record:
                        input_record_id = self.provenance_manager.entity_latest_record[input_id]
                        
                        # Add edge from input record to this record
                        edges.append({
                            "source": input_record_id,
                            "target": record_id,
                            "type": "input"
                        })
                        
                        # Recursively build graph for input record
                        self._build_lineage_graph(
                            input_record_id, nodes, edges, visited,
                            depth + 1, max_depth, include_audit_events
                        )
            
            # Add edges for outputs
            if hasattr(record, 'output_ids'):
                for output_id in record.output_ids:
                    if output_id in self.provenance_manager.entity_latest_record:
                        output_record_id = self.provenance_manager.entity_latest_record[output_id]
                        
                        # Only add edges to records we haven't already processed
                        if output_record_id not in visited:
                            # Add edge from this record to output record
                            edges.append({
                                "source": record_id,
                                "target": output_record_id,
                                "type": "output"
                            })
    
    def verify_data_lineage(self, data_id: str) -> Dict[str, Any]:
        """
        Verify the integrity and authenticity of a data entity's lineage.
        
        Args:
            data_id: ID of the data entity
            
        Returns:
            Dict[str, Any]: Verification results with details
        """
        if not PROVENANCE_AVAILABLE or not self.provenance_manager:
            self.logger.warning("Provenance system not available")
            return {"verified": False, "reason": "Provenance system not available"}
        
        if not hasattr(self.provenance_manager, 'verify_record'):
            return {"verified": False, "reason": "Verification not supported"}
        
        # Find the latest record for the data entity
        if data_id not in self.provenance_manager.entity_latest_record:
            return {"verified": False, "reason": "Data entity not found"}
            
        record_id = self.provenance_manager.entity_latest_record[data_id]
        
        # Verify the record and its entire lineage
        try:
            # Get lineage graph
            graph = self.get_lineage_graph(data_id, max_depth=100, include_audit_events=False)
            node_ids = [node["id"] for node in graph["nodes"]]
            
            # Verify all records in the lineage
            verification_results = {}
            for node_id in node_ids:
                if node_id in self.provenance_manager.records:
                    verification_results[node_id] = self.provenance_manager.verify_record(node_id)
            
            # Check if all records are verified
            all_verified = all(verification_results.values())
            
            # Return detailed results
            return {
                "verified": all_verified,
                "details": {
                    "record_count": len(verification_results),
                    "verified_count": sum(1 for v in verification_results.values() if v),
                    "unverified_count": sum(1 for v in verification_results.values() if not v),
                    "results": verification_results
                }
            }
        except Exception as e:
            return {
                "verified": False,
                "reason": f"Verification error: {str(e)}"
            }
    
    def export_provenance(
        self,
        data_id: str,
        format: str = "json",
        include_audit_events: bool = True,
        max_depth: int = 10
    ) -> Union[str, Dict[str, Any]]:
        """
        Export provenance information for a data entity.
        
        Args:
            data_id: ID of the data entity
            format: Export format ("json", "dict", "graph")
            include_audit_events: Whether to include audit events
            max_depth: Maximum depth of the lineage graph
            
        Returns:
            Union[str, Dict[str, Any]]: Exported provenance information
        """
        if not PROVENANCE_AVAILABLE or not self.provenance_manager:
            self.logger.warning("Provenance system not available")
            return {} if format == "dict" else "{}"
        
        # Get lineage graph
        graph = self.get_lineage_graph(
            data_id, max_depth=max_depth, include_audit_events=include_audit_events
        )
        
        # Convert graph to integrated records
        records = []
        for node in graph["nodes"]:
            if node["type"] != "audit_event" and "data" in node:
                record_id = node["id"]
                integrated_record = self.get_integrated_record(record_id)
                if integrated_record:
                    records.append(integrated_record.to_dict())
        
        # Create export structure
        export_data = {
            "data_id": data_id,
            "export_time": datetime.datetime.utcnow().isoformat() + "Z",
            "max_depth": max_depth,
            "include_audit_events": include_audit_events,
            "records": records,
            "lineage_graph": graph
        }
        
        # Return in requested format
        if format == "json":
            return json.dumps(export_data, indent=2)
        elif format == "graph":
            return graph
        else:  # dict
            return export_data