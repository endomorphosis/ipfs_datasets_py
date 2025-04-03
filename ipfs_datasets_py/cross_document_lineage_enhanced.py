"""
Enhanced Cross-Document Lineage Tracking

This module extends the cross-document lineage tracking capabilities
in the data provenance system with more detailed semantic relationship detection,
advanced document boundary analysis, and improved visualization.

It also provides integration with the IPLDProvenanceStorage class to support
detailed lineage tracking across documents and systems with comprehensive
analysis capabilities.
"""

import os
import uuid
import time
import json
import logging
import datetime
from typing import Dict, List, Optional, Union, Any, Set, Tuple
import networkx as nx
import matplotlib
import matplotlib.pyplot as plt
from collections import defaultdict

# Try to import optional visualization libraries
try:
    import plotly.graph_objects as go
    import plotly.express as px
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

# Set up logging
logger = logging.getLogger(__name__)

class CrossDocumentLineageEnhancer:
    """
    Provides enhanced functionality for cross-document lineage tracking.
    
    This class works with IPLDProvenanceStorage to extend its cross-document
    lineage capabilities with advanced features like:
    - Semantic relationship detection
    - Document boundary analysis
    - Enhanced visualization
    - Relationship categorization
    - Cross-document impact analysis
    """
    
    def __init__(self, storage):
        """
        Initialize the enhancer.
        
        Args:
            storage: IPLDProvenanceStorage instance to enhance
        """
        self.storage = storage
        
    def link_cross_document_provenance(self, source_record_id, target_record_id, link_type="related_to", 
                                      properties=None, confidence=1.0, semantic_context=None, 
                                      boundary_type=None):
        """
        Create an enhanced link between two provenance records that exist in different documents/datasets.
        
        This enhanced version provides more detailed relationship information, including semantic context,
        confidence scores, and boundary type classification for better cross-document lineage analysis.
        
        Args:
            source_record_id (str): ID of the source record
            target_record_id (str): ID of the target record
            link_type (str): Type of relationship between the records (e.g., "derived_from", "relates_to", "contains")
            properties (dict, optional): Additional properties for the link
            confidence (float, optional): Confidence score for the relationship (0.0-1.0)
            semantic_context (dict, optional): Semantic information about the relationship
                - category: Semantic category (e.g., "content", "temporal", "causal")
                - description: Human-readable description of the relationship
                - keywords: List of keywords characterizing the relationship
            boundary_type (str, optional): Type of document boundary being crossed
                - "organization": Cross-organizational boundary
                - "system": Cross-system boundary
                - "dataset": Cross-dataset boundary
                - "domain": Cross-domain boundary
                - "temporal": Temporal boundary (different time periods)
                - "format": Format boundary (different data formats)
                - "security": Security boundary (different security contexts)
                - "pii_boundary": Boundary between PII and non-PII data
                - "phi_boundary": Boundary between PHI and non-PHI data
                - "international_transfer": International data transfer boundary
                
        Returns:
            str: CID of the stored link record
        """
        # Ensure records exist in storage
        if source_record_id not in self.storage.record_cids:
            raise ValueError(f"Source record {source_record_id} not found in storage")
            
        if target_record_id not in self.storage.record_cids:
            raise ValueError(f"Target record {target_record_id} not found in storage")
        
        # Prepare enhanced properties
        link_properties = properties or {}
        
        # Add confidence score if not already in properties
        if "confidence" not in link_properties:
            link_properties["confidence"] = confidence
            
        # Add semantic context if provided
        if semantic_context:
            link_properties["semantic_context"] = semantic_context
            
        # Add boundary type if provided
        if boundary_type:
            link_properties["boundary_type"] = boundary_type
            
        # Add timestamp for the link creation
        link_properties["created_at"] = time.time()
        
        # Get document IDs for source and target if available
        source_doc_id = None
        target_doc_id = None
        
        try:
            if source_record_id in self.storage.record_cids:
                source_record = self.storage.load_record(self.storage.record_cids[source_record_id])
                if hasattr(source_record, "metadata") and isinstance(source_record.metadata, dict):
                    source_doc_id = source_record.metadata.get("document_id")
                    
            if target_record_id in self.storage.record_cids:
                target_record = self.storage.load_record(self.storage.record_cids[target_record_id])
                if hasattr(target_record, "metadata") and isinstance(target_record.metadata, dict):
                    target_doc_id = target_record.metadata.get("document_id")
        except Exception as e:
            logger.warning(f"Error retrieving document IDs for cross-document link: {str(e)}")
            
        # Add document IDs to link properties if available
        if source_doc_id:
            link_properties["source_document_id"] = source_doc_id
        if target_doc_id:
            link_properties["target_document_id"] = target_doc_id
            
        # Auto-detect boundary type if not provided
        if not boundary_type and source_doc_id and target_doc_id:
            if source_doc_id != target_doc_id:
                # Try to determine boundary type from document IDs
                if ("org:" in source_doc_id and "org:" in target_doc_id and 
                    source_doc_id.split("org:")[1] != target_doc_id.split("org:")[1]):
                    link_properties["boundary_type"] = "organization"
                elif ("system:" in source_doc_id and "system:" in target_doc_id and 
                      source_doc_id.split("system:")[1] != target_doc_id.split("system:")[1]):
                    link_properties["boundary_type"] = "system"
                elif "dataset:" in source_doc_id and "dataset:" in target_doc_id:
                    link_properties["boundary_type"] = "dataset"
                else:
                    link_properties["boundary_type"] = "unknown"
        
        # Create a link record using the existing method but with enhanced properties
        return self.storage.link_cross_document_provenance(
            source_record_id=source_record_id,
            target_record_id=target_record_id,
            link_type=link_type,
            properties=link_properties
        )
    
    def build_enhanced_cross_document_lineage_graph(self, record_ids, max_depth=3, 
                                                   link_types=None, include_semantic_analysis=True):
        """
        Build an enhanced cross-document lineage graph with additional semantic information.
        
        This method extends the default graph building with:
        - Semantic relationship detection and categorization
        - Enhanced boundary detection and classification
        - Document clustering and community detection
        - Path relevance scoring
        - More detailed metadata for nodes and edges
        
        Args:
            record_ids: Single record ID or list of record IDs to start from
            max_depth: Maximum traversal depth
            link_types: Optional filter for specific types of links
            include_semantic_analysis: Whether to include semantic relationship analysis
            
        Returns:
            nx.DiGraph: Enhanced lineage graph with additional attributes
        """
        # First build the base lineage graph
        base_graph = self.storage.build_cross_document_lineage_graph(
            record_ids=record_ids,
            max_depth=max_depth,
            link_types=link_types
        )
        
        if not include_semantic_analysis:
            return base_graph
            
        # Enhance the graph with semantic relationship information
        enhanced_graph = self._enhance_lineage_graph(base_graph)
        
        return enhanced_graph
    
    def _enhance_lineage_graph(self, graph):
        """
        Enhance a lineage graph with additional semantic information.
        
        Args:
            graph: nx.DiGraph to enhance
            
        Returns:
            nx.DiGraph: Enhanced graph
        """
        # Identify and label document boundaries more precisely
        self._enhance_document_boundaries(graph)
        
        # Detect semantic relationship types
        self._detect_semantic_relationships(graph)
        
        # Perform document clustering
        self._perform_document_clustering(graph)
        
        # Calculate enhanced metrics
        self._calculate_enhanced_metrics(graph)
        
        return graph
    
    def _enhance_document_boundaries(self, graph):
        """
        Enhance document boundary detection and labeling.
        
        Args:
            graph: nx.DiGraph to enhance
        """
        # Get all document IDs in the graph
        document_ids = set()
        document_nodes = defaultdict(list)
        
        for node, attrs in graph.nodes(data=True):
            doc_id = attrs.get('document_id')
            if doc_id:
                document_ids.add(doc_id)
                document_nodes[doc_id].append(node)
        
        # Identify boundary edges (edges between nodes in different documents)
        boundaries = []
        boundary_types = defaultdict(int)
        
        for u, v, attrs in graph.edges(data=True):
            u_doc = graph.nodes[u].get('document_id')
            v_doc = graph.nodes[v].get('document_id')
            
            if u_doc and v_doc and u_doc != v_doc:
                # This is a boundary edge
                boundary_type = attrs.get('boundary_type', 'unknown')
                if 'properties' in attrs and 'boundary_type' in attrs['properties']:
                    boundary_type = attrs['properties']['boundary_type']
                
                boundaries.append((u, v, u_doc, v_doc, boundary_type))
                boundary_types[boundary_type] += 1
                
                # Mark the edge as a boundary
                graph.edges[u, v]['is_boundary'] = True
                graph.edges[u, v]['boundary_type'] = boundary_type
                
        # Add document boundary information to graph attributes
        graph.graph['document_boundaries'] = boundaries
        graph.graph['boundary_types'] = dict(boundary_types)
        graph.graph['cross_boundary_flow_count'] = len(boundaries)
    
    def _detect_semantic_relationships(self, graph):
        """
        Detect and categorize semantic relationships in the graph.
        
        Args:
            graph: nx.DiGraph to enhance
        """
        # Initialize relationship tracking
        semantic_relationships = []
        relationship_types = defaultdict(int)
        
        # Analyze edge relationships
        for u, v, attrs in graph.edges(data=True):
            # Basic relationship type
            rel_type = attrs.get('relation', 'unknown')
            relationship_types[rel_type] += 1
            
            # Extract semantic context if available
            semantic_context = None
            if 'properties' in attrs and 'semantic_context' in attrs['properties']:
                semantic_context = attrs['properties']['semantic_context']
            
            # Determine semantic relationship category
            semantic_category = "unknown"
            if semantic_context and 'category' in semantic_context:
                semantic_category = semantic_context['category']
            elif rel_type in ["derived_from", "transforms", "generates"]:
                semantic_category = "causal"
            elif rel_type in ["contains", "part_of", "references"]:
                semantic_category = "structural"
            elif rel_type in ["precedes", "follows", "concurrent_with"]:
                semantic_category = "temporal"
            elif rel_type in ["similar_to", "semantically_related", "contradicts"]:
                semantic_category = "semantic"
                
            # Add semantic information to edge
            graph.edges[u, v]['semantic_category'] = semantic_category
            
            # Track the relationship
            semantic_relationships.append({
                'source': u,
                'target': v,
                'type': rel_type,
                'semantic_category': semantic_category,
                'context': semantic_context
            })
        
        # Add semantic relationship information to graph attributes
        graph.graph['semantic_relationships'] = semantic_relationships
        graph.graph['relationship_types'] = dict(relationship_types)
        graph.graph['semantic_categories'] = {
            cat: len([r for r in semantic_relationships if r['semantic_category'] == cat])
            for cat in set(r['semantic_category'] for r in semantic_relationships)
        }
    
    def _perform_document_clustering(self, graph):
        """
        Perform document clustering to identify related document groups.
        
        Args:
            graph: nx.DiGraph to enhance
        """
        # Create a document-level graph
        doc_graph = nx.Graph()
        
        # Add document nodes
        document_metadata = graph.graph.get('documents', {})
        for doc_id, metadata in document_metadata.items():
            doc_graph.add_node(doc_id, **metadata)
            
        # Add document relationships based on cross-document edges
        for u, v, attrs in graph.edges(data=True):
            u_doc = graph.nodes[u].get('document_id')
            v_doc = graph.nodes[v].get('document_id')
            
            if u_doc and v_doc and u_doc != v_doc:
                # Add or update edge between documents
                if doc_graph.has_edge(u_doc, v_doc):
                    doc_graph.edges[u_doc, v_doc]['weight'] += 1
                else:
                    doc_graph.add_edge(u_doc, v_doc, weight=1)
        
        # Perform community detection if networkx has the algorithms
        document_clusters = {}
        try:
            # Try to use Louvain community detection
            from networkx.algorithms import community
            communities = community.louvain_communities(doc_graph)
            
            # Convert communities to clusters
            for i, comm in enumerate(communities):
                cluster_id = f"cluster_{i}"
                document_clusters[cluster_id] = list(comm)
                
                # Add cluster information to document nodes
                for doc_id in comm:
                    # Update document metadata
                    if doc_id in document_metadata:
                        document_metadata[doc_id]['cluster'] = cluster_id
        except ImportError:
            # Fall back to connected components
            communities = list(nx.connected_components(doc_graph))
            for i, comm in enumerate(communities):
                cluster_id = f"component_{i}"
                document_clusters[cluster_id] = list(comm)
                
                # Add component information to document nodes
                for doc_id in comm:
                    # Update document metadata
                    if doc_id in document_metadata:
                        document_metadata[doc_id]['cluster'] = cluster_id
        
        # Update graph attributes
        graph.graph['document_clusters'] = document_clusters
        graph.graph['cluster_count'] = len(document_clusters)
        graph.graph['documents'] = document_metadata  # Update with cluster information
    
    def _calculate_enhanced_metrics(self, graph):
        """
        Calculate enhanced metrics for the lineage graph.
        
        Args:
            graph: nx.DiGraph to enhance
        """
        # Data flow metrics
        flow_metrics = {
            'total_flows': graph.number_of_edges(),
            'cross_document_flows': sum(1 for _, _, attrs in graph.edges(data=True) 
                                      if attrs.get('cross_document', False)),
            'flow_density': nx.density(graph),
        }
        
        # Calculate average path lengths for connected nodes
        path_lengths = []
        for source in graph.nodes():
            for target in graph.nodes():
                if source != target and nx.has_path(graph, source, target):
                    path_lengths.append(nx.shortest_path_length(graph, source, target))
        
        if path_lengths:
            flow_metrics['average_path_length'] = sum(path_lengths) / len(path_lengths)
        else:
            flow_metrics['average_path_length'] = 0
            
        # Add to graph attributes
        graph.graph['data_flow_metrics'] = flow_metrics
        
        # Calculate high-centrality records
        centrality = nx.betweenness_centrality(graph)
        
        # Find records with high centrality (above 75th percentile)
        if centrality:
            centrality_values = list(centrality.values())
            if centrality_values:
                threshold = sorted(centrality_values)[int(len(centrality_values) * 0.75)]
                high_centrality_records = [node for node, c in centrality.items() if c >= threshold]
                graph.graph['high_centrality_records'] = high_centrality_records
        
        # Calculate boundary impact assessment
        boundary_impact = {}
        doc_id_to_nodes = defaultdict(list)
        
        # Map nodes to documents
        for node, attrs in graph.nodes(data=True):
            doc_id = attrs.get('document_id')
            if doc_id:
                doc_id_to_nodes[doc_id].append(node)
        
        # Calculate impact across boundaries
        for doc_id, nodes in doc_id_to_nodes.items():
            outgoing_impact = 0
            incoming_dependence = 0
            
            for node in nodes:
                # Check outgoing edges to other documents
                for _, target in graph.out_edges(node):
                    target_doc = graph.nodes[target].get('document_id')
                    if target_doc and target_doc != doc_id:
                        outgoing_impact += 1
                
                # Check incoming edges from other documents
                for source, _ in graph.in_edges(node):
                    source_doc = graph.nodes[source].get('document_id')
                    if source_doc and source_doc != doc_id:
                        incoming_dependence += 1
            
            boundary_impact[doc_id] = {
                'outgoing_impact': outgoing_impact,
                'incoming_dependence': incoming_dependence,
                'impact_ratio': outgoing_impact / (incoming_dependence or 1)
            }
        
        # Add boundary impact to graph attributes
        graph.graph['boundary_impact'] = boundary_impact
    
    def visualize_enhanced_cross_document_lineage(self, lineage_graph=None, record_ids=None, max_depth=3,
                                                highlight_cross_document=True, highlight_boundaries=True,
                                                layout="hierarchical", show_clusters=True,
                                                show_metrics=True, file_path=None, format="png",
                                                width=1200, height=800):
        """
        Visualize cross-document lineage with enhanced features.
        
        This enhanced version provides better visualization with:
        - Document boundary highlighting
        - Document cluster visualization
        - Semantic relationship coloring
        - Boundary impact visualization
        - Interactive capabilities with Plotly (if available)
        
        Args:
            lineage_graph: Optional pre-built lineage graph. If None, built from record_ids
            record_ids: Single record ID or list of record IDs to start from (if lineage_graph is None)
            max_depth: Maximum traversal depth (if lineage_graph is None)
            highlight_cross_document: Whether to highlight cross-document edges
            highlight_boundaries: Whether to highlight document boundaries
            layout: Layout algorithm to use ("hierarchical", "spring", "circular", "spectral")
            show_clusters: Whether to group nodes by document clusters
            show_metrics: Whether to include metrics in visualization
            file_path: If specified, save visualization to this file
            format: Output format ("png", "svg", "pdf", "json", "html")
            width: Width of the visualization in pixels
            height: Height of the visualization in pixels
            
        Returns:
            Visualization result (format dependent) or None if saved to file
        """
        # Build or use the provided lineage graph
        graph = lineage_graph
        if graph is None:
            if record_ids is None:
                raise ValueError("Either lineage_graph or record_ids must be provided")
            graph = self.build_enhanced_cross_document_lineage_graph(
                record_ids=record_ids,
                max_depth=max_depth
            )
        
        # Interactive visualization with Plotly if available and format supports it
        if PLOTLY_AVAILABLE and format in ["html", "json"]:
            return self._visualize_with_plotly(
                graph=graph,
                highlight_cross_document=highlight_cross_document,
                highlight_boundaries=highlight_boundaries,
                show_clusters=show_clusters,
                show_metrics=show_metrics,
                file_path=file_path,
                format=format,
                width=width,
                height=height
            )
        else:
            # Fall back to matplotlib
            return self._visualize_with_matplotlib(
                graph=graph,
                highlight_cross_document=highlight_cross_document,
                highlight_boundaries=highlight_boundaries,
                layout=layout,
                show_clusters=show_clusters,
                show_metrics=show_metrics,
                file_path=file_path,
                format=format,
                width=width,
                height=height
            )
    
    def _visualize_with_matplotlib(self, graph, highlight_cross_document, highlight_boundaries,
                                 layout, show_clusters, show_metrics, file_path, format,
                                 width, height):
        """
        Visualize lineage graph using matplotlib.
        
        Args:
            graph: NetworkX DiGraph to visualize
            highlight_cross_document: Whether to highlight cross-document edges
            highlight_boundaries: Whether to highlight document boundaries
            layout: Layout algorithm to use
            show_clusters: Whether to group nodes by document clusters
            show_metrics: Whether to include metrics in visualization
            file_path: If specified, save visualization to this file
            format: Output format
            width: Width of the visualization in pixels
            height: Height of the visualization in pixels
            
        Returns:
            Visualization result or None if saved to file
        """
        # Set up figure
        plt.figure(figsize=(width/100, height/100), dpi=100)
        
        # Determine node positions based on layout
        if layout == "hierarchical":
            pos = nx.multipartite_layout(graph, subset_key="record_type")
        elif layout == "spring":
            pos = nx.spring_layout(graph)
        elif layout == "circular":
            pos = nx.circular_layout(graph)
        elif layout == "spectral":
            pos = nx.spectral_layout(graph)
        else:
            pos = nx.spring_layout(graph)
            
        # Group nodes by document or cluster if requested
        if show_clusters:
            # Get document clusters
            document_clusters = graph.graph.get('document_clusters', {})
            cluster_to_nodes = defaultdict(list)
            
            # Map nodes to clusters based on their document
            for node, attrs in graph.nodes(data=True):
                doc_id = attrs.get('document_id')
                if doc_id:
                    # Find cluster for this document
                    for cluster, docs in document_clusters.items():
                        if doc_id in docs:
                            cluster_to_nodes[cluster].append(node)
                            break
                    else:
                        # No cluster found, use document as cluster
                        cluster_to_nodes[f"doc_{doc_id}"].append(node)
                else:
                    # No document ID, put in "unknown" cluster
                    cluster_to_nodes["unknown"].append(node)
                    
            # Draw each cluster
            for i, (cluster, nodes) in enumerate(cluster_to_nodes.items()):
                if not nodes:
                    continue
                    
                # Draw a convex hull around the cluster
                node_pos = [pos[node] for node in nodes]
                if len(node_pos) > 2:
                    from scipy.spatial import ConvexHull
                    try:
                        hull = ConvexHull(node_pos)
                        hull_points = [node_pos[i] for i in hull.vertices]
                        hull_points.append(hull_points[0])  # Close the polygon
                        xs, ys = zip(*hull_points)
                        
                        # Draw with a light background and label
                        plt.fill(xs, ys, alpha=0.2, color=f'C{i%9}')
                        
                        # Add cluster label at centroid
                        centroid_x = sum(p[0] for p in node_pos) / len(node_pos)
                        centroid_y = sum(p[1] for p in node_pos) / len(node_pos)
                        plt.text(centroid_x, centroid_y, cluster, 
                                ha='center', va='center', bbox=dict(facecolor='white', alpha=0.6))
                    except:
                        # Fall back if convex hull fails
                        pass
        
        # Draw nodes with colors based on record type
        record_types = {attrs.get('record_type', 'unknown') for _, attrs in graph.nodes(data=True)}
        color_map = {rt: f'C{i}' for i, rt in enumerate(record_types)}
        
        # Draw nodes
        for record_type in record_types:
            nodes = [node for node, attrs in graph.nodes(data=True) 
                    if attrs.get('record_type') == record_type]
            if nodes:
                nx.draw_networkx_nodes(
                    graph, pos, 
                    nodelist=nodes,
                    node_color=color_map[record_type],
                    node_size=100,
                    alpha=0.8,
                    label=record_type
                )
        
        # Draw edges with different styles based on cross-document status
        cross_doc_edges = [(u, v) for u, v, attrs in graph.edges(data=True) 
                          if attrs.get('cross_document', False)]
        normal_edges = [(u, v) for u, v, attrs in graph.edges(data=True) 
                      if not attrs.get('cross_document', False)]
        boundary_edges = [(u, v) for u, v, attrs in graph.edges(data=True) 
                        if attrs.get('is_boundary', False)]
        
        # Draw normal edges
        if normal_edges:
            nx.draw_networkx_edges(
                graph, pos,
                edgelist=normal_edges,
                width=1.0,
                alpha=0.5,
                edge_color='gray'
            )
        
        # Draw cross-document edges if highlighting
        if highlight_cross_document and cross_doc_edges:
            nx.draw_networkx_edges(
                graph, pos,
                edgelist=cross_doc_edges,
                width=1.5,
                alpha=0.7,
                edge_color='blue',
                style='dashed'
            )
            
        # Draw boundary edges with special style if highlighting
        if highlight_boundaries and boundary_edges:
            nx.draw_networkx_edges(
                graph, pos,
                edgelist=boundary_edges,
                width=2.0,
                alpha=0.9,
                edge_color='red',
                style='dotted'
            )
        
        # Draw node labels
        nx.draw_networkx_labels(
            graph, pos,
            labels={node: node for node in graph.nodes()},
            font_size=8,
            font_color='black'
        )
        
        # Add metrics and legend if requested
        if show_metrics:
            metrics_text = []
            metrics_text.append(f"Nodes: {graph.number_of_nodes()}")
            metrics_text.append(f"Edges: {graph.number_of_edges()}")
            
            if 'documents' in graph.graph:
                metrics_text.append(f"Documents: {len(graph.graph['documents'])}")
                
            if 'cross_document_edge_count' in graph.graph:
                metrics_text.append(f"Cross-doc edges: {graph.graph['cross_document_edge_count']}")
                
            if 'document_clusters' in graph.graph:
                metrics_text.append(f"Clusters: {len(graph.graph['document_clusters'])}")
                
            if 'semantic_categories' in graph.graph:
                for category, count in graph.graph['semantic_categories'].items():
                    metrics_text.append(f"{category}: {count}")
                    
            # Add metrics to plot
            metrics_str = '\n'.join(metrics_text)
            plt.figtext(0.01, 0.01, metrics_str, fontsize=8,
                       bbox=dict(facecolor='white', alpha=0.8))
        
        # Add title and legend
        plt.title("Cross-Document Lineage Graph")
        plt.legend()
        plt.axis('off')
        
        # Save or return based on format
        if file_path:
            plt.savefig(file_path, format=format, bbox_inches='tight')
            plt.close()
            return None
        elif format == 'svg':
            from io import BytesIO
            import base64
            
            buffer = BytesIO()
            plt.savefig(buffer, format='svg', bbox_inches='tight')
            plt.close()
            svg_content = buffer.getvalue().decode('utf-8')
            return svg_content
        else:
            from io import BytesIO
            import base64
            
            buffer = BytesIO()
            plt.savefig(buffer, format=format, bbox_inches='tight')
            plt.close()
            image_data = base64.b64encode(buffer.getvalue()).decode('utf-8')
            return image_data
    
    def _visualize_with_plotly(self, graph, highlight_cross_document, highlight_boundaries,
                             show_clusters, show_metrics, file_path, format, width, height):
        """
        Visualize lineage graph using Plotly for interactive visualization.
        
        Args:
            graph: NetworkX DiGraph to visualize
            highlight_cross_document: Whether to highlight cross-document edges
            highlight_boundaries: Whether to highlight document boundaries
            show_clusters: Whether to group nodes by document clusters
            show_metrics: Whether to include metrics in visualization
            file_path: If specified, save visualization to this file
            format: Output format
            width: Width of the visualization in pixels
            height: Height of the visualization in pixels
            
        Returns:
            Visualization result or None if saved to file
        """
        # Convert graph to node and edge lists for Plotly
        nodes = []
        for node, attrs in graph.nodes(data=True):
            record_type = attrs.get('record_type', 'unknown')
            doc_id = attrs.get('document_id', 'unknown')
            
            # Determine node color based on record type
            color_map = {
                'source': 'blue',
                'transformation': 'green',
                'verification': 'orange',
                'query': 'purple',
                'result': 'red',
                'unknown': 'gray'
            }
            color = color_map.get(record_type, 'gray')
            
            # Create node data
            node_data = {
                'id': node,
                'label': node,
                'color': color,
                'size': 10,
                'record_type': record_type,
                'document_id': doc_id,
            }
            
            # Add additional attributes
            for key, value in attrs.items():
                if key not in node_data and not key.startswith("_"):
                    # Convert complex objects to strings
                    if isinstance(value, (dict, list)):
                        node_data[key] = str(value)
                    else:
                        node_data[key] = value
                        
            nodes.append(node_data)
            
        # Create edge list
        edges = []
        for u, v, attrs in graph.edges(data=True):
            # Determine edge color and style
            color = 'gray'
            width = 1
            dash = 'solid'
            
            if attrs.get('cross_document', False) and highlight_cross_document:
                color = 'blue'
                width = 2
                dash = 'dash'
                
            if attrs.get('is_boundary', False) and highlight_boundaries:
                color = 'red'
                width = 3
                dash = 'dot'
                
            # Create edge data
            edge_data = {
                'source': u,
                'target': v,
                'color': color,
                'width': width,
                'dash': dash
            }
            
            # Add relationship type if available
            if 'relation' in attrs:
                edge_data['label'] = attrs['relation']
                
            # Add semantic category if available
            if 'semantic_category' in attrs:
                edge_data['semantic_category'] = attrs['semantic_category']
                
            edges.append(edge_data)
        
        # Create Plotly figure
        fig = go.Figure()
        
        # Use Plotly's force-directed graph layout
        # This requires networkx positions
        pos = nx.spring_layout(graph, seed=42)
        
        # Extract x, y coordinates
        x_nodes = [pos[node][0] for node in graph.nodes()]
        y_nodes = [pos[node][1] for node in graph.nodes()]
        
        # Create node traces by record type
        record_types = {node['record_type'] for node in nodes}
        for record_type in record_types:
            # Filter nodes by record type
            type_nodes = [node for node in nodes if node['record_type'] == record_type]
            
            if not type_nodes:
                continue
                
            # Extract node data
            node_x = [pos[node['id']][0] for node in type_nodes]
            node_y = [pos[node['id']][1] for node in type_nodes]
            node_text = [f"ID: {node['id']}<br>Type: {node['record_type']}<br>Doc: {node['document_id']}" 
                        for node in type_nodes]
            node_color = [node['color'] for node in type_nodes]
            
            # Create node trace
            node_trace = go.Scatter(
                x=node_x, y=node_y,
                mode='markers+text',
                marker=dict(
                    size=15,
                    color=node_color,
                    opacity=0.8
                ),
                text=[node['id'] for node in type_nodes],
                textposition="top center",
                hovertext=node_text,
                hoverinfo='text',
                name=record_type
            )
            
            fig.add_trace(node_trace)
        
        # Create edge traces by type
        edge_types = {'normal': [], 'cross_doc': [], 'boundary': []}
        
        for edge in edges:
            u, v = edge['source'], edge['target']
            x0, y0 = pos[u]
            x1, y1 = pos[v]
            
            # Determine edge type for grouping
            if edge['dash'] == 'dot':
                edge_types['boundary'].append((x0, y0, x1, y1, edge))
            elif edge['dash'] == 'dash':
                edge_types['cross_doc'].append((x0, y0, x1, y1, edge))
            else:
                edge_types['normal'].append((x0, y0, x1, y1, edge))
        
        # Create edge traces
        for edge_type, edges_of_type in edge_types.items():
            if not edges_of_type:
                continue
                
            # Unpack edge data
            x_edges = []
            y_edges = []
            edge_colors = []
            edge_widths = []
            edge_text = []
            
            for x0, y0, x1, y1, edge in edges_of_type:
                x_edges.extend([x0, x1, None])
                y_edges.extend([y0, y1, None])
                edge_colors.append(edge['color'])
                edge_widths.append(edge['width'])
                
                # Create hover text
                hover_text = f"Source: {edge['source']}<br>Target: {edge['target']}"
                if 'label' in edge:
                    hover_text += f"<br>Relation: {edge['label']}"
                if 'semantic_category' in edge:
                    hover_text += f"<br>Category: {edge['semantic_category']}"
                    
                edge_text.append(hover_text)
            
            # Create edge trace
            edge_trace = go.Scatter(
                x=x_edges, y=y_edges,
                mode='lines',
                line=dict(
                    color=edge_colors[0] if edge_colors else 'gray',
                    width=edge_widths[0] if edge_widths else 1,
                    dash=edge_type if edge_type != 'normal' else 'solid'
                ),
                hoverinfo='text',
                hovertext=edge_text * 3,  # Repeat for each segment (source, target, None)
                name=f"{edge_type} links"
            )
            
            fig.add_trace(edge_trace)
        
        # Update layout
        fig.update_layout(
            title="Interactive Cross-Document Lineage Graph",
            showlegend=True,
            hovermode='closest',
            margin=dict(b=20, l=5, r=5, t=40),
            width=width,
            height=height,
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False)
        )
        
        # Add metrics as annotations if requested
        if show_metrics:
            metrics_text = []
            metrics_text.append(f"Nodes: {graph.number_of_nodes()}")
            metrics_text.append(f"Edges: {graph.number_of_edges()}")
            
            if 'documents' in graph.graph:
                metrics_text.append(f"Documents: {len(graph.graph['documents'])}")
                
            if 'cross_document_edge_count' in graph.graph:
                metrics_text.append(f"Cross-doc edges: {graph.graph['cross_document_edge_count']}")
                
            if 'document_clusters' in graph.graph:
                metrics_text.append(f"Clusters: {len(graph.graph['document_clusters'])}")
                
            # Add metrics as annotation
            fig.add_annotation(
                xref="paper", yref="paper",
                x=0.01, y=0.99,
                text="<br>".join(metrics_text),
                showarrow=False,
                font=dict(size=12),
                bgcolor="white",
                opacity=0.8,
                align="left"
            )
        
        # Output based on format
        if file_path:
            if format == "html":
                fig.write_html(file_path)
            elif format == "json":
                with open(file_path, 'w') as f:
                    f.write(fig.to_json())
            else:
                fig.write_image(file_path, format=format)
            return None
        else:
            if format == "html":
                return fig.to_html()
            elif format == "json":
                return fig.to_json()
            else:
                # Return image as base64
                from io import BytesIO
                import base64
                
                buffer = BytesIO()
                fig.write_image(buffer, format=format)
                image_data = base64.b64encode(buffer.getvalue()).decode('utf-8')
                return image_data

    def analyze_cross_document_lineage(self, lineage_graph=None, record_ids=None, max_depth=3,
                                     include_semantic_analysis=True, include_impact_analysis=True,
                                     include_cluster_analysis=True):
        """
        Perform enhanced analysis of cross-document lineage.
        
        This method provides a comprehensive analysis of cross-document
        relationships, document boundaries, and data flow patterns.
        
        Args:
            lineage_graph: Optional pre-built lineage graph. If None, built from record_ids
            record_ids: Single record ID or list of record IDs to start from (if lineage_graph is None)
            max_depth: Maximum traversal depth (if lineage_graph is None)
            include_semantic_analysis: Whether to include semantic relationship analysis
            include_impact_analysis: Whether to include impact analysis
            include_cluster_analysis: Whether to include document clustering analysis
            
        Returns:
            dict: Detailed analysis results
        """
        # Build or use the provided lineage graph
        graph = lineage_graph
        if graph is None:
            if record_ids is None:
                raise ValueError("Either lineage_graph or record_ids must be provided")
            graph = self.build_enhanced_cross_document_lineage_graph(
                record_ids=record_ids,
                max_depth=max_depth,
                include_semantic_analysis=include_semantic_analysis
            )
        
        # Initialize analysis results
        analysis = {}
        
        # Basic metrics
        analysis['basic_metrics'] = {
            'node_count': graph.number_of_nodes(),
            'edge_count': graph.number_of_edges(),
            'document_count': len(graph.graph.get('documents', {})),
            'cross_document_edge_count': sum(1 for _, _, attrs in graph.edges(data=True) 
                                           if attrs.get('cross_document', False)),
            'cross_document_ratio': sum(1 for _, _, attrs in graph.edges(data=True) 
                                      if attrs.get('cross_document', False)) / 
                                    max(1, graph.number_of_edges())
        }
        
        # Document boundary analysis
        if 'document_boundaries' in graph.graph:
            analysis['document_boundaries'] = {
                'count': len(graph.graph['document_boundaries']),
                'types': graph.graph.get('boundary_types', {}),
                'cross_boundary_flow_count': graph.graph.get('cross_boundary_flow_count', 0)
            }
        
        # Semantic relationship analysis
        if include_semantic_analysis and 'semantic_relationships' in graph.graph:
            analysis['semantic_relationships'] = {
                'count': len(graph.graph['semantic_relationships']),
                'categories': graph.graph.get('semantic_categories', {}),
                'types': graph.graph.get('relationship_types', {})
            }
        
        # Document cluster analysis
        if include_cluster_analysis and 'document_clusters' in graph.graph:
            analysis['document_clusters'] = {
                'count': len(graph.graph['document_clusters']),
                'clusters': graph.graph['document_clusters'],
                'largest_cluster_size': max(len(cluster) for cluster in graph.graph['document_clusters'].values())
            }
        
        # Impact analysis
        if include_impact_analysis:
            # Add flow metrics
            if 'data_flow_metrics' in graph.graph:
                analysis['data_flow_metrics'] = graph.graph['data_flow_metrics']
                
            # Add boundary impact
            if 'boundary_impact' in graph.graph:
                analysis['boundary_impact'] = graph.graph['boundary_impact']
                
            # Add high-centrality records
            if 'high_centrality_records' in graph.graph:
                analysis['high_centrality_records'] = graph.graph['high_centrality_records']
                
            # Calculate critical paths
            try:
                critical_paths = []
                for node in graph.nodes():
                    if graph.in_degree(node) == 0:  # Source node
                        for target in graph.nodes():
                            if node != target and graph.out_degree(target) == 0:  # Target node
                                if nx.has_path(graph, node, target):
                                    path = nx.shortest_path(graph, node, target)
                                    if len(path) > 2:  # Only include non-trivial paths
                                        critical_paths.append(path)
                
                # Sort paths by length (longest first)
                critical_paths.sort(key=len, reverse=True)
                
                # Keep top 5 paths
                analysis['critical_paths'] = critical_paths[:5]
                analysis['critical_paths_count'] = len(critical_paths)
            except Exception as e:
                logger.warning(f"Error calculating critical paths: {str(e)}")
                
            # Identify hub records (high degree centrality)
            try:
                # Use degree centrality to find hub nodes
                degree_centrality = nx.degree_centrality(graph)
                
                # Get top 10 nodes by degree centrality
                hub_records = sorted(degree_centrality.items(), key=lambda x: x[1], reverse=True)[:10]
                analysis['hub_records'] = [{"id": node, "centrality": centrality} 
                                          for node, centrality in hub_records]
            except Exception as e:
                logger.warning(f"Error identifying hub records: {str(e)}")
        
        # Time analysis
        try:
            # Get timestamps from nodes
            timestamps = []
            for _, attrs in graph.nodes(data=True):
                if 'timestamp' in attrs:
                    try:
                        timestamp = float(attrs['timestamp'])
                        timestamps.append(timestamp)
                    except (ValueError, TypeError):
                        pass
            
            if timestamps:
                earliest = min(timestamps)
                latest = max(timestamps)
                
                time_analysis = {
                    'earliest_timestamp': earliest,
                    'latest_timestamp': latest,
                    'time_span_seconds': latest - earliest,
                    'time_span_days': (latest - earliest) / (24 * 60 * 60)
                }
                
                # Format timestamps for human readability
                time_analysis['earliest_record'] = datetime.datetime.fromtimestamp(earliest).isoformat()
                time_analysis['latest_record'] = datetime.datetime.fromtimestamp(latest).isoformat()
                
                analysis['time_analysis'] = time_analysis
        except Exception as e:
            logger.warning(f"Error performing time analysis: {str(e)}")
        
        return analysis
    
    def export_cross_document_lineage(self, lineage_graph=None, record_ids=None, max_depth=3,
                                    format="json", file_path=None, include_records=False):
        """
        Export cross-document lineage to various formats.
        
        Args:
            lineage_graph: Optional pre-built lineage graph. If None, built from record_ids
            record_ids: Single record ID or list of record IDs to start from (if lineage_graph is None)
            max_depth: Maximum traversal depth (if lineage_graph is None)
            format: Export format ("json", "cytoscape", "graphml", "gexf")
            file_path: If specified, save export to this file
            include_records: Whether to include full record data (caution: can be large)
            
        Returns:
            Export data or None if saved to file
        """
        # Build or use the provided lineage graph
        graph = lineage_graph
        if graph is None:
            if record_ids is None:
                raise ValueError("Either lineage_graph or record_ids must be provided")
            graph = self.build_enhanced_cross_document_lineage_graph(
                record_ids=record_ids,
                max_depth=max_depth
            )
        
        # Export based on format
        if format == "json":
            return self._export_to_json(graph, file_path, include_records)
        elif format == "cytoscape":
            return self._export_to_cytoscape(graph, file_path)
        elif format == "graphml":
            return self._export_to_graphml(graph, file_path)
        elif format == "gexf":
            return self._export_to_gexf(graph, file_path)
        else:
            raise ValueError(f"Unsupported export format: {format}")
    
    def _export_to_json(self, graph, file_path, include_records):
        """Export graph to JSON format."""
        # Convert graph to JSON-compatible format
        data = {
            "nodes": [],
            "edges": [],
            "metadata": {
                "node_count": graph.number_of_nodes(),
                "edge_count": graph.number_of_edges(),
                "document_count": len(graph.graph.get('documents', {})),
                "cross_document_edge_count": sum(1 for _, _, attrs in graph.edges(data=True) 
                                               if attrs.get('cross_document', False))
            }
        }
        
        # Add any additional graph metadata
        for key, value in graph.graph.items():
            # Skip large or complex objects
            if key not in ['nodes', 'edges'] and not isinstance(value, (nx.Graph, nx.DiGraph)):
                try:
                    # Test if serializable
                    json.dumps(value)
                    data["metadata"][key] = value
                except (TypeError, OverflowError):
                    # Convert non-serializable objects to string representation
                    if isinstance(value, dict):
                        data["metadata"][key] = {str(k): str(v) for k, v in value.items()}
                    else:
                        data["metadata"][key] = str(value)
        
        # Add nodes
        for node, attrs in graph.nodes(data=True):
            node_data = {"id": node}
            
            # Include node attributes
            for key, value in attrs.items():
                try:
                    # Test if serializable
                    json.dumps(value)
                    node_data[key] = value
                except (TypeError, OverflowError):
                    # Convert non-serializable objects to string representation
                    node_data[key] = str(value)
            
            # Include full record data if requested
            if include_records and self.storage and node in self.storage.record_cids:
                try:
                    record = self.storage.load_record(self.storage.record_cids[node])
                    if hasattr(record, 'to_dict'):
                        node_data['record_data'] = record.to_dict()
                    else:
                        # Create a basic dictionary of record attributes
                        record_data = {}
                        for attr in dir(record):
                            if not attr.startswith('_') and not callable(getattr(record, attr)):
                                try:
                                    value = getattr(record, attr)
                                    # Try to make serializable
                                    json.dumps(value)
                                    record_data[attr] = value
                                except (TypeError, OverflowError):
                                    record_data[attr] = str(value)
                        node_data['record_data'] = record_data
                except Exception as e:
                    node_data['record_error'] = str(e)
            
            data["nodes"].append(node_data)
        
        # Add edges
        for u, v, attrs in graph.edges(data=True):
            edge_data = {"source": u, "target": v}
            
            # Include edge attributes
            for key, value in attrs.items():
                try:
                    # Test if serializable
                    json.dumps(value)
                    edge_data[key] = value
                except (TypeError, OverflowError):
                    # Convert non-serializable objects to string representation
                    edge_data[key] = str(value)
            
            data["edges"].append(edge_data)
        
        # Save to file or return data
        if file_path:
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2)
            return None
        else:
            return data
    
    def _export_to_cytoscape(self, graph, file_path):
        """Export graph to Cytoscape.js format."""
        data = {
            "elements": {
                "nodes": [],
                "edges": []
            },
            "data": {
                "node_count": graph.number_of_nodes(),
                "edge_count": graph.number_of_edges()
            }
        }
        
        # Add nodes
        for node, attrs in graph.nodes(data=True):
            # Create node data
            node_data = {"data": {"id": node}}
            
            # Add visual properties
            node_data["data"]["label"] = node
            record_type = attrs.get('record_type', 'unknown')
            node_data["data"]["record_type"] = record_type
            
            # Add document info
            if 'document_id' in attrs:
                node_data["data"]["document_id"] = attrs['document_id']
            
            # Add visual style based on record type
            color_map = {
                'source': '#6baed6',  # Blue
                'transformation': '#74c476',  # Green
                'verification': '#fd8d3c',  # Orange
                'query': '#9e9ac8',  # Purple
                'result': '#d62728',  # Red
                'unknown': '#969696'  # Gray
            }
            node_data["data"]["color"] = color_map.get(record_type, '#969696')
            
            # Add other attributes as needed
            for key, value in attrs.items():
                if key not in ['id', 'label', 'record_type', 'document_id', 'color']:
                    try:
                        # Test if serializable
                        json.dumps(value)
                        node_data["data"][key] = value
                    except (TypeError, OverflowError):
                        # Convert non-serializable objects to string representation
                        node_data["data"][key] = str(value)
            
            data["elements"]["nodes"].append(node_data)
        
        # Add edges
        for u, v, attrs in graph.edges(data=True):
            # Create edge data
            edge_data = {"data": {"source": u, "target": v, "id": f"{u}-{v}"}}
            
            # Add edge attributes
            if 'relation' in attrs:
                edge_data["data"]["label"] = attrs['relation']
            
            # Style based on cross-document status
            if attrs.get('cross_document', False):
                edge_data["data"]["color"] = '#1f77b4'  # Blue
                edge_data["data"]["width"] = 2
                edge_data["data"]["style"] = 'dashed'
            else:
                edge_data["data"]["color"] = '#7f7f7f'  # Gray
                edge_data["data"]["width"] = 1
                edge_data["data"]["style"] = 'solid'
                
            # Add boundary status
            if attrs.get('is_boundary', False):
                edge_data["data"]["is_boundary"] = True
                edge_data["data"]["color"] = '#d62728'  # Red
                edge_data["data"]["width"] = 3
            
            # Add other attributes
            for key, value in attrs.items():
                if key not in ['source', 'target', 'id', 'label', 'color', 'width', 'style']:
                    try:
                        # Test if serializable
                        json.dumps(value)
                        edge_data["data"][key] = value
                    except (TypeError, OverflowError):
                        # Convert non-serializable objects to string representation
                        edge_data["data"][key] = str(value)
            
            data["elements"]["edges"].append(edge_data)
        
        # Save to file or return data
        if file_path:
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2)
            return None
        else:
            return data
    
    def _export_to_graphml(self, graph, file_path):
        """Export graph to GraphML format."""
        # Some preparations may be needed for proper GraphML export
        for node in graph.nodes():
            # Ensure attributes are GraphML-compatible
            for key, value in list(graph.nodes[node].items()):
                # GraphML has specific data types
                if isinstance(value, dict) or isinstance(value, list):
                    graph.nodes[node][key] = str(value)
        
        for u, v in graph.edges():
            # Ensure attributes are GraphML-compatible
            for key, value in list(graph.edges[u, v].items()):
                if isinstance(value, dict) or isinstance(value, list):
                    graph.edges[u, v][key] = str(value)
        
        # Save to file or return as string
        if file_path:
            nx.write_graphml(graph, file_path)
            return None
        else:
            import io
            buffer = io.StringIO()
            nx.write_graphml(graph, buffer)
            return buffer.getvalue()
    
    def _export_to_gexf(self, graph, file_path):
        """Export graph to GEXF format."""
        # Some preparations may be needed for proper GEXF export
        for node in graph.nodes():
            # Ensure attributes are GEXF-compatible
            for key, value in list(graph.nodes[node].items()):
                # GEXF has specific data types
                if isinstance(value, dict) or isinstance(value, list):
                    graph.nodes[node][key] = str(value)
        
        for u, v in graph.edges():
            # Ensure attributes are GEXF-compatible
            for key, value in list(graph.edges[u, v].items()):
                if isinstance(value, dict) or isinstance(value, list):
                    graph.edges[u, v][key] = str(value)
        
        # Add visualization attributes
        for node, attrs in graph.nodes(data=True):
            record_type = attrs.get('record_type', 'unknown')
            
            # Add color based on record type
            color_map = {
                'source': (107, 174, 214),  # Blue
                'transformation': (116, 196, 118),  # Green
                'verification': (253, 141, 60),  # Orange
                'query': (158, 154, 200),  # Purple
                'result': (214, 39, 40),  # Red
                'unknown': (150, 150, 150)  # Gray
            }
            
            if record_type in color_map:
                r, g, b = color_map[record_type]
                graph.nodes[node]['viz'] = {
                    'color': {'r': r, 'g': g, 'b': b, 'a': 0.8},
                    'size': 10,
                    'position': {'x': 0, 'y': 0, 'z': 0}  # Will be updated by layout
                }
        
        for u, v, attrs in graph.edges(data=True):
            # Add edge visualization
            if attrs.get('cross_document', False):
                graph.edges[u, v]['viz'] = {
                    'color': {'r': 31, 'g': 119, 'b': 180, 'a': 0.8},  # Blue
                    'thickness': 2,
                    'shape': 'dotted'
                }
            elif attrs.get('is_boundary', False):
                graph.edges[u, v]['viz'] = {
                    'color': {'r': 214, 'g': 39, 'b': 40, 'a': 0.8},  # Red
                    'thickness': 3,
                    'shape': 'dashed'
                }
            else:
                graph.edges[u, v]['viz'] = {
                    'color': {'r': 127, 'g': 127, 'b': 127, 'a': 0.5},  # Gray
                    'thickness': 1,
                    'shape': 'solid'
                }
        
        # Save to file or return as string
        if file_path:
            nx.write_gexf(graph, file_path)
            return None
        else:
            import io
            buffer = io.StringIO()
            nx.write_gexf(graph, buffer)
            return buffer.getvalue()


# Integrator class for connecting data provenance with cross-document lineage
class DetailedLineageIntegrator:
    """
    Integrates data provenance with cross-document lineage tracking.
    
    This class provides comprehensive integration between the EnhancedProvenanceManager
    and cross-document lineage tracking capabilities, enabling:
    - Detailed lineage analysis across document boundaries
    - Comprehensive data flow visualization
    - Semantic relationship enrichment
    - Integrated impact analysis
    - Enhanced reporting and visualization
    """
    
    def __init__(self, provenance_manager, lineage_enhancer):
        """
        Initialize the integrator.
        
        Args:
            provenance_manager: EnhancedProvenanceManager instance
            lineage_enhancer: CrossDocumentLineageEnhancer instance
        """
        self.provenance_manager = provenance_manager
        self.lineage_enhancer = lineage_enhancer
        self.storage = lineage_enhancer.storage if lineage_enhancer else None
        
    def integrate_provenance_with_lineage(self, provenance_graph, lineage_graph=None):
        """
        Integrate provenance graph with cross-document lineage.
        
        This method combines the detailed provenance tracking with cross-document
        lineage information, creating a comprehensive unified lineage graph.
        
        Args:
            provenance_graph: Provenance graph from EnhancedProvenanceManager
            lineage_graph: Optional cross-document lineage graph
            
        Returns:
            nx.DiGraph: Integrated lineage graph
        """
        # If lineage graph not provided, try to build it
        if lineage_graph is None and self.lineage_enhancer:
            # Get all record IDs from provenance graph
            record_ids = list(provenance_graph.nodes())
            if record_ids:
                try:
                    lineage_graph = self.lineage_enhancer.build_enhanced_cross_document_lineage_graph(
                        record_ids=record_ids,
                        max_depth=3  # Default depth
                    )
                except Exception as e:
                    logger.warning(f"Error building lineage graph: {str(e)}")
                    lineage_graph = nx.DiGraph()
        
        # If still no lineage graph, create an empty one
        if lineage_graph is None:
            lineage_graph = nx.DiGraph()
            
        # Create a new graph for integration
        integrated_graph = nx.DiGraph()
        
        # Add nodes and attributes from both graphs
        for graph, source_name in [(provenance_graph, "provenance"), (lineage_graph, "lineage")]:
            for node, attrs in graph.nodes(data=True):
                # Add node if not already present
                if not integrated_graph.has_node(node):
                    integrated_graph.add_node(node, **attrs, source=source_name)
                else:
                    # Merge attributes if node already exists
                    for key, value in attrs.items():
                        if key not in integrated_graph.nodes[node]:
                            integrated_graph.nodes[node][key] = value
                            
                    # Update source information
                    if integrated_graph.nodes[node].get('source') != source_name:
                        integrated_graph.nodes[node]['source'] = "both"
        
        # Add edges and attributes from both graphs
        for graph, source_name in [(provenance_graph, "provenance"), (lineage_graph, "lineage")]:
            for u, v, attrs in graph.edges(data=True):
                # Skip if nodes don't exist in integrated graph (shouldn't happen)
                if not (integrated_graph.has_node(u) and integrated_graph.has_node(v)):
                    continue
                    
                # Add edge if not already present
                if not integrated_graph.has_edge(u, v):
                    integrated_graph.add_edge(u, v, **attrs, source=source_name)
                else:
                    # Merge attributes if edge already exists
                    for key, value in attrs.items():
                        if key not in integrated_graph.edges[u, v]:
                            integrated_graph.edges[u, v][key] = value
                            
                    # Update source information
                    if integrated_graph.edges[u, v].get('source') != source_name:
                        integrated_graph.edges[u, v]['source'] = "both"
        
        # Add graph-level attributes
        integrated_graph.graph.update(provenance_graph.graph)
        
        # Add lineage graph attributes with prefix to avoid collisions
        for key, value in lineage_graph.graph.items():
            if key not in integrated_graph.graph:
                integrated_graph.graph[key] = value
            else:
                integrated_graph.graph[f"lineage_{key}"] = value
                
        # Add integration metadata
        integrated_graph.graph['integration'] = {
            'timestamp': time.time(),
            'provenance_nodes': provenance_graph.number_of_nodes(),
            'provenance_edges': provenance_graph.number_of_edges(),
            'lineage_nodes': lineage_graph.number_of_nodes(),
            'lineage_edges': lineage_graph.number_of_edges(),
            'integrated_nodes': integrated_graph.number_of_nodes(),
            'integrated_edges': integrated_graph.number_of_edges()
        }
        
        return integrated_graph
    
    def enrich_lineage_semantics(self, integrated_graph):
        """
        Enrich the integrated lineage graph with additional semantic information.
        
        This method enhances the integrated graph with:
        - Improved relationship descriptions
        - Data transformation context
        - Process step categorization
        - Confidence scoring for relationships
        
        Args:
            integrated_graph: nx.DiGraph - Integrated lineage graph
            
        Returns:
            nx.DiGraph: Semantically enriched lineage graph
        """
        # Clone the graph to avoid modifying the original
        enriched_graph = integrated_graph.copy()
        
        # Track relationships to enrich
        enriched_relationships = []
        
        # Identify different types of relationships
        for u, v, attrs in enriched_graph.edges(data=True):
            # Base relationship type
            rel_type = attrs.get('relation', 'unknown')
            if 'relation' not in attrs and 'type' in attrs:
                rel_type = attrs['type']
                
            # Source and target record types
            source_type = enriched_graph.nodes[u].get('record_type', 'unknown')
            target_type = enriched_graph.nodes[v].get('record_type', 'unknown')
            
            # Default semantic context
            semantic_context = {}
            
            # Determine semantic relationship category based on record types and relationship
            if source_type == 'source' and target_type == 'transformation':
                semantic_category = "input"
                semantic_context['description'] = f"Data from {u} used as input for transformation {v}"
            elif source_type == 'transformation' and target_type in ['transformation', 'result']:
                semantic_category = "output"
                semantic_context['description'] = f"Transformation {u} produced result {v}"
            elif source_type == 'source' and target_type == 'source':
                semantic_category = "derivation"
                semantic_context['description'] = f"Source {v} derived from source {u}"
            elif source_type == 'verification' and target_type in ['source', 'transformation', 'result']:
                semantic_category = "verification"
                semantic_context['description'] = f"Verification {u} validated {v}"
            elif rel_type in ["derived_from", "transforms", "generates"]:
                semantic_category = "causal"
                semantic_context['description'] = f"{u} causally influences {v}"
            elif rel_type in ["contains", "part_of", "references"]:
                semantic_category = "structural"
                semantic_context['description'] = f"{u} structurally related to {v}"
            elif rel_type in ["precedes", "follows", "concurrent_with"]:
                semantic_category = "temporal"
                semantic_context['description'] = f"{u} temporally related to {v}"
            elif rel_type in ["similar_to", "semantically_related", "contradicts"]:
                semantic_category = "semantic"
                semantic_context['description'] = f"{u} semantically related to {v}"
            else:
                semantic_category = "unknown"
                semantic_context['description'] = f"{u} related to {v}"
                
            # Add semantic category to edge
            enriched_graph.edges[u, v]['semantic_category'] = semantic_category
            
            # Add confidence score if not already present
            if 'confidence' not in attrs:
                # Default high confidence for direct relationships
                confidence = 0.9
                # Lower confidence for inferred relationships
                if attrs.get('source') == 'lineage':
                    confidence = 0.7
                enriched_graph.edges[u, v]['confidence'] = confidence
                
            # Add semantic context if not already present
            if 'semantic_context' not in attrs:
                enriched_graph.edges[u, v]['semantic_context'] = semantic_context
            
            # Add to enriched relationships
            enriched_relationships.append({
                'source': u,
                'target': v,
                'type': rel_type,
                'semantic_category': semantic_category,
                'confidence': enriched_graph.edges[u, v].get('confidence', 0.5),
                'context': semantic_context
            })
        
        # Add enriched relationship information to graph attributes
        enriched_graph.graph['semantic_relationships'] = enriched_relationships
        enriched_graph.graph['semantic_categories'] = {
            cat: len([r for r in enriched_relationships if r['semantic_category'] == cat])
            for cat in set(r['semantic_category'] for r in enriched_relationships)
        }
        
        return enriched_graph
    
    def create_unified_lineage_report(self, integrated_graph=None, record_ids=None, 
                                     include_visualization=True, output_path=None):
        """
        Create a comprehensive unified lineage report.
        
        This method generates a detailed report that combines data provenance
        and cross-document lineage information into a unified view.
        
        Args:
            integrated_graph: nx.DiGraph - Integrated lineage graph (created if None)
            record_ids: IDs to start from if integrated_graph is None
            include_visualization: Whether to include visualization in the report
            output_path: Optional path to save the report
            
        Returns:
            dict: Comprehensive lineage report
        """
        # If no integrated graph provided, create one
        if integrated_graph is None:
            if record_ids is None:
                raise ValueError("Either integrated_graph or record_ids must be provided")
                
            # Get provenance graph
            provenance_graph = self.provenance_manager.get_provenance_graph(record_ids)
            
            # Integrate with lineage
            integrated_graph = self.integrate_provenance_with_lineage(provenance_graph)
            
            # Enrich with semantics
            integrated_graph = self.enrich_lineage_semantics(integrated_graph)
            
        # Initialize report
        report = {
            'generated_at': datetime.datetime.now().isoformat(),
            'record_count': integrated_graph.number_of_nodes(),
            'relationship_count': integrated_graph.number_of_edges(),
            'metadata': dict(integrated_graph.graph)
        }
        
        # Analyze graph structure
        report['structure'] = {
            'node_count': integrated_graph.number_of_nodes(),
            'edge_count': integrated_graph.number_of_edges(),
            'connected_components': nx.number_weakly_connected_components(integrated_graph),
            'diameter': self._safe_diameter(integrated_graph),
            'average_path_length': self._safe_avg_path_length(integrated_graph)
        }
        
        # Document analysis
        if 'documents' in integrated_graph.graph:
            report['documents'] = {
                'count': len(integrated_graph.graph['documents']),
                'details': integrated_graph.graph['documents']
            }
            
        # Cross-document analysis
        if 'document_boundaries' in integrated_graph.graph:
            report['cross_document'] = {
                'boundary_count': len(integrated_graph.graph['document_boundaries']),
                'boundary_types': integrated_graph.graph.get('boundary_types', {}),
                'flow_count': integrated_graph.graph.get('cross_boundary_flow_count', 0)
            }
            
        # Semantic analysis
        if 'semantic_categories' in integrated_graph.graph:
            report['semantics'] = {
                'categories': integrated_graph.graph['semantic_categories'],
                'relationship_types': integrated_graph.graph.get('relationship_types', {})
            }
            
        # Critical nodes analysis
        try:
            # Calculate node centrality
            betweenness = nx.betweenness_centrality(integrated_graph)
            degree = nx.degree_centrality(integrated_graph)
            
            # Find top 5 critical nodes
            critical_nodes = sorted([(node, score) for node, score in betweenness.items()], 
                                  key=lambda x: x[1], reverse=True)[:5]
            
            report['critical_nodes'] = [{
                'id': node,
                'betweenness': score,
                'degree': degree.get(node, 0),
                'record_type': integrated_graph.nodes[node].get('record_type', 'unknown'),
                'document_id': integrated_graph.nodes[node].get('document_id', 'unknown')
            } for node, score in critical_nodes]
        except Exception as e:
            logger.warning(f"Error calculating critical nodes: {str(e)}")
            
        # Data flow analysis
        if 'data_flow_metrics' in integrated_graph.graph:
            report['data_flow'] = integrated_graph.graph['data_flow_metrics']
            
        # Create visualization if requested
        if include_visualization and self.lineage_enhancer:
            try:
                # Generate visualization
                viz_result = self.lineage_enhancer.visualize_enhanced_cross_document_lineage(
                    lineage_graph=integrated_graph,
                    highlight_cross_document=True,
                    highlight_boundaries=True,
                    show_clusters=True,
                    show_metrics=True,
                    file_path=output_path + "_viz.png" if output_path else None,
                    format="png",
                    width=1200,
                    height=800
                )
                
                # Add visualization reference to report
                if output_path:
                    report['visualization_path'] = output_path + "_viz.png"
                else:
                    report['visualization_data'] = viz_result
            except Exception as e:
                logger.warning(f"Error creating visualization: {str(e)}")
                
        # Save report if output path provided
        if output_path:
            try:
                with open(output_path, 'w') as f:
                    json.dump(report, f, indent=2)
            except Exception as e:
                logger.error(f"Error saving report: {str(e)}")
                
        return report
    
    def analyze_data_flow_patterns(self, integrated_graph):
        """
        Analyze data flow patterns in the integrated lineage graph.
        
        This method identifies common data flow patterns, bottlenecks,
        and critical paths in the data lineage.
        
        Args:
            integrated_graph: nx.DiGraph - Integrated lineage graph
            
        Returns:
            dict: Data flow pattern analysis
        """
        # Initialize analysis results
        analysis = {
            'flow_patterns': {},
            'bottlenecks': [],
            'critical_paths': [],
            'parallel_flows': [],
            'cycles': []
        }
        
        # Identify common flow patterns
        pattern_counts = defaultdict(int)
        
        # Analyze all paths of length 3 (source -> process -> target)
        for source in integrated_graph.nodes():
            if integrated_graph.out_degree(source) > 0:
                for mid in integrated_graph.successors(source):
                    if integrated_graph.out_degree(mid) > 0:
                        for target in integrated_graph.successors(mid):
                            # Get node types
                            source_type = integrated_graph.nodes[source].get('record_type', 'unknown')
                            mid_type = integrated_graph.nodes[mid].get('record_type', 'unknown')
                            target_type = integrated_graph.nodes[target].get('record_type', 'unknown')
                            
                            # Create pattern key
                            pattern = f"{source_type}->{mid_type}->{target_type}"
                            pattern_counts[pattern] += 1
        
        # Keep top 5 patterns
        top_patterns = sorted(pattern_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        analysis['flow_patterns'] = {pattern: count for pattern, count in top_patterns}
        
        # Identify bottlenecks (nodes with high in-degree and out-degree)
        bottlenecks = []
        for node in integrated_graph.nodes():
            in_deg = integrated_graph.in_degree(node)
            out_deg = integrated_graph.out_degree(node)
            
            if in_deg > 1 and out_deg > 1:
                bottleneck_score = in_deg * out_deg
                bottlenecks.append((node, in_deg, out_deg, bottleneck_score))
                
        # Sort by bottleneck score and keep top 5
        bottlenecks.sort(key=lambda x: x[3], reverse=True)
        analysis['bottlenecks'] = [{
            'id': node,
            'in_degree': in_deg,
            'out_degree': out_deg,
            'bottleneck_score': score,
            'record_type': integrated_graph.nodes[node].get('record_type', 'unknown'),
            'document_id': integrated_graph.nodes[node].get('document_id', 'unknown')
        } for node, in_deg, out_deg, score in bottlenecks[:5]]
        
        # Identify critical paths (longest paths in the graph)
        critical_paths = []
        
        # Find source and sink nodes
        sources = [n for n in integrated_graph.nodes() if integrated_graph.in_degree(n) == 0]
        sinks = [n for n in integrated_graph.nodes() if integrated_graph.out_degree(n) == 0]
        
        # Find all paths between sources and sinks
        for source in sources:
            for sink in sinks:
                try:
                    # Find all simple paths (limited to prevent exponential explosion)
                    for path in nx.all_simple_paths(integrated_graph, source, sink, cutoff=10):
                        if len(path) > 2:  # Only consider non-trivial paths
                            critical_paths.append((path, len(path)))
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    continue
                    
        # Sort by path length and keep top 5
        critical_paths.sort(key=lambda x: x[1], reverse=True)
        analysis['critical_paths'] = [{
            'path': path,
            'length': length,
            'path_types': [integrated_graph.nodes[n].get('record_type', 'unknown') for n in path]
        } for path, length in critical_paths[:5]]
        
        # Identify parallel flows (similar paths between same endpoints)
        parallel_groups = defaultdict(list)
        
        for path, _ in critical_paths:
            if len(path) < 2:
                continue
                
            # Group by source and target
            key = (path[0], path[-1])
            parallel_groups[key].append(path)
            
        # Keep groups with multiple paths
        for (source, target), paths in parallel_groups.items():
            if len(paths) > 1:
                analysis['parallel_flows'].append({
                    'source': source,
                    'target': target,
                    'path_count': len(paths),
                    'paths': paths
                })
                
        # Identify cycles (potential feedback loops)
        try:
            cycles = list(nx.simple_cycles(integrated_graph))
            # Keep cycles of reasonable size
            cycles = [c for c in cycles if 2 <= len(c) <= 10]
            
            analysis['cycles'] = [{
                'cycle': cycle,
                'length': len(cycle),
                'cycle_types': [integrated_graph.nodes[n].get('record_type', 'unknown') for n in cycle]
            } for cycle in cycles[:5]]  # Limit to top 5
        except:
            # Simple cycles only works in directed graphs
            pass
            
        return analysis
    
    def track_document_lineage_evolution(self, document_id, time_range=None):
        """
        Track the evolution of document lineage over time.
        
        This method analyzes how the lineage of a document has evolved
        over time, identifying key changes and patterns.
        
        Args:
            document_id: ID of the document to analyze
            time_range: Optional tuple of (start_time, end_time) as timestamps
            
        Returns:
            dict: Document lineage evolution analysis
        """
        # Initialize evolution tracking
        evolution = {
            'document_id': document_id,
            'time_range': time_range,
            'timeline': [],
            'growth_metrics': {},
            'relationship_evolution': {},
            'key_events': []
        }
        
        # Get all records associated with the document
        document_records = []
        if self.storage:
            for record_id, cid in self.storage.record_cids.items():
                try:
                    record = self.storage.load_record(cid)
                    if hasattr(record, 'metadata') and isinstance(record.metadata, dict):
                        if record.metadata.get('document_id') == document_id:
                            # Get record timestamp
                            timestamp = record.metadata.get('timestamp', 0)
                            if hasattr(record, 'timestamp'):
                                timestamp = record.timestamp
                                
                            # Apply time range filter if provided
                            if time_range:
                                start_time, end_time = time_range
                                if timestamp < start_time or timestamp > end_time:
                                    continue
                                    
                            document_records.append((record_id, timestamp, record))
                except Exception as e:
                    logger.warning(f"Error loading record {record_id}: {str(e)}")
        
        # Sort records by timestamp
        document_records.sort(key=lambda x: x[1])
        
        # Create timeline of document evolution
        current_records = set()
        current_relationships = defaultdict(int)
        
        for i, (record_id, timestamp, record) in enumerate(document_records):
            current_records.add(record_id)
            
            # Build lineage graph at this point in time
            if self.lineage_enhancer:
                try:
                    lineage_graph = self.lineage_enhancer.build_enhanced_cross_document_lineage_graph(
                        record_ids=list(current_records),
                        max_depth=2
                    )
                    
                    # Count relationship types
                    for _, _, attrs in lineage_graph.edges(data=True):
                        rel_type = attrs.get('relation', 'unknown')
                        current_relationships[rel_type] += 1
                        
                    # Create timeline entry
                    timeline_entry = {
                        'timestamp': timestamp,
                        'formatted_time': datetime.datetime.fromtimestamp(timestamp).isoformat(),
                        'record_count': len(current_records),
                        'relationship_count': lineage_graph.number_of_edges(),
                        'cross_document_edges': sum(1 for _, _, attrs in lineage_graph.edges(data=True) 
                                                  if attrs.get('cross_document', False)),
                        'relationship_types': dict(current_relationships)
                    }
                    
                    # Identify key events (significant changes)
                    is_key_event = False
                    reason = None
                    
                    if i == 0:
                        is_key_event = True
                        reason = "First record in document"
                    elif i == len(document_records) - 1:
                        is_key_event = True
                        reason = "Latest record in document"
                    elif timeline_entry.get('cross_document_edges', 0) > 0 and i > 0 and evolution['timeline'][i-1].get('cross_document_edges', 0) == 0:
                        is_key_event = True
                        reason = "First cross-document link established"
                        
                    timeline_entry['is_key_event'] = is_key_event
                    if reason:
                        timeline_entry['key_event_reason'] = reason
                        
                    evolution['timeline'].append(timeline_entry)
                    
                    # Track key events separately
                    if is_key_event:
                        key_event = dict(timeline_entry)
                        key_event['record_id'] = record_id
                        evolution['key_events'].append(key_event)
                except Exception as e:
                    logger.warning(f"Error building lineage graph at timestamp {timestamp}: {str(e)}")
        
        # Calculate growth metrics
        if evolution['timeline']:
            first = evolution['timeline'][0]
            last = evolution['timeline'][-1]
            
            evolution['growth_metrics'] = {
                'duration_seconds': last['timestamp'] - first['timestamp'],
                'record_growth': last['record_count'] - first['record_count'],
                'relationship_growth': last['relationship_count'] - first['relationship_count'],
                'records_per_day': (last['record_count'] - first['record_count']) / 
                                  max(1, (last['timestamp'] - first['timestamp']) / (24 * 3600))
            }
            
            # Track relationship type evolution
            all_rel_types = set()
            for entry in evolution['timeline']:
                all_rel_types.update(entry.get('relationship_types', {}).keys())
                
            for rel_type in all_rel_types:
                evolution['relationship_evolution'][rel_type] = [
                    entry.get('relationship_types', {}).get(rel_type, 0)
                    for entry in evolution['timeline']
                ]
                
        return evolution
        
    def _safe_diameter(self, graph):
        """Calculate graph diameter safely."""
        try:
            # Convert to undirected for diameter calculation
            undirected = graph.to_undirected()
            if nx.is_connected(undirected):
                return nx.diameter(undirected)
            else:
                # Get diameter of largest component
                largest_cc = max(nx.connected_components(undirected), key=len)
                subgraph = undirected.subgraph(largest_cc)
                return nx.diameter(subgraph)
        except Exception as e:
            logger.debug(f"Error calculating diameter: {str(e)}")
            return -1  # Indicate calculation failure
            
    def _safe_avg_path_length(self, graph):
        """Calculate average path length safely."""
        try:
            # Convert to undirected for path length calculation
            undirected = graph.to_undirected()
            if nx.is_connected(undirected):
                return nx.average_shortest_path_length(undirected)
            else:
                # Calculate for largest component
                largest_cc = max(nx.connected_components(undirected), key=len)
                subgraph = undirected.subgraph(largest_cc)
                return nx.average_shortest_path_length(subgraph)
        except Exception as e:
            logger.debug(f"Error calculating average path length: {str(e)}")
            return -1  # Indicate calculation failure


# Helper class for analyzing data transformation impact across document boundaries
class CrossDocumentImpactAnalyzer:
    """
    Analyzes the impact of data transformations across document boundaries.
    
    This class helps identify and visualize how changes in one document
    affect other documents, measuring cross-document dependencies and
    impact propagation.
    """
    
    def __init__(self, storage):
        """
        Initialize the impact analyzer.
        
        Args:
            storage: IPLDProvenanceStorage instance
        """
        self.storage = storage
        
    def analyze_impact(self, source_id, max_depth=3):
        """
        Analyze the impact of a record across document boundaries.
        
        Args:
            source_id: ID of the record to analyze impact for
            max_depth: Maximum traversal depth
            
        Returns:
            dict: Impact analysis results
        """
        # Build the lineage graph starting from the source record
        graph = self.storage.build_cross_document_lineage_graph(
            record_ids=[source_id],
            max_depth=max_depth
        )
        
        # Initialize impact results
        impact = {
            'source_id': source_id,
            'source_document': None,
            'impacted_documents': {},
            'impact_paths': [],
            'impact_metrics': {}
        }
        
        # Get source document
        for node, attrs in graph.nodes(data=True):
            if node == source_id and 'document_id' in attrs:
                impact['source_document'] = attrs['document_id']
                break
        
        # Find all paths from the source
        downstream_nodes = set()
        for node in graph.nodes():
            if node != source_id and nx.has_path(graph, source_id, node):
                downstream_nodes.add(node)
                
                # Record the path
                path = nx.shortest_path(graph, source_id, node)
                if len(path) > 1:
                    # Get document IDs along the path
                    doc_path = []
                    for path_node in path:
                        doc_id = graph.nodes[path_node].get('document_id')
                        if doc_id:
                            doc_path.append(doc_id)
                    
                    # Add path information
                    path_info = {
                        'path': path,
                        'document_path': doc_path,
                        'length': len(path),
                        'crosses_document': len(set(doc_path)) > 1
                    }
                    
                    impact['impact_paths'].append(path_info)
        
        # Count impacts by document
        doc_counts = defaultdict(int)
        for node in downstream_nodes:
            doc_id = graph.nodes[node].get('document_id')
            if doc_id and doc_id != impact['source_document']:
                doc_counts[doc_id] += 1
        
        # Format document impacts
        for doc_id, count in doc_counts.items():
            impact['impacted_documents'][doc_id] = {
                'impacted_nodes': count,
                'impact_paths': [p for p in impact['impact_paths'] 
                              if doc_id in p['document_path']]
            }
        
        # Calculate impact metrics
        impact['impact_metrics'] = {
            'total_impacted_nodes': len(downstream_nodes),
            'impacted_document_count': len(doc_counts),
            'max_path_length': max([p['length'] for p in impact['impact_paths']], default=0),
            'cross_document_paths': len([p for p in impact['impact_paths'] if p['crosses_document']])
        }
        
        # Calculate impact score (0-1)
        if graph.number_of_nodes() > 1:
            impact['impact_metrics']['impact_score'] = len(downstream_nodes) / (graph.number_of_nodes() - 1)
        else:
            impact['impact_metrics']['impact_score'] = 0
            
        return impact
    
    def visualize_impact(self, source_id, max_depth=3, file_path=None, format="png"):
        """
        Visualize the impact of a record across document boundaries.
        
        Args:
            source_id: ID of the record to analyze impact for
            max_depth: Maximum traversal depth
            file_path: If specified, save visualization to this file
            format: Output format
            
        Returns:
            Visualization result or None if saved to file
        """
        # Build the lineage graph starting from the source record
        graph = self.storage.build_cross_document_lineage_graph(
            record_ids=[source_id],
            max_depth=max_depth
        )
        
        # Get source document
        source_doc = None
        for node, attrs in graph.nodes(data=True):
            if node == source_id and 'document_id' in attrs:
                source_doc = attrs['document_id']
                break
                
        # Create impact visualization
        plt.figure(figsize=(12, 8), dpi=100)
        
        # Determine node positions
        pos = nx.spring_layout(graph, seed=42)
        
        # Draw nodes with colors based on impact status
        downstream_nodes = set()
        for node in graph.nodes():
            if node != source_id and nx.has_path(graph, source_id, node):
                downstream_nodes.add(node)
        
        # Color nodes by impact status
        node_colors = []
        for node in graph.nodes():
            if node == source_id:
                node_colors.append('red')  # Source node
            elif node in downstream_nodes:
                doc_id = graph.nodes[node].get('document_id')
                if doc_id and doc_id != source_doc:
                    node_colors.append('orange')  # Cross-document impact
                else:
                    node_colors.append('yellow')  # Same-document impact
            else:
                node_colors.append('lightgray')  # Not impacted
        
        # Draw nodes
        nx.draw_networkx_nodes(
            graph, pos, 
            node_color=node_colors,
            node_size=100,
            alpha=0.8
        )
        
        # Draw edges with colors showing impact paths
        edge_colors = []
        for u, v in graph.edges():
            if u == source_id or (u in downstream_nodes and nx.has_path(graph, source_id, u)):
                if nx.has_path(graph, source_id, v):
                    # Edge is part of an impact path
                    u_doc = graph.nodes[u].get('document_id')
                    v_doc = graph.nodes[v].get('document_id')
                    if u_doc != v_doc:
                        edge_colors.append('red')  # Cross-document impact edge
                    else:
                        edge_colors.append('orange')  # Same-document impact edge
                else:
                    edge_colors.append('gray')  # Not in impact path
            else:
                edge_colors.append('lightgray')  # Not in impact path
                
        # Draw edges
        nx.draw_networkx_edges(
            graph, pos,
            edge_color=edge_colors,
            width=1.5,
            alpha=0.7
        )
        
        # Draw node labels
        nx.draw_networkx_labels(
            graph, pos,
            labels={node: node for node in graph.nodes()},
            font_size=8,
            font_color='black'
        )
        
        # Add legend and title
        plt.title(f"Impact Analysis for {source_id}")
        legend_elements = [
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='red', markersize=10, label='Source Node'),
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='orange', markersize=10, label='Cross-Doc Impact'),
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='yellow', markersize=10, label='Same-Doc Impact'),
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='lightgray', markersize=10, label='Not Impacted')
        ]
        plt.legend(handles=legend_elements, loc='upper right')
        plt.axis('off')
        
        # Add impact metrics
        impact = self.analyze_impact(source_id, max_depth)
        metrics_text = [
            f"Impacted Nodes: {impact['impact_metrics']['total_impacted_nodes']}",
            f"Impacted Documents: {impact['impact_metrics']['impacted_document_count']}",
            f"Impact Score: {impact['impact_metrics']['impact_score']:.2f}",
            f"Cross-Doc Paths: {impact['impact_metrics']['cross_document_paths']}"
        ]
        plt.figtext(0.01, 0.01, '\n'.join(metrics_text), fontsize=10,
                   bbox=dict(facecolor='white', alpha=0.8))
        
        # Save or return based on format
        if file_path:
            plt.savefig(file_path, format=format, bbox_inches='tight')
            plt.close()
            return None
        elif format == 'svg':
            from io import BytesIO
            import base64
            
            buffer = BytesIO()
            plt.savefig(buffer, format='svg', bbox_inches='tight')
            plt.close()
            svg_content = buffer.getvalue().decode('utf-8')
            return svg_content
        else:
            from io import BytesIO
            import base64
            
            buffer = BytesIO()
            plt.savefig(buffer, format=format, bbox_inches='tight')
            plt.close()
            image_data = base64.b64encode(buffer.getvalue()).decode('utf-8')
            return image_data