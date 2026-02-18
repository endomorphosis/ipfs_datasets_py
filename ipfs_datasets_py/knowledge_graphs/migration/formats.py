"""
Data Formats for Migration

Defines the data structures and formats used for migrating data
between Neo4j and IPFS Graph Database.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from enum import Enum
import json
import xml.etree.ElementTree as ET


class MigrationFormat(Enum):
    """Supported migration formats."""
    DAG_JSON = "dag-json"  # IPLD DAG-JSON
    JSON_LINES = "jsonlines"  # JSON Lines (one object per line)
    CAR = "car"  # Content Addressable aRchive
    GRAPHML = "graphml"  # GraphML XML format
    GEXF = "gexf"  # Graph Exchange XML Format
    PAJEK = "pajek"  # Pajek NET format


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
        
        elif format == MigrationFormat.GRAPHML:
            self._save_to_graphml(filepath)
        
        elif format == MigrationFormat.GEXF:
            self._save_to_gexf(filepath)
        
        elif format == MigrationFormat.PAJEK:
            self._save_to_pajek(filepath)
        
        elif format == MigrationFormat.CAR:
            raise NotImplementedError(f"CAR format requires IPLD CAR library integration (planned for future)")
        
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
        
        elif format == MigrationFormat.GRAPHML:
            return cls._load_from_graphml(filepath)
        
        elif format == MigrationFormat.GEXF:
            return cls._load_from_gexf(filepath)
        
        elif format == MigrationFormat.PAJEK:
            return cls._load_from_pajek(filepath)
        
        elif format == MigrationFormat.CAR:
            raise NotImplementedError(f"CAR format requires IPLD CAR library integration (planned for future)")
        
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
    
    def _save_to_graphml(self, filepath: str) -> None:
        """Save graph to GraphML XML format.
        
        GraphML is an XML-based format for graphs, widely used by tools like
        Gephi, yEd, and Cytoscape.
        """
        # Create root element
        graphml = ET.Element('graphml',
                            xmlns="http://graphml.graphdrawing.org/xmlns",
                            xmlns_xsi="http://www.w3.org/2001/XMLSchema-instance",
                            xsi_schemaLocation="http://graphml.graphdrawing.org/xmlns http://graphml.graphdrawing.org/xmlns/1.0/graphml.xsd")
        
        # Define keys for node and edge attributes
        # Collect all property keys from nodes and relationships
        node_props = set()
        for node in self.nodes:
            node_props.update(node.properties.keys())
        
        edge_props = set()
        for rel in self.relationships:
            edge_props.update(rel.properties.keys())
        
        # Add key definitions for node properties
        for i, prop in enumerate(sorted(node_props)):
            ET.SubElement(graphml, 'key',
                         id=f'node_prop_{i}',
                         for_='node',
                         attr_name=prop,
                         attr_type='string')
        
        # Add key definition for node labels
        ET.SubElement(graphml, 'key',
                     id='node_labels',
                     for_='node',
                     attr_name='labels',
                     attr_type='string')
        
        # Add key definitions for edge properties
        for i, prop in enumerate(sorted(edge_props)):
            ET.SubElement(graphml, 'key',
                         id=f'edge_prop_{i}',
                         for_='edge',
                         attr_name=prop,
                         attr_type='string')
        
        # Add key definition for edge type
        ET.SubElement(graphml, 'key',
                     id='edge_type',
                     for_='edge',
                     attr_name='type',
                     attr_type='string')
        
        # Create graph element
        graph_elem = ET.SubElement(graphml, 'graph',
                                  id='G',
                                  edgedefault='directed')
        
        # Add nodes
        for node in self.nodes:
            node_elem = ET.SubElement(graph_elem, 'node', id=str(node.id))
            
            # Add labels as data
            labels_elem = ET.SubElement(node_elem, 'data', key='node_labels')
            labels_elem.text = ','.join(node.labels)
            
            # Add properties as data
            for prop, value in node.properties.items():
                prop_key = f'node_prop_{sorted(node_props).index(prop)}'
                prop_elem = ET.SubElement(node_elem, 'data', key=prop_key)
                prop_elem.text = str(value)
        
        # Add edges (relationships)
        for rel in self.relationships:
            edge_elem = ET.SubElement(graph_elem, 'edge',
                                     id=str(rel.id),
                                     source=str(rel.start_node),
                                     target=str(rel.end_node))
            
            # Add type as data
            type_elem = ET.SubElement(edge_elem, 'data', key='edge_type')
            type_elem.text = rel.type
            
            # Add properties as data
            for prop, value in rel.properties.items():
                prop_key = f'edge_prop_{sorted(edge_props).index(prop)}'
                prop_elem = ET.SubElement(edge_elem, 'data', key=prop_key)
                prop_elem.text = str(value)
        
        # Write to file
        tree = ET.ElementTree(graphml)
        ET.indent(tree, space='  ')
        tree.write(filepath, encoding='utf-8', xml_declaration=True)
    
    @classmethod
    def _load_from_graphml(cls, filepath: str) -> 'GraphData':
        """Load graph from GraphML XML format."""
        tree = ET.parse(filepath)
        root = tree.getroot()
        
        # Parse namespace
        ns = {'gml': 'http://graphml.graphdrawing.org/xmlns'}
        
        # Parse key definitions to map IDs to attribute names
        key_map = {}
        for key in root.findall('gml:key', ns) or root.findall('key'):
            key_id = key.get('id')
            # Try both attr.name and attr_name
            attr_name = key.get('attr.name') or key.get('attr_name')
            key_for = key.get('for')
            if attr_name:
                key_map[key_id] = (attr_name, key_for)
        
        # Find graph element
        graph = root.find('gml:graph', ns)
        if graph is None:
            # Try without namespace
            graph = root.find('graph')
        
        nodes = []
        relationships = []
        
        # Parse nodes
        for node_elem in graph.findall('gml:node', ns) or graph.findall('node'):
            node_id = node_elem.get('id')
            labels = []
            properties = {}
            
            for data in node_elem.findall('gml:data', ns) or node_elem.findall('data'):
                key = data.get('key')
                value = data.text or ''
                
                if key in key_map:
                    attr_name, _ = key_map[key]
                    if attr_name == 'labels':
                        labels = [l.strip() for l in value.split(',') if l.strip()]
                    else:
                        properties[attr_name] = value
                elif value:  # Key not in map but has value
                    properties[key] = value
            
            nodes.append(NodeData(id=node_id, labels=labels, properties=properties))
        
        # Parse edges
        for edge_elem in graph.findall('gml:edge', ns) or graph.findall('edge'):
            edge_id = edge_elem.get('id')
            source = edge_elem.get('source')
            target = edge_elem.get('target')
            rel_type = 'RELATED_TO'
            properties = {}
            
            for data in edge_elem.findall('gml:data', ns) or edge_elem.findall('data'):
                key = data.get('key')
                value = data.text or ''
                
                if key in key_map:
                    attr_name, _ = key_map[key]
                    if attr_name == 'type':
                        rel_type = value
                    else:
                        properties[attr_name] = value
                elif value:  # Key not in map but has value
                    properties[key] = value
            
            relationships.append(RelationshipData(
                id=edge_id or f"{source}_{target}",
                type=rel_type,
                start_node=source,
                end_node=target,
                properties=properties
            ))
        
        return cls(nodes=nodes, relationships=relationships)
    
    def _save_to_gexf(self, filepath: str) -> None:
        """Save graph to GEXF XML format.
        
        GEXF (Graph Exchange XML Format) is used by Gephi and other tools.
        """
        # Create root element
        gexf = ET.Element('gexf',
                         xmlns="http://www.gexf.net/1.2draft",
                         version="1.2")
        
        # Add meta element
        meta = ET.SubElement(gexf, 'meta')
        ET.SubElement(meta, 'creator').text = 'IPFS Datasets Knowledge Graphs'
        ET.SubElement(meta, 'description').text = 'Graph exported from IPFS Knowledge Graphs'
        
        # Create graph element
        graph_elem = ET.SubElement(gexf, 'graph',
                                  defaultedgetype='directed',
                                  mode='static')
        
        # Collect all properties
        node_props = set()
        for node in self.nodes:
            node_props.update(node.properties.keys())
        
        edge_props = set()
        for rel in self.relationships:
            edge_props.update(rel.properties.keys())
        
        # Define attributes for nodes
        if node_props or True:  # Always add labels attribute
            attrs_elem = ET.SubElement(graph_elem, 'attributes', class_='node')
            ET.SubElement(attrs_elem, 'attribute',
                         id='0',
                         title='labels',
                         type='string')
            for i, prop in enumerate(sorted(node_props), start=1):
                ET.SubElement(attrs_elem, 'attribute',
                             id=str(i),
                             title=prop,
                             type='string')
        
        # Define attributes for edges
        if edge_props or True:  # Always add type attribute
            attrs_elem = ET.SubElement(graph_elem, 'attributes', class_='edge')
            ET.SubElement(attrs_elem, 'attribute',
                         id='0',
                         title='type',
                         type='string')
            for i, prop in enumerate(sorted(edge_props), start=1):
                ET.SubElement(attrs_elem, 'attribute',
                             id=str(i),
                             title=prop,
                             type='string')
        
        # Add nodes
        nodes_elem = ET.SubElement(graph_elem, 'nodes')
        for node in self.nodes:
            node_elem = ET.SubElement(nodes_elem, 'node', id=str(node.id))
            
            attvalues = ET.SubElement(node_elem, 'attvalues')
            
            # Add labels
            ET.SubElement(attvalues, 'attvalue',
                         for_='0',
                         value=','.join(node.labels))
            
            # Add properties
            for i, prop in enumerate(sorted(node_props), start=1):
                if prop in node.properties:
                    ET.SubElement(attvalues, 'attvalue',
                                 for_=str(i),
                                 value=str(node.properties[prop]))
        
        # Add edges
        edges_elem = ET.SubElement(graph_elem, 'edges')
        for rel in self.relationships:
            edge_elem = ET.SubElement(edges_elem, 'edge',
                                     id=str(rel.id),
                                     source=str(rel.start_node),
                                     target=str(rel.end_node))
            
            attvalues = ET.SubElement(edge_elem, 'attvalues')
            
            # Add type
            ET.SubElement(attvalues, 'attvalue',
                         for_='0',
                         value=rel.type)
            
            # Add properties
            for i, prop in enumerate(sorted(edge_props), start=1):
                if prop in rel.properties:
                    ET.SubElement(attvalues, 'attvalue',
                                 for_=str(i),
                                 value=str(rel.properties[prop]))
        
        # Write to file
        tree = ET.ElementTree(gexf)
        ET.indent(tree, space='  ')
        tree.write(filepath, encoding='utf-8', xml_declaration=True)
    
    @classmethod
    def _load_from_gexf(cls, filepath: str) -> 'GraphData':
        """Load graph from GEXF XML format."""
        tree = ET.parse(filepath)
        root = tree.getroot()
        
        # Parse namespace
        ns = {'gexf': 'http://www.gexf.net/1.2draft'}
        
        # Find graph element
        graph = root.find('gexf:graph', ns)
        if graph is None:
            graph = root.find('graph')
        
        # Parse attributes definitions
        node_attrs = {}
        edge_attrs = {}
        
        for attrs in graph.findall('gexf:attributes', ns) or graph.findall('attributes'):
            class_type = attrs.get('class')
            for attr in attrs.findall('gexf:attribute', ns) or attrs.findall('attribute'):
                attr_id = attr.get('id')
                attr_title = attr.get('title')
                if class_type == 'node':
                    node_attrs[attr_id] = attr_title
                elif class_type == 'edge':
                    edge_attrs[attr_id] = attr_title
        
        nodes = []
        relationships = []
        
        # Parse nodes
        nodes_elem = graph.find('gexf:nodes', ns) or graph.find('nodes')
        if nodes_elem is not None:
            for node_elem in nodes_elem.findall('gexf:node', ns) or nodes_elem.findall('node'):
                node_id = node_elem.get('id')
                labels = []
                properties = {}
                
                attvalues = node_elem.find('gexf:attvalues', ns) or node_elem.find('attvalues')
                if attvalues is not None:
                    for attval in attvalues.findall('gexf:attvalue', ns) or attvalues.findall('attvalue'):
                        for_attr = attval.get('for')
                        value = attval.get('value', '')
                        
                        if for_attr in node_attrs:
                            attr_name = node_attrs[for_attr]
                            if attr_name == 'labels':
                                labels = value.split(',') if value else []
                            else:
                                properties[attr_name] = value
                
                nodes.append(NodeData(id=node_id, labels=labels, properties=properties))
        
        # Parse edges
        edges_elem = graph.find('gexf:edges', ns) or graph.find('edges')
        if edges_elem is not None:
            for edge_elem in edges_elem.findall('gexf:edge', ns) or edges_elem.findall('edge'):
                edge_id = edge_elem.get('id')
                source = edge_elem.get('source')
                target = edge_elem.get('target')
                rel_type = 'RELATED_TO'
                properties = {}
                
                attvalues = edge_elem.find('gexf:attvalues', ns) or edge_elem.find('attvalues')
                if attvalues is not None:
                    for attval in attvalues.findall('gexf:attvalue', ns) or attvalues.findall('attvalue'):
                        for_attr = attval.get('for')
                        value = attval.get('value', '')
                        
                        if for_attr in edge_attrs:
                            attr_name = edge_attrs[for_attr]
                            if attr_name == 'type':
                                rel_type = value
                            else:
                                properties[attr_name] = value
                
                relationships.append(RelationshipData(
                    id=edge_id or f"{source}_{target}",
                    type=rel_type,
                    start_node=source,
                    end_node=target,
                    properties=properties
                ))
        
        return cls(nodes=nodes, relationships=relationships)
    
    def _save_to_pajek(self, filepath: str) -> None:
        """Save graph to Pajek NET format.
        
        Pajek is a program for large network analysis with a simple text format.
        """
        with open(filepath, 'w') as f:
            # Write nodes
            f.write(f"*Vertices {len(self.nodes)}\n")
            
            # Create node ID mapping (Pajek uses 1-based indexing)
            node_id_map = {node.id: i+1 for i, node in enumerate(self.nodes)}
            
            for i, node in enumerate(self.nodes, start=1):
                # Format: <id> "<label>" <x> <y> <z>
                label = node.properties.get('name', node.id)
                # Escape quotes in label
                label = str(label).replace('"', '\\"')
                f.write(f'{i} "{label}"\n')
            
            # Write edges (arcs for directed graph)
            f.write(f"*Arcs {len(self.relationships)}\n")
            for rel in self.relationships:
                source_idx = node_id_map.get(rel.start_node)
                target_idx = node_id_map.get(rel.end_node)
                if source_idx and target_idx:
                    # Format: <source> <target> <weight>
                    weight = rel.properties.get('weight', 1)
                    f.write(f"{source_idx} {target_idx} {weight}\n")
    
    @classmethod
    def _load_from_pajek(cls, filepath: str) -> 'GraphData':
        """Load graph from Pajek NET format."""
        nodes = []
        relationships = []
        
        with open(filepath, 'r') as f:
            lines = f.readlines()
        
        mode = None
        node_id_map = {}  # Map Pajek index to node ID
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('%'):
                continue
            
            if line.startswith('*Vertices') or line.startswith('*vertices'):
                mode = 'vertices'
                continue
            elif line.startswith('*Arcs') or line.startswith('*arcs'):
                mode = 'arcs'
                continue
            elif line.startswith('*Edges') or line.startswith('*edges'):
                mode = 'edges'
                continue
            
            if mode == 'vertices':
                # Parse node: <id> "<label>" [x y z]
                parts = line.split('"')
                if len(parts) >= 2:
                    idx = int(parts[0].strip())
                    label = parts[1]
                    node_id = f"n{idx}"
                    node_id_map[idx] = node_id
                    nodes.append(NodeData(
                        id=node_id,
                        labels=['Node'],
                        properties={'name': label}
                    ))
            
            elif mode in ('arcs', 'edges'):
                # Parse edge: <source> <target> [weight]
                parts = line.split()
                if len(parts) >= 2:
                    source_idx = int(parts[0])
                    target_idx = int(parts[1])
                    weight = float(parts[2]) if len(parts) > 2 else 1.0
                    
                    source_id = node_id_map.get(source_idx, f"n{source_idx}")
                    target_id = node_id_map.get(target_idx, f"n{target_idx}")
                    
                    relationships.append(RelationshipData(
                        id=f"e{len(relationships)}",
                        type='CONNECTED_TO',
                        start_node=source_id,
                        end_node=target_id,
                        properties={'weight': weight}
                    ))
        
        return cls(nodes=nodes, relationships=relationships)
