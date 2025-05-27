"""
Provenance Dashboard Module

This module provides a dashboard for visualizing data provenance information,
including data lineage, transformation history, and integration with audit and
RAG query visualization systems.
"""

import os
import json
import time
import logging
import datetime
from typing import Dict, List, Any, Optional, Tuple, Union, Callable
from pathlib import Path
import base64
import io

# Add UTC import to fix deprecation warnings
# Python 3.11+ supports datetime.UTC directly, older versions need to use timezone.utc
try:
    from datetime import UTC  # Python 3.11+
except ImportError:
    from datetime import timezone
    UTC = timezone.utc

try:
    import numpy as np
    import pandas as pd
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import MaxNLocator
    import seaborn as sns
    import networkx as nx
    VISUALIZATION_LIBS_AVAILABLE = True
except ImportError:
    VISUALIZATION_LIBS_AVAILABLE = False

try:
    import plotly.graph_objects as go
    import plotly.express as px
    from plotly.subplots import make_subplots
    INTERACTIVE_VISUALIZATION_AVAILABLE = True
except ImportError:
    INTERACTIVE_VISUALIZATION_AVAILABLE = False

try:
    from jinja2 import Template
    TEMPLATE_ENGINE_AVAILABLE = True
except ImportError:
    TEMPLATE_ENGINE_AVAILABLE = False

# Import related modules
from ipfs_datasets_py.data_provenance import ProvenanceManager
from ipfs_datasets_py.cross_document_lineage import EnhancedLineageTracker
from ipfs_datasets_py.rag_query_visualization import RAGQueryVisualizer


class ProvenanceDashboard:
    """
    Dashboard for data provenance visualization and analysis.
    
    This class creates an interactive dashboard for exploring data provenance
    information, including lineage graphs, audit events, and integration with
    RAG query metrics.
    """
    
    def __init__(
        self,
        provenance_manager: ProvenanceManager,
        lineage_tracker: Optional[EnhancedLineageTracker] = None,
        query_visualizer: Optional[RAGQueryVisualizer] = None
    ):
        """
        Initialize the provenance dashboard.
        
        Args:
            provenance_manager: ProvenanceManager for tracking data provenance
            lineage_tracker: Optional EnhancedLineageTracker for cross-document lineage
            query_visualizer: Optional RAGQueryVisualizer for RAG query metrics
        """
        self.provenance_manager = provenance_manager
        self.lineage_tracker = lineage_tracker
        self.query_visualizer = query_visualizer
        self.visualization_available = VISUALIZATION_LIBS_AVAILABLE
        self.interactive_visualization_available = INTERACTIVE_VISUALIZATION_AVAILABLE
        self.template_engine_available = TEMPLATE_ENGINE_AVAILABLE
    
    def visualize_data_lineage(
        self,
        data_ids: List[str],
        max_depth: int = 5,
        include_parameters: bool = True,
        show_timestamps: bool = True,
        output_file: Optional[str] = None,
        return_base64: bool = False,
        interactive: bool = False
    ) -> Optional[str]:
        """
        Visualize data lineage for specified data entities.
        
        Args:
            data_ids: List of data entity IDs to visualize
            max_depth: Maximum depth to trace back
            include_parameters: Whether to include operation parameters
            show_timestamps: Whether to show timestamps
            output_file: Optional path to save the visualization
            return_base64: Whether to return the image as base64
            interactive: Whether to create an interactive visualization
            
        Returns:
            str: Base64-encoded image or None if visualization not available
        """
        if not self.visualization_available:
            logging.warning("Visualization libraries not available")
            return None
        
        if interactive and not self.interactive_visualization_available:
            logging.warning("Interactive visualization not available, falling back to static")
            interactive = False
        
        # For non-interactive visualization, use the provenance manager's built-in method
        if not interactive:
            return self.provenance_manager.visualize_provenance(
                data_ids=data_ids,
                max_depth=max_depth,
                include_parameters=include_parameters,
                show_timestamps=show_timestamps,
                file_path=output_file,
                return_base64=return_base64
            )
        
        # Interactive visualization using Plotly
        try:
            # Extract the provenance subgraph for the specified data entities
            subgraph_nodes = set()
            for data_id in data_ids:
                lineage = self.provenance_manager.get_data_lineage(data_id, max_depth=max_depth)
                
                # Helper function to extract nodes from lineage
                def extract_nodes(lin, depth=0):
                    if depth > max_depth:
                        return
                    
                    if 'record_id' in lin:
                        subgraph_nodes.add(lin['record_id'])
                    
                    for parent in lin.get('parents', []):
                        extract_nodes(parent, depth + 1)
                
                extract_nodes(lineage)
            
            # Create a subgraph with these nodes
            subgraph = self.provenance_manager.graph.subgraph(subgraph_nodes)
            
            # Create an interactive Plotly figure
            pos = nx.spring_layout(subgraph, seed=42)
            
            # Prepare node traces by type
            node_types = {}
            for node in subgraph.nodes():
                node_type = subgraph.nodes[node].get('record_type', 'unknown')
                if node_type not in node_types:
                    node_types[node_type] = []
                node_types[node_type].append(node)
            
            # Define node colors
            color_map = {
                'source': 'lightblue',
                'transformation': 'lightgreen',
                'merge': 'orange',
                'query': 'lightcoral',
                'result': 'yellow',
                'checkpoint': 'purple',
                'data_entity': 'gray',
                'unknown': 'white'
            }
            
            fig = go.Figure()
            
            # Add nodes for each type
            for node_type, nodes in node_types.items():
                color = color_map.get(node_type, 'white')
                
                # Extract position and prepare hover text
                x = [pos[node][0] for node in nodes]
                y = [pos[node][1] for node in nodes]
                
                text = []
                for node in nodes:
                    # Get node data for hover text
                    node_data = subgraph.nodes[node]
                    description = node_data.get('description', '')
                    timestamp = node_data.get('timestamp', '')
                    
                    if timestamp:
                        timestamp_str = datetime.datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
                    else:
                        timestamp_str = ''
                    
                    # Build hover text
                    hover_text = f"ID: {node}<br>Type: {node_type}<br>"
                    if description:
                        hover_text += f"Description: {description}<br>"
                    if timestamp_str:
                        hover_text += f"Time: {timestamp_str}<br>"
                    
                    text.append(hover_text)
                
                # Add node trace
                fig.add_trace(go.Scatter(
                    x=x, y=y,
                    mode='markers',
                    marker=dict(
                        size=15,
                        color=color,
                        line=dict(width=1, color='black')
                    ),
                    text=text,
                    hoverinfo='text',
                    name=node_type
                ))
            
            # Add edges
            edge_x = []
            edge_y = []
            edge_text = []
            
            for edge in subgraph.edges():
                x0, y0 = pos[edge[0]]
                x1, y1 = pos[edge[1]]
                
                # Add line coordinates and None for separation
                edge_x.extend([x0, x1, None])
                edge_y.extend([y0, y1, None])
                
                # Get edge type if available
                edge_type = subgraph.edges[edge].get('type', 'unknown')
                edge_text.append(f"From: {edge[0]}<br>To: {edge[1]}<br>Type: {edge_type}")
            
            # Add edge trace
            fig.add_trace(go.Scatter(
                x=edge_x, y=edge_y,
                mode='lines',
                line=dict(width=1, color='gray'),
                hoverinfo='text',
                text=edge_text,
                name='connections'
            ))
            
            # Configure layout
            fig.update_layout(
                title=f"Data Lineage for {', '.join(data_ids[:3])}{' and others' if len(data_ids) > 3 else ''}",
                showlegend=True,
                hovermode='closest',
                margin=dict(b=20, l=5, r=5, t=40),
                xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                height=600,
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1
                )
            )
            
            # Save as HTML if output_file is provided
            if output_file:
                fig.write_html(output_file)
            
            # If return_base64 is True, convert to base64
            if return_base64:
                buffer = io.StringIO()
                fig.write_html(buffer)
                html_string = buffer.getvalue()
                return base64.b64encode(html_string.encode()).decode()
            
            return output_file if output_file else None
        
        except Exception as e:
            logging.error(f"Error creating interactive lineage visualization: {str(e)}")
            import traceback
            logging.error(traceback.format_exc())
            
            # Fall back to static visualization
            return self.provenance_manager.visualize_provenance(
                data_ids=data_ids,
                max_depth=max_depth,
                include_parameters=include_parameters,
                show_timestamps=show_timestamps,
                file_path=output_file,
                return_base64=return_base64
            )
    
    def visualize_cross_document_lineage(
        self,
        document_ids: List[str],
        relationship_types: Optional[List[str]] = None,
        max_depth: int = 3,
        output_file: Optional[str] = None,
        return_base64: bool = False,
        interactive: bool = False
    ) -> Optional[str]:
        """
        Visualize cross-document lineage relationships.
        
        Args:
            document_ids: List of document IDs to visualize
            relationship_types: Optional filter for relationship types
            max_depth: Maximum depth for relationship traversal
            output_file: Optional path to save the visualization
            return_base64: Whether to return the image as base64
            interactive: Whether to create an interactive visualization
            
        Returns:
            str: Base64-encoded image or None if visualization not available
        """
        if not self.lineage_tracker:
            logging.warning("EnhancedLineageTracker not available for cross-document lineage visualization")
            return None
        
        if not self.visualization_available:
            logging.warning("Visualization libraries not available")
            return None
        
        if interactive and not self.interactive_visualization_available:
            logging.warning("Interactive visualization not available, falling back to static")
            interactive = False
        
        try:
            # Get lineage graph from the tracker
            lineage_graph = self.lineage_tracker.get_lineage_subgraph(
                document_ids=document_ids,
                relationship_types=relationship_types,
                max_depth=max_depth
            )
            
            if not lineage_graph or lineage_graph.number_of_nodes() == 0:
                logging.warning("No lineage data available for visualization")
                return None
            
            if not interactive:
                # Create static visualization
                plt.figure(figsize=(12, 10))
                
                # Use a hierarchical layout for the graph
                pos = nx.spring_layout(lineage_graph, seed=42)
                
                # Define node colors by type
                node_colors = []
                for node in lineage_graph.nodes():
                    node_type = lineage_graph.nodes[node].get('type', 'unknown')
                    if node_type == 'document':
                        color = 'lightblue'
                    elif node_type == 'source':
                        color = 'lightgreen'
                    elif node_type == 'dataset':
                        color = 'orange'
                    elif node_type == 'model':
                        color = 'purple'
                    else:
                        color = 'gray'
                    node_colors.append(color)
                
                # Define edge colors by type
                edge_colors = []
                for source, target, data in lineage_graph.edges(data=True):
                    relationship_type = data.get('type', 'unknown')
                    if relationship_type == 'derives_from':
                        color = 'blue'
                    elif relationship_type == 'cites':
                        color = 'green'
                    elif relationship_type == 'includes':
                        color = 'orange'
                    elif relationship_type == 'references':
                        color = 'red'
                    else:
                        color = 'gray'
                    edge_colors.append(color)
                
                # Draw the graph
                nx.draw_networkx_nodes(lineage_graph, pos, node_color=node_colors, 
                                     alpha=0.8, node_size=500)
                
                # Draw edges with arrows
                nx.draw_networkx_edges(lineage_graph, pos, edge_color=edge_colors, 
                                     arrows=True, width=1.5, alpha=0.7)
                
                # Prepare and draw labels
                node_labels = {}
                for node in lineage_graph.nodes():
                    node_data = lineage_graph.nodes[node]
                    node_label = node_data.get('name', str(node))
                    # Truncate long labels
                    if len(node_label) > 20:
                        node_label = node_label[:17] + '...'
                    node_labels[node] = node_label
                
                nx.draw_networkx_labels(lineage_graph, pos, labels=node_labels, font_size=8)
                
                # Add a legend
                legend_elements = [
                    plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='lightblue', 
                             markersize=10, label='Document'),
                    plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='lightgreen', 
                             markersize=10, label='Source'),
                    plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='orange', 
                             markersize=10, label='Dataset'),
                    plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='purple', 
                             markersize=10, label='Model'),
                    plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='gray', 
                             markersize=10, label='Other')
                ]
                
                plt.legend(handles=legend_elements, loc='upper right')
                plt.title('Cross-Document Lineage Graph', fontsize=14)
                plt.axis('off')
                
                # Save or return the plot
                if output_file:
                    plt.savefig(output_file, bbox_inches='tight')
                    plt.close()
                    return output_file
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
            
            else:
                # Interactive visualization with Plotly
                # Position nodes using networkx layout
                pos = nx.spring_layout(lineage_graph, seed=42)
                
                # Prepare node traces by type
                node_types = {}
                for node in lineage_graph.nodes():
                    node_type = lineage_graph.nodes[node].get('type', 'unknown')
                    if node_type not in node_types:
                        node_types[node_type] = []
                    node_types[node_type].append(node)
                
                # Define node colors
                color_map = {
                    'document': 'lightblue',
                    'source': 'lightgreen',
                    'dataset': 'orange',
                    'model': 'purple',
                    'unknown': 'gray'
                }
                
                fig = go.Figure()
                
                # Add nodes for each type
                for node_type, nodes in node_types.items():
                    color = color_map.get(node_type, 'gray')
                    
                    # Extract position and prepare hover text
                    x = [pos[node][0] for node in nodes]
                    y = [pos[node][1] for node in nodes]
                    
                    text = []
                    for node in nodes:
                        # Get node data for hover text
                        node_data = lineage_graph.nodes[node]
                        name = node_data.get('name', str(node))
                        created = node_data.get('created_at', '')
                        
                        # Build hover text
                        hover_text = f"ID: {node}<br>Type: {node_type}<br>Name: {name}<br>"
                        if created:
                            hover_text += f"Created: {created}<br>"
                        
                        text.append(hover_text)
                    
                    # Add node trace
                    fig.add_trace(go.Scatter(
                        x=x, y=y,
                        mode='markers',
                        marker=dict(
                            size=15,
                            color=color,
                            line=dict(width=1, color='black')
                        ),
                        text=text,
                        hoverinfo='text',
                        name=node_type
                    ))
                
                # Group edges by relationship type
                edge_types = {}
                for u, v, data in lineage_graph.edges(data=True):
                    rel_type = data.get('type', 'unknown')
                    if rel_type not in edge_types:
                        edge_types[rel_type] = []
                    edge_types[rel_type].append((u, v, data))
                
                # Define edge colors
                edge_color_map = {
                    'derives_from': 'blue',
                    'cites': 'green',
                    'includes': 'orange',
                    'references': 'red',
                    'unknown': 'gray'
                }
                
                # Add edges by type
                for edge_type, edges in edge_types.items():
                    edge_x = []
                    edge_y = []
                    edge_text = []
                    color = edge_color_map.get(edge_type, 'gray')
                    
                    for u, v, data in edges:
                        x0, y0 = pos[u]
                        x1, y1 = pos[v]
                        
                        # Add line coordinates and None for separation
                        edge_x.extend([x0, x1, None])
                        edge_y.extend([y0, y1, None])
                        
                        # Prepare hover text
                        source_name = lineage_graph.nodes[u].get('name', str(u))
                        target_name = lineage_graph.nodes[v].get('name', str(v))
                        
                        hover_text = f"From: {source_name}<br>To: {target_name}<br>Type: {edge_type}<br>"
                        
                        if 'metadata' in data:
                            for key, value in data['metadata'].items():
                                hover_text += f"{key}: {value}<br>"
                        
                        edge_text.append(hover_text)
                    
                    # Add edge trace
                    fig.add_trace(go.Scatter(
                        x=edge_x, y=edge_y,
                        mode='lines',
                        line=dict(width=1.5, color=color),
                        hoverinfo='text',
                        text=edge_text,
                        name=edge_type
                    ))
                
                # Configure layout
                fig.update_layout(
                    title='Cross-Document Lineage Graph',
                    showlegend=True,
                    hovermode='closest',
                    margin=dict(b=20, l=5, r=5, t=40),
                    xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                    yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                    height=600,
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.02,
                        xanchor="right",
                        x=1
                    )
                )
                
                # Save as HTML if output_file is provided
                if output_file:
                    fig.write_html(output_file)
                
                # If return_base64 is True, convert to base64
                if return_base64:
                    buffer = io.StringIO()
                    fig.write_html(buffer)
                    html_string = buffer.getvalue()
                    return base64.b64encode(html_string.encode()).decode()
                
                return output_file if output_file else None
        
        except Exception as e:
            logging.error(f"Error creating cross-document lineage visualization: {str(e)}")
            import traceback
            logging.error(traceback.format_exc())
            return None
    
    def generate_provenance_report(
        self,
        data_ids: List[str],
        format: str = "html",
        include_lineage_graph: bool = True,
        include_audit_events: bool = True,
        include_query_metrics: bool = True,
        output_file: Optional[str] = None
    ) -> Optional[str]:
        """
        Generate a comprehensive provenance report for specified data entities.
        
        Args:
            data_ids: List of data entity IDs to include in the report
            format: Report format ('html', 'md', 'json')
            include_lineage_graph: Whether to include lineage graph visualization
            include_audit_events: Whether to include related audit events
            include_query_metrics: Whether to include related query metrics
            output_file: Optional path to save the report
            
        Returns:
            str: Report content or file path if output_file is specified
        """
        if format == 'html' and not self.template_engine_available:
            logging.warning("Template engine not available, falling back to markdown")
            format = 'md'
        
        # Get provenance data for each entity
        entity_data = {}
        for data_id in data_ids:
            try:
                lineage = self.provenance_manager.get_data_lineage(data_id, max_depth=10)
                entity_data[data_id] = lineage
            except Exception as e:
                logging.error(f"Error getting lineage for {data_id}: {str(e)}")
                entity_data[data_id] = {"error": str(e)}
        
        # Generate lineage graph if requested
        lineage_graph = None
        if include_lineage_graph and self.visualization_available:
            try:
                lineage_graph = self.visualize_data_lineage(
                    data_ids=data_ids,
                    return_base64=True
                )
            except Exception as e:
                logging.error(f"Error generating lineage graph: {str(e)}")
        
        # Get cross-document lineage if available
        cross_doc_lineage = None
        if self.lineage_tracker and include_lineage_graph and self.visualization_available:
            try:
                cross_doc_lineage = self.visualize_cross_document_lineage(
                    document_ids=data_ids,
                    return_base64=True
                )
            except Exception as e:
                logging.error(f"Error generating cross-document lineage: {str(e)}")
        
        # Generate audit report if available
        audit_report = None
        if include_audit_events:
            try:
                audit_report = self.provenance_manager.generate_audit_report(
                    data_ids=data_ids,
                    format=format,
                    include_parameters=True
                )
            except Exception as e:
                logging.error(f"Error generating audit report: {str(e)}")
        
        # Get query metrics if available and requested
        query_metrics = None
        if include_query_metrics and self.query_visualizer:
            try:
                # This is a simplification, in practice we would filter metrics by data IDs
                query_metrics = self.query_visualizer.metrics.get_performance_metrics()
            except Exception as e:
                logging.error(f"Error getting query metrics: {str(e)}")
        
        # Generate report in the requested format
        if format == 'json':
            report = {
                'data_ids': data_ids,
                'entity_data': entity_data,
                'generated_at': datetime.datetime.now(UTC).isoformat() + 'Z',
                'lineage_graph': lineage_graph,
                'cross_document_lineage': cross_doc_lineage,
                'audit_report': audit_report,
                'query_metrics': query_metrics
            }
            
            if output_file:
                with open(output_file, 'w') as f:
                    json.dump(report, f, indent=2)
                return output_file
            else:
                return json.dumps(report, indent=2)
            
        elif format == 'html':
            # Create HTML template
            template_string = """
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Data Provenance Report</title>
                <style>
                    body {
                        font-family: Arial, sans-serif;
                        line-height: 1.6;
                        color: #333;
                        max-width: 1200px;
                        margin: 0 auto;
                        padding: 20px;
                    }
                    h1, h2, h3, h4 {
                        color: #1a5276;
                    }
                    .header {
                        margin-bottom: 30px;
                        border-bottom: 1px solid #ddd;
                        padding-bottom: 10px;
                    }
                    .section {
                        margin-bottom: 30px;
                        padding-bottom: 20px;
                        border-bottom: 1px solid #eee;
                    }
                    .lineage-graph {
                        margin: 20px 0;
                        border: 1px solid #ddd;
                        padding: 10px;
                        background-color: #f9f9f9;
                        text-align: center;
                    }
                    .lineage-graph img {
                        max-width: 100%;
                        height: auto;
                    }
                    table {
                        border-collapse: collapse;
                        width: 100%;
                        margin: 20px 0;
                    }
                    th, td {
                        border: 1px solid #ddd;
                        padding: 8px 12px;
                        text-align: left;
                    }
                    th {
                        background-color: #f2f2f2;
                    }
                    tr:nth-child(even) {
                        background-color: #f9f9f9;
                    }
                    .metadata {
                        font-size: 0.9em;
                        color: #666;
                    }
                    .record {
                        margin: 15px 0;
                        padding: 10px;
                        border: 1px solid #ddd;
                        border-radius: 4px;
                    }
                    .record h4 {
                        margin-top: 0;
                    }
                    .source {
                        background-color: #e6f3ff;
                    }
                    .transformation {
                        background-color: #e6ffe6;
                    }
                    .merge {
                        background-color: #fff5e6;
                    }
                    .query {
                        background-color: #ffe6e6;
                    }
                    .result {
                        background-color: #fffee6;
                    }
                    .checkpoint {
                        background-color: #f2e6ff;
                    }
                    .metrics {
                        display: grid;
                        grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
                        gap: 15px;
                        margin: 20px 0;
                    }
                    .metric-card {
                        background-color: #f5f5f5;
                        padding: 15px;
                        border-radius: 4px;
                        text-align: center;
                    }
                    .metric-card h4 {
                        margin-top: 0;
                        font-size: 14px;
                    }
                    .metric-card p {
                        font-size: 24px;
                        font-weight: bold;
                        margin: 5px 0;
                    }
                    .footer {
                        margin-top: 30px;
                        text-align: center;
                        font-size: 0.8em;
                        color: #777;
                    }
                    pre {
                        background-color: #f8f8f8;
                        padding: 10px;
                        border-radius: 4px;
                        overflow-x: auto;
                    }
                    code {
                        font-family: monospace;
                    }
                    .text-center {
                        text-align: center;
                    }
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>Data Provenance Report</h1>
                    <p class="metadata">
                        Generated: {{ generated_at }}<br>
                        Data IDs: {{ data_ids|join(', ') }}
                    </p>
                </div>
                
                <div class="section">
                    <h2>Data Lineage Overview</h2>
                    
                    {% if lineage_graph %}
                    <div class="lineage-graph">
                        <h3>Provenance Graph</h3>
                        <img src="data:image/png;base64,{{ lineage_graph }}" alt="Data Lineage Graph">
                    </div>
                    {% else %}
                    <p class="text-center">Lineage graph not available.</p>
                    {% endif %}
                    
                    {% if cross_doc_lineage %}
                    <div class="lineage-graph">
                        <h3>Cross-Document Lineage</h3>
                        <img src="data:image/png;base64,{{ cross_doc_lineage }}" alt="Cross-Document Lineage">
                    </div>
                    {% else %}
                    <p class="text-center">Cross-document lineage not available.</p>
                    {% endif %}
                </div>
                
                <div class="section">
                    <h2>Detailed Provenance Records</h2>
                    
                    {% for data_id, lineage in entity_data.items() %}
                    <h3>Entity: {{ data_id }}</h3>
                    
                    {% if lineage.error %}
                    <p>Error: {{ lineage.error }}</p>
                    {% else %}
                    
                    <div class="record {{ lineage.record.record_type|lower }}">
                        <h4>{{ lineage.record.record_type|capitalize }}</h4>
                        <p><strong>ID:</strong> {{ lineage.record_id }}</p>
                        <p><strong>Description:</strong> {{ lineage.record.description }}</p>
                        <p><strong>Time:</strong> {{ lineage.record.timestamp|format_timestamp }}</p>
                        
                        {% if lineage.record.parameters %}
                        <h4>Parameters:</h4>
                        <pre><code>{{ lineage.record.parameters|format_json }}</code></pre>
                        {% endif %}
                        
                        {% if lineage.record.metadata %}
                        <h4>Metadata:</h4>
                        <pre><code>{{ lineage.record.metadata|format_json }}</code></pre>
                        {% endif %}
                    </div>
                    
                    {% if lineage.parents %}
                    <h4>Parent Records:</h4>
                    {% for parent in lineage.parents %}
                    <div class="record {{ parent.record.record_type|lower }}">
                        <h4>{{ parent.record.record_type|capitalize }}</h4>
                        <p><strong>ID:</strong> {{ parent.record_id }}</p>
                        <p><strong>Description:</strong> {{ parent.record.description }}</p>
                        <p><strong>Time:</strong> {{ parent.record.timestamp|format_timestamp }}</p>
                        
                        {% if parent.record.parameters %}
                        <h4>Parameters:</h4>
                        <pre><code>{{ parent.record.parameters|format_json }}</code></pre>
                        {% endif %}
                    </div>
                    {% endfor %}
                    {% endif %}
                    
                    {% endif %}
                    {% endfor %}
                </div>
                
                {% if query_metrics %}
                <div class="section">
                    <h2>Related Query Metrics</h2>
                    
                    <div class="metrics">
                        <div class="metric-card">
                            <h4>Total Queries</h4>
                            <p>{{ query_metrics.total_queries }}</p>
                        </div>
                        <div class="metric-card">
                            <h4>Avg Duration</h4>
                            <p>{{ query_metrics.avg_duration|round(2) }}s</p>
                        </div>
                        <div class="metric-card">
                            <h4>Success Rate</h4>
                            <p>{{ (query_metrics.success_rate * 100)|round(1) }}%</p>
                        </div>
                        <div class="metric-card">
                            <h4>Error Rate</h4>
                            <p>{{ (query_metrics.error_rate * 100)|round(1) }}%</p>
                        </div>
                    </div>
                    
                    {% if query_metrics.performance_by_type %}
                    <h3>Performance by Query Type</h3>
                    <table>
                        <thead>
                            <tr>
                                <th>Query Type</th>
                                <th>Count</th>
                                <th>Avg Duration (s)</th>
                                <th>Success Rate</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for query_type, stats in query_metrics.performance_by_type.items() %}
                            <tr>
                                <td>{{ query_type }}</td>
                                <td>{{ stats.count }}</td>
                                <td>{{ stats.avg_duration|round(3) }}</td>
                                <td>{{ (stats.success_rate * 100)|round(1) }}%</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                    {% endif %}
                </div>
                {% endif %}
                
                {% if audit_report %}
                <div class="section">
                    <h2>Audit Trail</h2>
                    {{ audit_report|safe }}
                </div>
                {% endif %}
                
                <div class="footer">
                    <p>Generated by ProvenanceDashboard | IPFS Datasets Python</p>
                </div>
            </body>
            </html>
            """
            
            # Define filter functions
            def format_timestamp(timestamp):
                if isinstance(timestamp, (int, float)):
                    return datetime.datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
                return timestamp
            
            def format_json(data):
                if not data:
                    return "{}"
                return json.dumps(data, indent=2)
            
            # Render the template
            template = Template(template_string)
            template.globals['format_timestamp'] = format_timestamp
            template.globals['format_json'] = format_json
            
            html = template.render(
                data_ids=data_ids,
                entity_data=entity_data,
                generated_at=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                lineage_graph=lineage_graph,
                cross_doc_lineage=cross_doc_lineage,
                audit_report=audit_report,
                query_metrics=query_metrics
            )
            
            if output_file:
                with open(output_file, 'w') as f:
                    f.write(html)
                return output_file
            else:
                return html
            
        else:  # Markdown format
            md_lines = ["# Data Provenance Report", ""]
            md_lines.append(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            md_lines.append(f"Data IDs: {', '.join(data_ids)}")
            md_lines.append("")
            
            # Add data lineage section
            md_lines.append("## Data Lineage Overview")
            md_lines.append("")
            if lineage_graph:
                md_lines.append("Lineage graph is available in the HTML version of this report.")
            else:
                md_lines.append("Lineage graph not available.")
            md_lines.append("")
            
            # Add detailed provenance records
            md_lines.append("## Detailed Provenance Records")
            md_lines.append("")
            
            for data_id, lineage in entity_data.items():
                md_lines.append(f"### Entity: {data_id}")
                md_lines.append("")
                
                if "error" in lineage:
                    md_lines.append(f"Error: {lineage['error']}")
                    md_lines.append("")
                    continue
                
                # Main record
                record = lineage.get("record", {})
                record_type = record.get("record_type", "Unknown").capitalize()
                md_lines.append(f"**Record Type:** {record_type}")
                md_lines.append(f"**ID:** {lineage.get('record_id', 'Unknown')}")
                md_lines.append(f"**Description:** {record.get('description', 'No description')}")
                
                timestamp = record.get("timestamp")
                if timestamp:
                    time_str = datetime.datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
                    md_lines.append(f"**Time:** {time_str}")
                
                # Parameters if available
                params = record.get("parameters")
                if params:
                    md_lines.append("\n**Parameters:**")
                    md_lines.append("```json")
                    md_lines.append(json.dumps(params, indent=2))
                    md_lines.append("```")
                
                md_lines.append("")
                
                # Parent records
                parents = lineage.get("parents", [])
                if parents:
                    md_lines.append("#### Parent Records:")
                    md_lines.append("")
                    
                    for parent in parents:
                        parent_record = parent.get("record", {})
                        parent_type = parent_record.get("record_type", "Unknown").capitalize()
                        md_lines.append(f"**Record Type:** {parent_type}")
                        md_lines.append(f"**ID:** {parent.get('record_id', 'Unknown')}")
                        md_lines.append(f"**Description:** {parent_record.get('description', 'No description')}")
                        
                        parent_timestamp = parent_record.get("timestamp")
                        if parent_timestamp:
                            parent_time_str = datetime.datetime.fromtimestamp(parent_timestamp).strftime('%Y-%m-%d %H:%M:%S')
                            md_lines.append(f"**Time:** {parent_time_str}")
                        
                        md_lines.append("")
                
                md_lines.append("")
            
            # Add query metrics if available
            if query_metrics:
                md_lines.append("## Related Query Metrics")
                md_lines.append("")
                md_lines.append(f"**Total Queries:** {query_metrics.get('total_queries', 0)}")
                md_lines.append(f"**Avg Duration:** {round(query_metrics.get('avg_duration', 0), 2)}s")
                md_lines.append(f"**Success Rate:** {round(query_metrics.get('success_rate', 0) * 100, 1)}%")
                md_lines.append(f"**Error Rate:** {round(query_metrics.get('error_rate', 0) * 100, 1)}%")
                md_lines.append("")
                
                # Add performance by query type
                performance_by_type = query_metrics.get('performance_by_type', {})
                if performance_by_type:
                    md_lines.append("### Performance by Query Type")
                    md_lines.append("")
                    md_lines.append("| Query Type | Count | Avg Duration (s) | Success Rate |")
                    md_lines.append("|------------|-------|-----------------|-------------|")
                    
                    for query_type, stats in performance_by_type.items():
                        count = stats.get('count', 0)
                        avg_duration = round(stats.get('avg_duration', 0), 3)
                        success_rate = round(stats.get('success_rate', 0) * 100, 1)
                        md_lines.append(f"| {query_type} | {count} | {avg_duration} | {success_rate}% |")
                    
                    md_lines.append("")
            
            # Add audit report if available (as is, since it's already in markdown format)
            if audit_report and format == 'md':
                md_lines.append("## Audit Trail")
                md_lines.append("")
                md_lines.append(audit_report)
            
            # Combine all lines
            markdown = "\n".join(md_lines)
            
            if output_file:
                with open(output_file, 'w') as f:
                    f.write(markdown)
                return output_file
            else:
                return markdown
    
    def create_integrated_dashboard(
        self,
        output_dir: str,
        data_ids: Optional[List[str]] = None,
        include_audit: bool = True,
        include_query: bool = True,
        include_cross_doc: bool = True,
        dashboard_name: str = "provenance_dashboard.html"
    ) -> str:
        """
        Create an integrated dashboard with provenance, audit, and query metrics.
        
        Args:
            output_dir: Directory to save the dashboard files
            data_ids: Optional list of data IDs to focus on, None for all
            include_audit: Whether to include audit metrics
            include_query: Whether to include query metrics
            include_cross_doc: Whether to include cross-document lineage
            dashboard_name: Name of the main dashboard HTML file
            
        Returns:
            str: Path to the main dashboard file
        """
        if not self.template_engine_available:
            logging.error("Template engine not available, cannot create dashboard")
            return None
        
        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        
        # Generate report for entity-specific data
        dashboard_path = os.path.join(output_dir, dashboard_name)
        
        # If no data_ids specified, use recent entities
        if not data_ids:
            # Get the most recent entities (up to 10)
            recent_entities = self._get_recent_entities(10)
            if recent_entities:
                data_ids = recent_entities
            else:
                # Fallback to empty list
                data_ids = []
        
        # Generate lineage visualizations
        lineage_path = None
        if data_ids and VISUALIZATION_LIBS_AVAILABLE:
            try:
                lineage_path = os.path.join(output_dir, "data_lineage.png")
                self.visualize_data_lineage(
                    data_ids=data_ids,
                    max_depth=5,
                    output_file=lineage_path
                )
            except Exception as e:
                logging.error(f"Error generating lineage visualization: {str(e)}")
                lineage_path = None
        
        # Generate cross-document lineage if requested
        cross_doc_path = None
        if include_cross_doc and self.lineage_tracker and data_ids and VISUALIZATION_LIBS_AVAILABLE:
            try:
                cross_doc_path = os.path.join(output_dir, "cross_doc_lineage.png")
                self.visualize_cross_document_lineage(
                    document_ids=data_ids,
                    output_file=cross_doc_path
                )
            except Exception as e:
                logging.error(f"Error generating cross-document lineage: {str(e)}")
                cross_doc_path = None
        
        # Generate query metrics visualizations if requested
        query_performance_path = None
        if include_query and self.query_visualizer:
            try:
                query_performance_path = os.path.join(output_dir, "query_performance.png")
                self.query_visualizer.plot_query_performance(
                    output_file=query_performance_path
                )
            except Exception as e:
                logging.error(f"Error generating query performance visualization: {str(e)}")
                query_performance_path = None
        
        # Generate integrated query-audit timeline if both are available
        timeline_path = None
        if include_audit and include_query and self.query_visualizer:
            try:
                from ipfs_datasets_py.audit.audit_visualization import create_query_audit_timeline
                
                # Get audit metrics if available
                try:
                    from ipfs_datasets_py.audit.audit_visualization import AuditMetricsAggregator
                    audit_metrics = getattr(self, 'audit_metrics', None)
                    
                    if audit_metrics and isinstance(audit_metrics, AuditMetricsAggregator):
                        timeline_path = os.path.join(output_dir, "query_audit_timeline.png")
                        create_query_audit_timeline(
                            query_metrics_collector=self.query_visualizer.metrics,
                            audit_metrics=audit_metrics,
                            output_file=timeline_path
                        )
                except ImportError:
                    logging.warning("Audit visualization components not available")
            except Exception as e:
                logging.error(f"Error generating integrated timeline: {str(e)}")
                timeline_path = None
        
        # Generate provenance report
        try:
            self.generate_provenance_report(
                data_ids=data_ids,
                format="html",
                include_lineage_graph=True,
                include_audit_events=include_audit,
                include_query_metrics=include_query,
                output_file=dashboard_path
            )
        except Exception as e:
            logging.error(f"Error generating provenance report: {str(e)}")
            # Create a simple fallback dashboard
            with open(dashboard_path, 'w') as f:
                f.write(f"""<!DOCTYPE html>
                <html>
                <head>
                    <title>Provenance Dashboard</title>
                </head>
                <body>
                    <h1>Provenance Dashboard</h1>
                    <p>Error generating full report: {str(e)}</p>
                    
                    {f'<h2>Data Lineage</h2><img src="data_lineage.png" alt="Data Lineage">' if lineage_path else ''}
                    {f'<h2>Cross-Document Lineage</h2><img src="cross_doc_lineage.png" alt="Cross-Document Lineage">' if cross_doc_path else ''}
                    {f'<h2>Query Performance</h2><img src="query_performance.png" alt="Query Performance">' if query_performance_path else ''}
                    {f'<h2>Query-Audit Timeline</h2><img src="query_audit_timeline.png" alt="Query-Audit Timeline">' if timeline_path else ''}
                </body>
                </html>""")
        
        return dashboard_path
    
    def _get_recent_entities(self, limit: int = 10) -> List[str]:
        """
        Get the most recent data entities from the provenance manager.
        
        Args:
            limit: Maximum number of entities to return
            
        Returns:
            List[str]: List of recent entity IDs
        """
        # Get all entities with their latest record timestamps
        entities = {}
        for entity_id, record_id in self.provenance_manager.entity_latest_record.items():
            if record_id in self.provenance_manager.records:
                record = self.provenance_manager.records[record_id]
                entities[entity_id] = record.timestamp
        
        # Sort by timestamp (newest first) and take the top 'limit' entities
        sorted_entities = sorted(entities.items(), key=lambda x: x[1], reverse=True)[:limit]
        
        return [entity_id for entity_id, _ in sorted_entities]


def setup_provenance_dashboard(
    provenance_manager: Optional[ProvenanceManager] = None,
    lineage_tracker: Optional[Any] = None,
    query_metrics: Optional[Any] = None,
    audit_metrics: Optional[Any] = None
) -> ProvenanceDashboard:
    """
    Set up a provenance dashboard with all available components.
    
    Args:
        provenance_manager: Optional ProvenanceManager instance
        lineage_tracker: Optional EnhancedLineageTracker instance
        query_metrics: Optional QueryMetricsCollector instance
        audit_metrics: Optional AuditMetricsAggregator instance
        
    Returns:
        ProvenanceDashboard: Configured dashboard instance
    """
    # Create provenance manager if not provided
    if not provenance_manager:
        try:
            provenance_manager = ProvenanceManager()
        except Exception as e:
            logging.error(f"Error creating provenance manager: {str(e)}")
            provenance_manager = None
    
    # Create lineage tracker if not provided and available
    if not lineage_tracker:
        try:
            from ipfs_datasets_py.cross_document_lineage import EnhancedLineageTracker
            lineage_tracker = EnhancedLineageTracker()
        except ImportError:
            logging.warning("EnhancedLineageTracker not available")
            lineage_tracker = None
        except Exception as e:
            logging.error(f"Error creating lineage tracker: {str(e)}")
            lineage_tracker = None
    
    # Create query visualizer if not provided but query metrics is available
    query_visualizer = None
    if query_metrics:
        try:
            from ipfs_datasets_py.rag_query_visualization import RAGQueryVisualizer
            query_visualizer = RAGQueryVisualizer(query_metrics)
        except ImportError:
            logging.warning("RAGQueryVisualizer not available")
        except Exception as e:
            logging.error(f"Error creating query visualizer: {str(e)}")
    
    # Create dashboard instance
    dashboard = ProvenanceDashboard(
        provenance_manager=provenance_manager,
        lineage_tracker=lineage_tracker,
        query_visualizer=query_visualizer
    )
    
    # Store audit metrics if provided
    if audit_metrics:
        dashboard.audit_metrics = audit_metrics
    
    return dashboard