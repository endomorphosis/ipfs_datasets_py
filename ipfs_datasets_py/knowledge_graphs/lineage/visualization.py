"""
Lineage graph visualization.

Provides visualization capabilities for lineage graphs using NetworkX
and optionally Plotly for interactive visualizations.
"""

import logging
from typing import Dict, List, Any, Optional
import io

from .core import LineageGraph, LineageTracker

logger = logging.getLogger(__name__)

# Try to import visualization libraries
try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    plt = None

try:
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False
    go = None


class LineageVisualizer:
    """
    Main visualization class for lineage graphs.
    
    Supports both NetworkX/Matplotlib (static) and Plotly (interactive).
    """
    
    def __init__(self, graph: LineageGraph):
        """
        Initialize visualizer.
        
        Args:
            graph: LineageGraph to visualize
        """
        self.graph = graph
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert graph to dictionary format suitable for visualization.
        
        Returns:
            Dictionary with nodes and edges
        """
        nodes = []
        for node_id, node in self.graph._nodes.items():
            nodes.append({
                'id': node_id,
                'type': node.node_type,
                'metadata': node.metadata,
                'timestamp': node.timestamp
            })
        
        edges = []
        for link_id, link in self.graph._links.items():
            edges.append({
                'source': link.source_id,
                'target': link.target_id,
                'type': link.relationship_type,
                'confidence': link.confidence,
                'metadata': link.metadata
            })
        
        return {
            'nodes': nodes,
            'edges': edges,
            'stats': {
                'node_count': self.graph.node_count,
                'link_count': self.graph.link_count
            }
        }
    
    def render_networkx(
        self,
        output_path: Optional[str] = None,
        layout: str = 'spring',
        figsize: tuple = (12, 8)
    ) -> Optional[bytes]:
        """
        Render graph using NetworkX and Matplotlib.
        
        Args:
            output_path: Optional path to save figure
            layout: Layout algorithm ('spring', 'circular', 'hierarchical')
            figsize: Figure size (width, height)
            
        Returns:
            PNG bytes if output_path is None, otherwise None
        """
        if not MATPLOTLIB_AVAILABLE:
            raise ImportError("Matplotlib required for NetworkX rendering")
        
        import networkx as nx
        
        # Create figure
        fig, ax = plt.subplots(figsize=figsize)
        
        # Choose layout
        if layout == 'spring':
            pos = nx.spring_layout(self.graph._graph)
        elif layout == 'circular':
            pos = nx.circular_layout(self.graph._graph)
        elif layout == 'hierarchical':
            pos = nx.kamada_kawai_layout(self.graph._graph)
        else:
            pos = nx.spring_layout(self.graph._graph)
        
        # Draw nodes
        node_colors = []
        for node_id in self.graph._graph.nodes():
            node = self.graph.get_node(node_id)
            if node:
                # Color by node type
                if node.node_type == 'dataset':
                    node_colors.append('lightblue')
                elif node.node_type == 'transformation':
                    node_colors.append('lightgreen')
                else:
                    node_colors.append('lightgray')
            else:
                node_colors.append('lightgray')
        
        nx.draw_networkx_nodes(
            self.graph._graph, pos,
            node_color=node_colors,
            node_size=500,
            ax=ax
        )
        
        # Draw edges
        nx.draw_networkx_edges(
            self.graph._graph, pos,
            edge_color='gray',
            arrows=True,
            ax=ax
        )
        
        # Draw labels
        nx.draw_networkx_labels(
            self.graph._graph, pos,
            font_size=8,
            ax=ax
        )
        
        ax.set_title('Lineage Graph')
        ax.axis('off')
        
        plt.tight_layout()
        
        if output_path:
            plt.savefig(output_path, dpi=150, bbox_inches='tight')
            plt.close()
            return None
        else:
            # Return as bytes
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
            plt.close()
            buf.seek(0)
            return buf.read()
    
    def render_plotly(
        self,
        output_path: Optional[str] = None
    ) -> Optional[str]:
        """
        Render interactive graph using Plotly.
        
        Args:
            output_path: Optional path to save HTML
            
        Returns:
            HTML string if output_path is None, otherwise None
        """
        if not PLOTLY_AVAILABLE:
            raise ImportError("Plotly required for interactive rendering")
        
        import networkx as nx
        
        # Get layout
        pos = nx.spring_layout(self.graph._graph)
        
        # Create edge traces
        edge_traces = []
        for edge in self.graph._graph.edges():
            x0, y0 = pos[edge[0]]
            x1, y1 = pos[edge[1]]
            
            edge_trace = go.Scatter(
                x=[x0, x1, None],
                y=[y0, y1, None],
                mode='lines',
                line=dict(width=1, color='#888'),
                hoverinfo='none',
                showlegend=False
            )
            edge_traces.append(edge_trace)
        
        # Create node trace
        node_x = []
        node_y = []
        node_text = []
        node_colors = []
        
        for node_id in self.graph._graph.nodes():
            x, y = pos[node_id]
            node_x.append(x)
            node_y.append(y)
            
            node = self.graph.get_node(node_id)
            if node:
                node_text.append(f"{node_id}<br>Type: {node.node_type}")
                # Color by type
                if node.node_type == 'dataset':
                    node_colors.append('blue')
                elif node.node_type == 'transformation':
                    node_colors.append('green')
                else:
                    node_colors.append('gray')
            else:
                node_text.append(node_id)
                node_colors.append('gray')
        
        node_trace = go.Scatter(
            x=node_x, y=node_y,
            mode='markers+text',
            text=[n.split('<br>')[0] for n in node_text],
            textposition='top center',
            hovertext=node_text,
            hoverinfo='text',
            marker=dict(
                size=15,
                color=node_colors,
                line=dict(width=2, color='white')
            ),
            showlegend=False
        )
        
        # Create figure
        fig = go.Figure(
            data=edge_traces + [node_trace],
            layout=go.Layout(
                title='Interactive Lineage Graph',
                showlegend=False,
                hovermode='closest',
                margin=dict(b=0, l=0, r=0, t=40),
                xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                height=600
            )
        )
        
        if output_path:
            fig.write_html(output_path)
            return None
        else:
            return fig.to_html()


def visualize_lineage(
    tracker: LineageTracker,
    output_path: Optional[str] = None,
    renderer: str = 'networkx',
    **kwargs
) -> Optional[Any]:
    """
    Convenient function to visualize a lineage tracker.
    
    Args:
        tracker: LineageTracker instance
        output_path: Optional path to save visualization
        renderer: Rendering engine ('networkx' or 'plotly')
        **kwargs: Additional arguments for renderer
        
    Returns:
        Visualization result (bytes, HTML, or None if saved to file)
    """
    visualizer = LineageVisualizer(tracker.graph)
    
    if renderer == 'networkx':
        return visualizer.render_networkx(output_path=output_path, **kwargs)
    elif renderer == 'plotly':
        return visualizer.render_plotly(output_path=output_path)
    else:
        raise ValueError(f"Unknown renderer: {renderer}")
