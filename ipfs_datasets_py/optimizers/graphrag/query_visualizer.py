"""Query visualization tools for GraphRAG query optimization."""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

# Optional numpy dependency used for chart positioning and color spacing.
try:
    import numpy as np
except ImportError:
    class _MockNumpy:
        @staticmethod
        def linspace(start: float, stop: float, num: int):
            if num <= 1:
                return [start]
            step = (stop - start) / (num - 1)
            return [start + i * step for i in range(num)]

        @staticmethod
        def arange(n: int):
            return list(range(n))

    np = _MockNumpy()

if TYPE_CHECKING:
    from matplotlib.figure import Figure
else:
    class Figure:  # pragma: no cover
        pass

try:
    import matplotlib.pyplot as plt
    import networkx as nx
    VISUALIZATION_AVAILABLE = True
except ImportError:
    VISUALIZATION_AVAILABLE = False

from ipfs_datasets_py.optimizers.graphrag.query_metrics import QueryMetricsCollector


class QueryVisualizer:
    """
    Provides visualization capabilities for GraphRAG query analysis.
    
    This class generates visualizations for query execution plans, performance metrics,
    and traversal patterns. It helps in analyzing query performance, identifying bottlenecks,
    and comparing different optimization strategies.
    
    Key features:
    - Query execution plan visualization
    - Performance breakdown charts
    - Time-series resource utilization graphs
    - Graph traversal pattern visualization
    - Comparative analysis between query strategies
    - Interactive plots (when used in notebook environments)
    - Export to various image formats
    """
    
    def __init__(self, metrics_collector: Optional[QueryMetricsCollector] = None):
        """
        Initialize the query visualizer.
        
        Args:
            metrics_collector (QueryMetricsCollector, optional): Metrics collector to visualize data from
        """
        self.metrics_collector = metrics_collector
        self.visualization_available = VISUALIZATION_AVAILABLE
        
        if not self.visualization_available:
            print("Warning: Visualization dependencies not available. "
                  "Install matplotlib and networkx for visualization support.")
    
    def set_metrics_collector(self, metrics_collector: QueryMetricsCollector) -> None:
        """
        Set the metrics collector to use for visualizations.
        
        Args:
            metrics_collector (QueryMetricsCollector): Metrics collector instance
        """
        self.metrics_collector = metrics_collector
    
    def visualize_phase_timing(
        self, 
        query_id: Optional[str] = None, 
        title: str = "Query Phase Timing",
        show_plot: bool = True,
        output_file: Optional[str] = None,
        figsize: Tuple[int, int] = (10, 6)
    ) -> Optional[Figure]:
        """
        Visualize the timing breakdown of query phases.
        
        Args:
            query_id (str, optional): Specific query ID to visualize, or None for all queries
            title (str): Plot title
            show_plot (bool): Whether to display the plot
            output_file (str, optional): Path to save the plot image
            figsize (Tuple[int, int]): Figure size (width, height) in inches
            
        Returns:
            matplotlib.figure.Figure or None: The figure object if visualization is available
        """
        if not self.visualization_available:
            print("Visualization dependencies not available. Install matplotlib and networkx.")
            return None
            
        if self.metrics_collector is None:
            print("No metrics collector set. Use set_metrics_collector() first.")
            return None
            
        # Get phase timing summary
        phase_timing = self.metrics_collector.get_phase_timing_summary(query_id)
        
        if not phase_timing:
            print("No phase timing data available.")
            return None
            
        # Create plot
        fig, ax = plt.subplots(figsize=figsize)
        
        # Sort phases by average duration (descending)
        sorted_phases = sorted(
            [(phase, data["avg_duration"]) for phase, data in phase_timing.items()],
            key=lambda x: x[1],
            reverse=True
        )
        
        # Prepare data for bar chart
        phases = [p[0] for p in sorted_phases]
        durations = [p[1] for p in sorted_phases]
        
        # Create bars with sequential colors
        colormap = plt.cm.viridis
        colors = [colormap(i) for i in np.linspace(0, 0.9, len(phases))]
        
        # Create horizontal bar chart for better readability of long phase names
        bars = ax.barh(phases, durations, color=colors)
        
        # Add value labels on bars
        for i, bar in enumerate(bars):
            width = bar.get_width()
            label_x_pos = width * 1.01
            ax.text(label_x_pos, bar.get_y() + bar.get_height()/2, f"{width:.3f}s",
                    va='center', color='black', fontsize=8)
        
        # Add labels and title
        ax.set_xlabel('Duration (seconds)')
        ax.set_title(title)
        ax.grid(axis='x', linestyle='--', alpha=0.7)
        
        # Adjust layout for better readability
        plt.tight_layout()
        
        # Save if output file specified
        if output_file:
            plt.savefig(output_file, dpi=300, bbox_inches='tight')
            
        # Show plot if requested
        if show_plot:
            plt.show()
        else:
            plt.close(fig)
            
        return fig
    
    def visualize_query_plan(
        self,
        query_plan: Dict[str, Any],
        title: str = "Query Execution Plan",
        show_plot: bool = True,
        output_file: Optional[str] = None,
        figsize: Tuple[int, int] = (12, 8)
    ) -> Optional[Figure]:
        """
        Visualize a query execution plan as a directed graph.
        
        Args:
            query_plan (Dict): Query execution plan to visualize
            title (str): Plot title
            show_plot (bool): Whether to display the plot
            output_file (str, optional): Path to save the plot image
            figsize (Tuple[int, int]): Figure size (width, height) in inches
            
        Returns:
            matplotlib.figure.Figure or None: The figure object if visualization is available
        """
        if not self.visualization_available:
            print("Visualization dependencies not available. Install matplotlib and networkx.")
            return None
            
        # Create a directed graph from the query plan
        G = nx.DiGraph()
        
        # Extract nodes and edges from query plan
        # This is a simplistic implementation - actual extraction will depend on query plan structure
        # The following assumes a structure with phases and dependencies
        
        # Get phases if available or use a simplified structure
        phases = query_plan.get("phases", {})
        if not phases and "steps" in query_plan:
            # Alternative structure with steps
            phases = {f"step_{i}": step for i, step in enumerate(query_plan["steps"])}
        
        if not phases:
            print("Query plan does not contain recognizable phases or steps.")
            return None
            
        # Add nodes (phases)
        for phase_id, phase_data in phases.items():
            # Extract node attributes
            label = phase_data.get("name", phase_id)
            duration = phase_data.get("duration", None)
            node_type = phase_data.get("type", "unknown")
            
            # Create node with attributes
            G.add_node(
                phase_id,
                label=label,
                duration=duration,
                type=node_type
            )
            
            # Add edges (dependencies)
            dependencies = phase_data.get("dependencies", [])
            for dep in dependencies:
                G.add_edge(dep, phase_id)
                
        # If no edges added and we have an ordered plan, create sequential edges
        if len(G.edges()) == 0 and len(G.nodes()) > 1:
            sorted_phases = sorted(phases.keys())  # Use order in dict or explicit sorting if available
            for i in range(len(sorted_phases) - 1):
                G.add_edge(sorted_phases[i], sorted_phases[i + 1])
        
        # Create plot
        fig, ax = plt.subplots(figsize=figsize)
        
        # Define node positions using layout algorithm
        pos = nx.spring_layout(G, seed=42)  # Consistent layout with fixed seed
        
        # Define node colors based on type or other criteria
        node_types = nx.get_node_attributes(G, 'type')
        type_colors = {
            "vector_search": "skyblue",
            "graph_traversal": "lightgreen",
            "processing": "lightsalmon",
            "ranking": "plum",
            "unknown": "lightgray"
        }
        
        node_colors = [type_colors.get(node_types.get(n, "unknown"), "lightgray") for n in G.nodes()]
        
        # Define node sizes based on duration
        node_durations = nx.get_node_attributes(G, 'duration')
        min_size, max_size = 500, 2000
        if node_durations:
            # Scale node sizes based on duration
            max_duration = max(filter(None, node_durations.values()) or [1.0])
            min_duration = min(filter(None, node_durations.values()) or [0.1])
            duration_range = max_duration - min_duration if max_duration > min_duration else 1.0
            
            node_sizes = [
                min_size + (max_size - min_size) * ((node_durations.get(n, min_duration) - min_duration) / duration_range)
                if node_durations.get(n) is not None else min_size
                for n in G.nodes()
            ]
        else:
            node_sizes = [min_size] * len(G.nodes())
        
        # Draw the graph
        nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=node_sizes, alpha=0.8, ax=ax)
        nx.draw_networkx_edges(G, pos, edge_color='gray', width=1.5, alpha=0.7, ax=ax, arrowsize=15)
        
        # Add labels with custom formatting
        node_labels = {}
        for node in G.nodes():
            label = G.nodes[node].get('label', node)
            duration = G.nodes[node].get('duration')
            if duration is not None:
                label = f"{label}\n({duration:.3f}s)"
            node_labels[node] = label
            
        nx.draw_networkx_labels(G, pos, labels=node_labels, font_size=9, font_family='sans-serif', ax=ax)
        
        # Add legend for node types
        legend_elements = [
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor=color, markersize=10, label=node_type)
            for node_type, color in type_colors.items()
            if any(t == node_type for t in node_types.values())
        ]
        if legend_elements:
            ax.legend(handles=legend_elements, loc='upper right')
        
        # Set title and remove axis
        ax.set_title(title)
        ax.axis('off')
        
        # Adjust layout
        plt.tight_layout()
        
        # Save if output file specified
        if output_file:
            plt.savefig(output_file, dpi=300, bbox_inches='tight')
            
        # Show plot if requested
        if show_plot:
            plt.show()
        else:
            plt.close(fig)
            
        return fig
    
    def visualize_resource_usage(
        self,
        query_id: str,
        title: str = "Resource Usage Over Time",
        show_plot: bool = True,
        output_file: Optional[str] = None,
        figsize: Tuple[int, int] = (10, 6)
    ) -> Optional[Figure]:
        """
        Visualize resource usage (memory and CPU) over time for a query.
        
        Args:
            query_id (str): Query ID to visualize resources for
            title (str): Plot title
            show_plot (bool): Whether to display the plot
            output_file (str, optional): Path to save the plot image
            figsize (Tuple[int, int]): Figure size (width, height) in inches
            
        Returns:
            matplotlib.figure.Figure or None: The figure object if visualization is available
        """
        if not self.visualization_available:
            print("Visualization dependencies not available. Install matplotlib and networkx.")
            return None
            
        if self.metrics_collector is None:
            print("No metrics collector set. Use set_metrics_collector() first.")
            return None
            
        # Get query metrics
        metrics = self.metrics_collector.get_query_metrics(query_id)
        
        if not metrics:
            print(f"No metrics found for query ID: {query_id}")
            return None
            
        # Extract resource samples
        memory_samples = metrics["resources"].get("memory_samples", [])
        cpu_samples = metrics["resources"].get("cpu_samples", [])
        
        if not memory_samples and not cpu_samples:
            print("No resource samples available for this query.")
            return None
            
        # Create plot with two y-axes
        fig, ax1 = plt.subplots(figsize=figsize)
        
        # Memory usage (primary y-axis)
        if memory_samples:
            timestamps = [t - metrics["start_time"] for t, _ in memory_samples]  # Relative time in seconds
            memory_values = [m / (1024 * 1024) for _, m in memory_samples]  # Convert to MB
            
            ax1.set_xlabel('Time (seconds)')
            ax1.set_ylabel('Memory Usage (MB)', color='tab:blue')
            ax1.plot(timestamps, memory_values, 'o-', color='tab:blue', label='Memory Usage')
            ax1.tick_params(axis='y', labelcolor='tab:blue')
            ax1.grid(True, alpha=0.3)
            
        # CPU usage (secondary y-axis)
        if cpu_samples:
            timestamps = [t - metrics["start_time"] for t, _ in cpu_samples]  # Relative time in seconds
            cpu_values = [c for _, c in cpu_samples]
            
            if memory_samples:  # Create secondary y-axis if we have memory data
                ax2 = ax1.twinx()
                ax2.set_ylabel('CPU Usage (%)', color='tab:red')
                ax2.plot(timestamps, cpu_values, 'o-', color='tab:red', label='CPU Usage')
                ax2.tick_params(axis='y', labelcolor='tab:red')
                
                # Create combined legend
                lines1, labels1 = ax1.get_legend_handles_labels()
                lines2, labels2 = ax2.get_legend_handles_labels()
                ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')
            else:
                ax1.set_xlabel('Time (seconds)')
                ax1.set_ylabel('CPU Usage (%)', color='tab:red')
                ax1.plot(timestamps, cpu_values, 'o-', color='tab:red', label='CPU Usage')
                ax1.tick_params(axis='y', labelcolor='tab:red')
                ax1.legend(loc='upper left')
                ax1.grid(True, alpha=0.3)
        
        # Add phase timing markers if available
        phase_data = metrics.get("phases", {})
        if phase_data:
            # Find top phases by duration
            top_phases = sorted(
                [(name, data) for name, data in phase_data.items()],
                key=lambda x: x[1].get("duration", 0),
                reverse=True
            )[:5]  # Show top 5 phases only to avoid clutter
            
            for name, data in top_phases:
                if "start_time" in data and "end_time" in data:
                    start_rel = data["start_time"] - metrics["start_time"]
                    end_rel = data["end_time"] - metrics["start_time"]
                    mid_point = (start_rel + end_rel) / 2
                    
                    # Add vertical spans for phase duration
                    ax1.axvspan(start_rel, end_rel, alpha=0.2, color='gray')
                    
                    # Add text label at midpoint
                    y_pos = ax1.get_ylim()[1] * 0.95  # Place near top
                    ax1.text(mid_point, y_pos, name, 
                            rotation=90, verticalalignment='top', 
                            fontsize=8, color='black')
        
        # Set title and adjust layout
        plt.title(title)
        plt.tight_layout()
        
        # Save if output file specified
        if output_file:
            plt.savefig(output_file, dpi=300, bbox_inches='tight')
            
        # Show plot if requested
        if show_plot:
            plt.show()
        else:
            plt.close(fig)
            
        return fig
    
    def visualize_performance_comparison(
        self,
        query_ids: List[str],
        labels: Optional[List[str]] = None,
        title: str = "Query Performance Comparison",
        show_plot: bool = True,
        output_file: Optional[str] = None,
        figsize: Tuple[int, int] = (12, 8)
    ) -> Optional[Figure]:
        """
        Compare performance metrics across multiple queries.
        
        Args:
            query_ids (List[str]): List of query IDs to compare
            labels (List[str], optional): Labels for each query, defaults to query IDs
            title (str): Plot title
            show_plot (bool): Whether to display the plot
            output_file (str, optional): Path to save the plot image
            figsize (Tuple[int, int]): Figure size (width, height) in inches
            
        Returns:
            matplotlib.figure.Figure or None: The figure object if visualization is available
        """
        if not self.visualization_available:
            print("Visualization dependencies not available. Install matplotlib and networkx.")
            return None
            
        if self.metrics_collector is None:
            print("No metrics collector set. Use set_metrics_collector() first.")
            return None
            
        # Get metrics for all queries
        metrics_list = []
        for qid in query_ids:
            metrics = self.metrics_collector.get_query_metrics(qid)
            if metrics:
                metrics_list.append(metrics)
            else:
                print(f"Warning: No metrics found for query ID: {qid}")
                
        if not metrics_list:
            print("No valid metrics found for any of the provided query IDs.")
            return None
            
        # Use provided labels or generate default ones
        if labels is None or len(labels) != len(metrics_list):
            labels = [f"Query {i+1}" for i in range(len(metrics_list))]
            
        # Create figure with multiple subplots
        fig, axs = plt.subplots(2, 2, figsize=figsize)
        
        # 1. Total Duration Comparison (top left)
        durations = [m.get("duration", 0) for m in metrics_list]
        axs[0, 0].bar(labels, durations, color='skyblue')
        axs[0, 0].set_title('Total Execution Time')
        axs[0, 0].set_ylabel('Seconds')
        axs[0, 0].grid(axis='y', linestyle='--', alpha=0.7)
        
        # Add value labels on bars
        for i, v in enumerate(durations):
            axs[0, 0].text(i, v + 0.05, f"{v:.2f}s", ha='center', fontsize=8)
            
        # 2. Phase Timing Comparison (top right)
        # Find common phases across all queries
        all_phases = set()
        for metrics in metrics_list:
            all_phases.update(metrics.get("phases", {}).keys())
            
        # Select top common phases by average duration
        phase_avg_durations = {}
        for phase in all_phases:
            durations = []
            for metrics in metrics_list:
                if phase in metrics.get("phases", {}):
                    durations.append(metrics["phases"][phase].get("duration", 0))
            if durations:
                phase_avg_durations[phase] = sum(durations) / len(durations)
                
        top_phases = sorted(
            [(phase, duration) for phase, duration in phase_avg_durations.items()],
            key=lambda x: x[1],
            reverse=True
        )[:5]  # Show top 5 phases only
        
        if top_phases:
            top_phase_names = [p[0] for p in top_phases]
            
            # Get phase duration for each query
            phase_data = {label: [] for label in labels}
            for i, metrics in enumerate(metrics_list):
                for phase in top_phase_names:
                    duration = 0
                    if phase in metrics.get("phases", {}):
                        duration = metrics["phases"][phase].get("duration", 0)
                    phase_data[labels[i]].append(duration)
                    
            # Create grouped bar chart
            x = np.arange(len(top_phase_names))
            width = 0.8 / len(labels)
            
            for i, label in enumerate(labels):
                offset = (i - len(labels)/2 + 0.5) * width
                bars = axs[0, 1].bar(x + offset, phase_data[label], width, label=label)
                
            axs[0, 1].set_title('Phase Duration Comparison')
            axs[0, 1].set_ylabel('Seconds')
            axs[0, 1].set_xticks(x)
            # Shorten phase names for display if too long
            display_names = [p[:15] + '...' if len(p) > 15 else p for p in top_phase_names]
            axs[0, 1].set_xticklabels(display_names, rotation=45, ha='right')
            axs[0, 1].legend(fontsize=8)
            axs[0, 1].grid(axis='y', linestyle='--', alpha=0.7)
            
        # 3. Memory Usage Comparison (bottom left)
        peak_memories = []
        for metrics in metrics_list:
            if "resources" in metrics and "peak_memory" in metrics["resources"]:
                # Convert to MB
                peak_memories.append(metrics["resources"]["peak_memory"] / (1024 * 1024))
            else:
                peak_memories.append(0)
                
        axs[1, 0].bar(labels, peak_memories, color='lightgreen')
        axs[1, 0].set_title('Peak Memory Usage')
        axs[1, 0].set_ylabel('Memory (MB)')
        axs[1, 0].grid(axis='y', linestyle='--', alpha=0.7)
        
        # Add value labels on bars
        for i, v in enumerate(peak_memories):
            axs[1, 0].text(i, v + 1, f"{v:.1f} MB", ha='center', fontsize=8)
            
        # 4. Results Quality Comparison (bottom right)
        result_counts = [m["results"].get("count", 0) for m in metrics_list]
        quality_scores = [m["results"].get("quality_score", 0) for m in metrics_list]
        
        # Create two-metric visualization
        ax4 = axs[1, 1]
        ax4.set_title('Results Quality and Count')
        
        # Primary y-axis for quality scores
        color = 'tab:red'
        ax4.set_xlabel('Query')
        ax4.set_ylabel('Quality Score (0-1)', color=color)
        ax4.bar(labels, quality_scores, color=color, alpha=0.7, label='Quality Score')
        ax4.tick_params(axis='y', labelcolor=color)
        ax4.set_ylim(0, 1.1)  # Quality scores are 0-1
        
        # Secondary y-axis for result counts
        ax4_count = ax4.twinx()
        color = 'tab:blue'
        ax4_count.set_ylabel('Result Count', color=color)
        ax4_count.plot(labels, result_counts, 'o-', color=color, label='Result Count')
        ax4_count.tick_params(axis='y', labelcolor=color)
        
        # Combine legends
        lines1, labels1 = ax4.get_legend_handles_labels()
        lines2, labels2 = ax4_count.get_legend_handles_labels()
        ax4.legend(lines1 + lines2, labels1 + labels2, loc='upper right', fontsize=8)
        
        # Adjust layout
        plt.tight_layout()
        fig.suptitle(title, fontsize=14, y=1.05)
        
        # Save if output file specified
        if output_file:
            plt.savefig(output_file, dpi=300, bbox_inches='tight')
            
        # Show plot if requested
        if show_plot:
            plt.show()
        else:
            plt.close(fig)
            
        return fig
    
    def visualize_query_patterns(
        self,
        limit: int = 10,
        title: str = "Common Query Patterns",
        show_plot: bool = True,
        output_file: Optional[str] = None,
        figsize: Tuple[int, int] = (10, 6)
    ) -> Optional[Figure]:
        """
        Visualize common query patterns from collected metrics.
        
        Args:
            limit (int): Maximum number of patterns to display
            title (str): Plot title
            show_plot (bool): Whether to display the plot
            output_file (str, optional): Path to save the plot image
            figsize (Tuple[int, int]): Figure size (width, height) in inches
            
        Returns:
            matplotlib.figure.Figure or None: The figure object if visualization is available
        """
        if not self.visualization_available:
            print("Visualization dependencies not available. Install matplotlib and networkx.")
            return None
            
        if self.metrics_collector is None:
            print("No metrics collector set. Use set_metrics_collector() first.")
            return None
            
        # Extract query patterns
        patterns = {}
        for metrics in self.metrics_collector.query_metrics:
            pattern_key = self._extract_pattern_key(metrics)
            if pattern_key in patterns:
                patterns[pattern_key]["count"] += 1
                patterns[pattern_key]["durations"].append(metrics.get("duration", 0))
            else:
                patterns[pattern_key] = {
                    "count": 1,
                    "durations": [metrics.get("duration", 0)],
                    "params": self._extract_pattern_params(metrics)
                }
                
        if not patterns:
            print("No query patterns found in metrics.")
            return None
            
        # Sort patterns by count
        sorted_patterns = sorted(
            [(k, v) for k, v in patterns.items()],
            key=lambda x: x[1]["count"],
            reverse=True
        )[:limit]
        
        # Create figure
        fig, ax = plt.subplots(figsize=figsize)
        
        # Prepare data for visualization
        labels = [f"Pattern {i+1}" for i in range(len(sorted_patterns))]
        counts = [p[1]["count"] for p in sorted_patterns]
        avg_durations = [sum(p[1]["durations"]) / len(p[1]["durations"]) for p in sorted_patterns]
        
        # Create bars for counts
        x = np.arange(len(labels))
        width = 0.35
        
        rects1 = ax.bar(x - width/2, counts, width, label='Query Count', color='steelblue')
        
        # Create secondary y-axis for durations
        ax2 = ax.twinx()
        rects2 = ax2.bar(x + width/2, avg_durations, width, label='Avg Duration (s)', color='indianred')
        
        # Add labels and title
        ax.set_xlabel('Pattern')
        ax.set_ylabel('Query Count')
        ax2.set_ylabel('Average Duration (s)')
        ax.set_title(title)
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        
        # Add legend
        ax.legend(loc='upper left')
        ax2.legend(loc='upper right')
        
        # Add tooltips with pattern details
        for i, (pattern_key, pattern_data) in enumerate(sorted_patterns):
            # Create a string with pattern parameters
            param_str = "\n".join([f"{k}: {v}" for k, v in pattern_data["params"].items()])
            
            # Add an annotation with the pattern details
            ax.annotate(
                param_str,
                xy=(i, 0),
                xytext=(0, -20),
                textcoords="offset points",
                ha='center',
                va='top',
                bbox=dict(boxstyle='round,pad=0.5', fc='yellow', alpha=0.5),
                xycoords='data',
                fontsize=8,
                visible=False  # Start invisible
            )
            
        # Add grid for better readability
        ax.grid(axis='y', linestyle='--', alpha=0.7)
        
        # Add a note about pattern details
        plt.figtext(0.5, 0.01, 
                   "Note: Pattern details available in returned Figure object or when using in interactive mode.",
                   ha="center", fontsize=8, style='italic')
        
        # Adjust layout
        plt.tight_layout()
        
        # Save if output file specified
        if output_file:
            plt.savefig(output_file, dpi=300, bbox_inches='tight')
            
        # Show plot if requested
        if show_plot:
            plt.show()
        else:
            plt.close(fig)
            
        return fig
    
    def export_dashboard_html(
        self,
        output_file: str,
        query_id: Optional[str] = None,
        include_all_metrics: bool = False
    ) -> None:
        """
        Export a complete HTML dashboard with multiple visualizations.
        
        Args:
            output_file (str): Path to save the HTML dashboard
            query_id (str, optional): Specific query ID to focus on, or None for all queries
            include_all_metrics (bool): Whether to include all available metrics
        """
        if not self.visualization_available:
            print("Visualization dependencies not available. Install matplotlib and networkx.")
            return
            
        if self.metrics_collector is None:
            print("No metrics collector set. Use set_metrics_collector() first.")
            return
            
        # Generate all required visualizations
        # Save them as temporary files or encode as base64
        # Then create an HTML template with the visualizations embedded
        # This is a simplified implementation
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>GraphRAG Query Optimizer Dashboard</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .dashboard {{ display: flex; flex-wrap: wrap; }}
                .chart {{ margin: 10px; padding: 10px; border: 1px solid #ddd; border-radius: 5px; }}
                .full-width {{ width: 100%; }}
                .half-width {{ width: calc(50% - 40px); }}
                h1, h2 {{ color: #333; }}
                .metrics-table {{ border-collapse: collapse; width: 100%; }}
                .metrics-table th, .metrics-table td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                .metrics-table tr:nth-child(even) {{ background-color: #f2f2f2; }}
            </style>
        </head>
        <body>
            <h1>GraphRAG Query Optimizer Dashboard</h1>
            <p>Generated on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        """
        
        # Add dashboard content based on metrics
        # This would typically include:
        # - Overall performance metrics table
        # - Timing breakdown charts
        # - Resource usage charts
        # - Query pattern analysis
        
        # Example of adding metrics table
        if query_id is not None:
            metrics = self.metrics_collector.get_query_metrics(query_id)
            if metrics:
                html_content += f"""
                <div class="chart full-width">
                    <h2>Query Metrics: {query_id}</h2>
                    <table class="metrics-table">
                        <tr>
                            <th>Metric</th>
                            <th>Value</th>
                        </tr>
                        <tr>
                            <td>Duration</td>
                            <td>{metrics.get('duration', 0):.3f} seconds</td>
                        </tr>
                        <tr>
                            <td>Result Count</td>
                            <td>{metrics['results'].get('count', 0)}</td>
                        </tr>
                        <tr>
                            <td>Quality Score</td>
                            <td>{metrics['results'].get('quality_score', 0):.2f}</td>
                        </tr>
                        <tr>
                            <td>Peak Memory</td>
                            <td>{metrics['resources'].get('peak_memory', 0) / (1024 * 1024):.2f} MB</td>
                        </tr>
                    </table>
                </div>
                """
                
                # Add phase breakdown
                if metrics.get("phases"):
                    html_content += """
                    <div class="chart full-width">
                        <h2>Phase Timing Breakdown</h2>
                        <table class="metrics-table">
                            <tr>
                                <th>Phase</th>
                                <th>Duration (s)</th>
                                <th>% of Total</th>
                            </tr>
                    """
                    
                    # Sort phases by duration
                    sorted_phases = sorted(
                        [(p, d) for p, d in metrics["phases"].items()],
                        key=lambda x: x[1].get("duration", 0),
                        reverse=True
                    )
                    
                    total_duration = metrics.get("duration", 1.0)  # Avoid division by zero
                    
                    for phase, data in sorted_phases:
                        duration = data.get("duration", 0)
                        percentage = (duration / total_duration) * 100
                        html_content += f"""
                        <tr>
                            <td>{phase}</td>
                            <td>{duration:.3f}</td>
                            <td>{percentage:.1f}%</td>
                        </tr>
                        """
                        
                    html_content += """
                    </table>
                    </div>
                    """
        else:
            # Summary of all queries
            performance_report = self.metrics_collector.generate_performance_report()
            
            if performance_report:
                html_content += """
                <div class="chart full-width">
                    <h2>Overall Performance Summary</h2>
                    <table class="metrics-table">
                        <tr>
                            <th>Metric</th>
                            <th>Value</th>
                        </tr>
                """
                
                timing = performance_report.get("timing_summary", {})
                html_content += f"""
                <tr>
                    <td>Total Queries</td>
                    <td>{performance_report.get('query_count', 0)}</td>
                </tr>
                <tr>
                    <td>Average Duration</td>
                    <td>{timing.get('avg_duration', 0):.3f} seconds</td>
                </tr>
                <tr>
                    <td>Minimum Duration</td>
                    <td>{timing.get('min_duration', 0):.3f} seconds</td>
                </tr>
                <tr>
                    <td>Maximum Duration</td>
                    <td>{timing.get('max_duration', 0):.3f} seconds</td>
                </tr>
                """
                html_content += """
                </table>
                </div>
                """
                
                # Add recommendations
                recommendations = performance_report.get("recommendations", [])
                if recommendations:
                    html_content += """
                    <div class="chart full-width">
                        <h2>Optimization Recommendations</h2>
                        <ul>
                    """
                    
                    for rec in recommendations:
                        severity = rec.get("severity", "medium")
                        color = {
                            "high": "red",
                            "medium": "orange",
                            "low": "green"
                        }.get(severity, "black")
                        
                        html_content += f"""
                        <li style="color: {color};">{rec.get('message', '')}</li>
                        """
                        
                    html_content += """
                    </ul>
                    </div>
                    """
            
            # Add interactive controls and other dashboard elements here
        
        # Close HTML
        html_content += """
        </body>
        </html>
        """
        
        # Write to file
        with open(output_file, 'w') as f:
            f.write(html_content)
            
        print(f"Dashboard exported to {output_file}")
    
    def _extract_pattern_key(self, metrics: Dict[str, Any]) -> str:
        """
        Extract a pattern key from query metrics for grouping similar queries.
        
        Args:
            metrics (Dict): Query metrics
            
        Returns:
            str: Pattern key
        """
        # This is a simplified implementation
        # A more sophisticated approach would analyze query parameters and structure
        
        pattern_elements = []
        
        # Extract key parameters that define a pattern
        params = metrics.get("params", {})
        
        # Vector-related parameters
        if "max_vector_results" in params:
            pattern_elements.append(f"vec{params['max_vector_results']}")
            
        # Traversal-related parameters
        if "max_traversal_depth" in params:
            pattern_elements.append(f"depth{params['max_traversal_depth']}")
            
        # Edge types (if present)
        if "edge_types" in params and params["edge_types"]:
            edge_count = len(params["edge_types"])
            pattern_elements.append(f"edges{edge_count}")
            
        # Use counts of phases as part of the pattern
        phases = metrics.get("phases", {})
        if phases:
            pattern_elements.append(f"phases{len(phases)}")
            
        # If we have nothing else, use the duration range
        if not pattern_elements and "duration" in metrics:
            duration = metrics["duration"]
            if duration < 0.1:
                pattern_elements.append("duration_veryfast")
            elif duration < 0.5:
                pattern_elements.append("duration_fast")
            elif duration < 2.0:
                pattern_elements.append("duration_medium")
            else:
                pattern_elements.append("duration_slow")
                
        # Combine elements to form pattern key
        if not pattern_elements:
            return "unknown_pattern"
            
        return "_".join(pattern_elements)
    
    def _extract_pattern_params(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract representative parameters for a query pattern.
        
        Args:
            metrics (Dict): Query metrics
            
        Returns:
            Dict: Pattern parameters
        """
        # Start with the original parameters
        pattern_params = metrics.get("params", {}).copy()
        
        # Add derived metrics
        pattern_params["duration"] = metrics.get("duration", 0)
        pattern_params["result_count"] = metrics.get("results", {}).get("count", 0)
        
        # Add phase count
        pattern_params["phase_count"] = len(metrics.get("phases", {}))
        
        # Add memory usage if available
        if "resources" in metrics and "peak_memory" in metrics["resources"]:
            pattern_params["peak_memory_mb"] = metrics["resources"]["peak_memory"] / (1024 * 1024)
            
        return pattern_params
