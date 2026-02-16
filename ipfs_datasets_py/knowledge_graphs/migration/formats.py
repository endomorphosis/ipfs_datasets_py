"""
Data Formats for Migration

Defines the data structures and formats used for migrating data
between Neo4j and IPFS Graph Database.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from enum import Enum
import json


class MigrationFormat(Enum):
    """Supported migration formats."""
    DAG_JSON = "dag-json"  # IPLD DAG-JSON
    JSON_LINES = "jsonlines"  # JSON Lines (one object per line)
    CAR = "car"  # Content Addressable aRchive


@dataclass
class NodeData:
    """Represents a node in the migration format."""
    
    id: str  # Node ID (can be Neo4j internal ID or custom)
    labels: List[str] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'id': self.id,
            'labels': self.labels,
            'properties': self.properties
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'NodeData':
        """Create from dictionary."""
        return cls(
            id=data['id'],
            labels=data.get('labels', []),
            properties=data.get('properties', {})
        )
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())


@dataclass
class RelationshipData:
    """Represents a relationship in the migration format."""
    
    id: str  # Relationship ID
    type: str  # Relationship type
    start_node: str  # Start node ID
    end_node: str  # End node ID
    properties: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'id': self.id,
            'type': self.type,
            'start_node': self.start_node,
            'end_node': self.end_node,
            'properties': self.properties
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RelationshipData':
        """Create from dictionary."""
        return cls(
            id=data['id'],
            type=data['type'],
            start_node=data['start_node'],
            end_node=data['end_node'],
            properties=data.get('properties', {})
        )
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())


@dataclass
class SchemaData:
    """Represents schema information."""
    
    indexes: List[Dict[str, Any]] = field(default_factory=list)
    constraints: List[Dict[str, Any]] = field(default_factory=list)
    node_labels: List[str] = field(default_factory=list)
    relationship_types: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'indexes': self.indexes,
            'constraints': self.constraints,
            'node_labels': self.node_labels,
            'relationship_types': self.relationship_types
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SchemaData':
        """Create from dictionary."""
        return cls(
            indexes=data.get('indexes', []),
            constraints=data.get('constraints', []),
            node_labels=data.get('node_labels', []),
            relationship_types=data.get('relationship_types', [])
        )


@dataclass
class GraphData:
    """Complete graph data for migration."""
    
    nodes: List[NodeData] = field(default_factory=list)
    relationships: List[RelationshipData] = field(default_factory=list)
    schema: Optional[SchemaData] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'nodes': [n.to_dict() for n in self.nodes],
            'relationships': [r.to_dict() for r in self.relationships],
            'schema': self.schema.to_dict() if self.schema else None,
            'metadata': self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GraphData':
        """Create from dictionary."""
        return cls(
            nodes=[NodeData.from_dict(n) for n in data.get('nodes', [])],
            relationships=[RelationshipData.from_dict(r) for r in data.get('relationships', [])],
            schema=SchemaData.from_dict(data['schema']) if data.get('schema') else None,
            metadata=data.get('metadata', {})
        )
    
    def to_json(self, indent: Optional[int] = None) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'GraphData':
        """Create from JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)
    
    def save_to_file(self, filepath: str, format: MigrationFormat = MigrationFormat.DAG_JSON) -> None:
        """Save to file in specified format."""
        if format == MigrationFormat.DAG_JSON or format == MigrationFormat.JSON_LINES:
            with open(filepath, 'w') as f:
                if format == MigrationFormat.DAG_JSON:
                    f.write(self.to_json(indent=2))
                else:  # JSON_LINES
                    # Write nodes
                    for node in self.nodes:
                        f.write(json.dumps({'type': 'node', 'data': node.to_dict()}) + '\n')
                    # Write relationships
                    for rel in self.relationships:
                        f.write(json.dumps({'type': 'relationship', 'data': rel.to_dict()}) + '\n')
                    # Write schema
                    if self.schema:
                        f.write(json.dumps({'type': 'schema', 'data': self.schema.to_dict()}) + '\n')
        else:
            raise NotImplementedError(f"Format {format} not yet implemented")
    
    @classmethod
    def load_from_file(cls, filepath: str, format: MigrationFormat = MigrationFormat.DAG_JSON) -> 'GraphData':
        """Load from file in specified format."""
        if format == MigrationFormat.DAG_JSON:
            with open(filepath, 'r') as f:
                return cls.from_json(f.read())
        elif format == MigrationFormat.JSON_LINES:
            nodes = []
            relationships = []
            schema = None
            
            with open(filepath, 'r') as f:
                for line in f:
                    if not line.strip():
                        continue
                    obj = json.loads(line)
                    if obj['type'] == 'node':
                        nodes.append(NodeData.from_dict(obj['data']))
                    elif obj['type'] == 'relationship':
                        relationships.append(RelationshipData.from_dict(obj['data']))
                    elif obj['type'] == 'schema':
                        schema = SchemaData.from_dict(obj['data'])
            
            return cls(nodes=nodes, relationships=relationships, schema=schema)
        else:
            raise NotImplementedError(f"Format {format} not yet implemented")
    
    @property
    def node_count(self) -> int:
        """Get number of nodes."""
        return len(self.nodes)
    
    @property
    def relationship_count(self) -> int:
        """Get number of relationships."""
        return len(self.relationships)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get graph statistics."""
        label_counts = {}
        for node in self.nodes:
            for label in node.labels:
                label_counts[label] = label_counts.get(label, 0) + 1
        
        type_counts = {}
        for rel in self.relationships:
            type_counts[rel.type] = type_counts.get(rel.type, 0) + 1
        
        return {
            'node_count': self.node_count,
            'relationship_count': self.relationship_count,
            'label_counts': label_counts,
            'relationship_type_counts': type_counts,
            'has_schema': self.schema is not None
        }
