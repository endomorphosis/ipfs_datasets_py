"""
Audit and Provenance Integration Module

This module provides integration between the audit visualization system and the provenance dashboard,
enabling comprehensive monitoring of data lineage, transformations, and audit events in a unified view.
"""

import os
import json
import time
import logging
import datetime
from typing import Dict, List, Any, Optional, Tuple, Union, Callable
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
from ipfs_datasets_py.audit.audit_visualization import AuditVisualizer, AuditMetricsAggregator
from ipfs_datasets_py.audit.audit_logger import AuditLogger, AuditEvent
from ipfs_datasets_py.provenance_dashboard import ProvenanceDashboard
from ipfs_datasets_py.dashboards.rag.query_visualization import RAGQueryVisualizer
from ipfs_datasets_py.analytics.data_provenance import ProvenanceManager
from ipfs_datasets_py.knowledge_graphs.cross_document_lineage import EnhancedLineageTracker


class AuditProvenanceDashboard:
    """
    Integrated dashboard combining audit visualization with provenance tracking.

    This class provides a unified view of audit events, data lineage, and query performance,
    enabling comprehensive monitoring and analysis of data transformations and usage.
    """

    def __init__(
        self,
        audit_metrics: Optional[AuditMetricsAggregator] = None,
        provenance_dashboard: Optional[ProvenanceDashboard] = None,
        audit_logger: Optional[AuditLogger] = None,
        query_visualizer: Optional[RAGQueryVisualizer] = None
    ):
        """
        Initialize the integrated audit-provenance dashboard.

        Args:
            audit_metrics: Optional AuditMetricsAggregator for audit visualization
            provenance_dashboard: Optional ProvenanceDashboard for provenance tracking
            audit_logger: Optional AuditLogger for capturing new audit events
            query_visualizer: Optional RAGQueryVisualizer for RAG query metrics
        """
        # Create components if not provided
        if not audit_metrics:
            audit_metrics = AuditMetricsAggregator()

        if not provenance_dashboard:
            # Create a new provenance dashboard
            provenance_manager = ProvenanceManager()
            lineage_tracker = None
            try:
                lineage_tracker = EnhancedLineageTracker()
            except Exception as e:
                logging.warning(f"Could not initialize EnhancedLineageTracker: {str(e)}")

            provenance_dashboard = ProvenanceDashboard(
                provenance_manager=provenance_manager,
                lineage_tracker=lineage_tracker
            )

        if not audit_logger:
            # Create a new audit logger that feeds into the metrics
            audit_logger = AuditLogger()
            audit_logger.add_handler(lambda event: audit_metrics.process_event(event))

        self.audit_metrics = audit_metrics
        self.provenance_dashboard = provenance_dashboard
        self.audit_logger = audit_logger
        self.query_visualizer = query_visualizer

        # Store audit metrics in provenance dashboard for integration
        self.provenance_dashboard.audit_metrics = audit_metrics

        # Create visualizer
        self.audit_visualizer = AuditVisualizer(audit_metrics)

        # Available visualization capabilities
        self.visualization_available = VISUALIZATION_LIBS_AVAILABLE
        self.interactive_visualization_available = INTERACTIVE_VISUALIZATION_AVAILABLE
        self.template_engine_available = TEMPLATE_ENGINE_AVAILABLE

    def create_provenance_audit_timeline(
        self,
        data_ids: List[str],
        hours: int = 24,
        output_file: Optional[str] = None,
        return_base64: bool = False
    ) -> Optional[str]:
        """
        Create a timeline visualization showing both provenance events and audit events.

        Args:
            data_ids: List of data entity IDs to visualize
            hours: Number of hours to include in the timeline
            output_file: Optional path to save the visualization
            return_base64: Whether to return the image as base64

        Returns:
            str: Base64-encoded image or file path if output_file is specified
        """
        if not self.visualization_available:
            logging.warning("Visualization libraries not available")
            return None

        try:
            # Get provenance events for these data IDs
            provenance_events = self._get_provenance_events(data_ids)

            # Get audit events (filtered by data IDs if possible)
            audit_events = self._get_audit_events_for_entities(data_ids, hours)

            # Create timeline visualization
            fig, ax = plt.subplots(figsize=(14, 8))

            # Calculate time range
            end_time = time.time()
            start_time = end_time - (hours * 3600)

            # Convert timestamps to datetime for plotting
            prov_times = [datetime.datetime.fromtimestamp(event['timestamp'])
                         for event in provenance_events
                         if event['timestamp'] >= start_time]

            prov_labels = [f"{event['type']}: {event['entity_id']}"
                         for event in provenance_events
                         if event['timestamp'] >= start_time]

            audit_times = [datetime.datetime.fromtimestamp(event['timestamp'])
                         for event in audit_events]

            audit_labels = [f"{event['category']}: {event['action']}"
                          for event in audit_events]

            # Create scatter plot for provenance events
            ax.scatter(prov_times, [1] * len(prov_times), marker='o', s=100,
                     color='blue', alpha=0.7, label='Provenance Events')

            # Create scatter plot for audit events
            audit_y = [0.8] * len(audit_times)
            ax.scatter(audit_times, audit_y, marker='s', s=80,
                     color='red', alpha=0.7, label='Audit Events')

            # Add annotations for important events
            for i, (time_point, label) in enumerate(zip(prov_times, prov_labels)):
                if i % max(1, len(prov_times) // 10) == 0:  # Annotate every Nth point to avoid crowding
                    ax.annotate(label, (time_point, 1),
                              xytext=(0, 10), textcoords='offset points',
                              rotation=45, ha='right', fontsize=8)

            for i, (time_point, label) in enumerate(zip(audit_times, audit_labels)):
                if i % max(1, len(audit_times) // 10) == 0:  # Annotate every Nth point to avoid crowding
                    ax.annotate(label, (time_point, 0.8),
                              xytext=(0, -20), textcoords='offset points',
                              rotation=45, ha='right', fontsize=8)

            # Configure axes
            ax.set_title('Integrated Provenance and Audit Timeline', fontsize=14)
            ax.set_xlabel('Time', fontsize=12)
            ax.set_yticks([0.8, 1])
            ax.set_yticklabels(['Audit Events', 'Provenance Events'])
            ax.grid(True, linestyle='--', alpha=0.7)

            # Format time axis
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            plt.xticks(rotation=45)

            # Add legend
            ax.legend(loc='upper right')

            # Set y-axis limits with some padding
            ax.set_ylim([0.5, 1.2])

            # Adjust layout
            plt.tight_layout()

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

        except Exception as e:
            logging.error(f"Error creating provenance-audit timeline: {str(e)}")
            import traceback
            logging.error(traceback.format_exc())
            return None

    def create_provenance_metrics_comparison(
        self,
        metrics_type: str = 'overview',
        output_file: Optional[str] = None,
        return_base64: bool = False,
        interactive: bool = False
    ) -> Optional[str]:
        """
        Create a visualization comparing provenance metrics with audit metrics.

        Args:
            metrics_type: Type of metrics to compare ('overview', 'performance', 'security')
            output_file: Optional path to save the visualization
            return_base64: Whether to return the image as base64
            interactive: Whether to create an interactive visualization

        Returns:
            str: Base64-encoded image or file path if output_file is specified
        """
        if not self.visualization_available:
            logging.warning("Visualization libraries not available")
            return None

        if interactive and not self.interactive_visualization_available:
            logging.warning("Interactive visualization not available, falling back to static")
            interactive = False

        try:
            # Get audit metrics summary
            audit_summary = self.audit_metrics.get_metrics_summary()

            # Get provenance metrics summary
            provenance_summary = self._get_provenance_metrics()

            if metrics_type == 'overview':
                if interactive:
                    # Create interactive overview chart using Plotly
                    fig = make_subplots(
                        rows=1, cols=2,
                        subplot_titles=["Audit Events", "Provenance Events"],
                        specs=[[{"type": "domain"}, {"type": "domain"}]]
                    )

                    # Add audit events pie chart
                    audit_labels = list(audit_summary['by_category'].keys())
                    audit_values = list(audit_summary['by_category'].values())

                    fig.add_trace(
                        go.Pie(
                            labels=audit_labels,
                            values=audit_values,
                            textinfo='label+percent',
                            marker=dict(colors=px.colors.qualitative.Set2),
                            name="Audit Events"
                        ),
                        row=1, col=1
                    )

                    # Add provenance events pie chart
                    prov_labels = list(provenance_summary['by_type'].keys())
                    prov_values = list(provenance_summary['by_type'].values())

                    fig.add_trace(
                        go.Pie(
                            labels=prov_labels,
                            values=prov_values,
                            textinfo='label+percent',
                            marker=dict(colors=px.colors.qualitative.Pastel2),
                            name="Provenance Events"
                        ),
                        row=1, col=2
                    )

                    # Update layout
                    fig.update_layout(
                        title="Comparison of Audit and Provenance Events",
                        height=500,
                        width=900
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
                else:
                    # Create static visualization using matplotlib
                    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 7))

                    # Plot audit events by category
                    audit_labels = list(audit_summary['by_category'].keys())
                    audit_values = list(audit_summary['by_category'].values())
                    ax1.pie(audit_values, labels=audit_labels, autopct='%1.1f%%',
                           colors=sns.color_palette("Set2", len(audit_labels)),
                           startangle=90)
                    ax1.set_title('Audit Events by Category')
                    ax1.axis('equal')

                    # Plot provenance events by type
                    prov_labels = list(provenance_summary['by_type'].keys())
                    prov_values = list(provenance_summary['by_type'].values())
                    ax2.pie(prov_values, labels=prov_labels, autopct='%1.1f%%',
                           colors=sns.color_palette("Pastel2", len(prov_labels)),
                           startangle=90)
                    ax2.set_title('Provenance Events by Type')
                    ax2.axis('equal')

                    plt.suptitle('Comparison of Audit and Provenance Events', fontsize=16)
                    plt.tight_layout()

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

            elif metrics_type == 'performance':
                # Get performance metrics
                audit_performance = self.audit_metrics.get_performance_metrics()

                # Get provenance timing data (approximated)
                prov_timing = provenance_summary.get('timing', {})

                if interactive:
                    # Create interactive bar chart using Plotly
                    fig = go.Figure()

                    # Add audit performance bar
                    if audit_performance and 'avg_duration' in audit_performance:
                        audit_operations = list(audit_performance['avg_duration'].keys())
                        audit_durations = list(audit_performance['avg_duration'].values())

                        fig.add_trace(go.Bar(
                            x=audit_operations,
                            y=audit_durations,
                            name='Audit Operations',
                            marker_color='indianred'
                        ))

                    # Add provenance performance bar
                    if prov_timing:
                        prov_operations = list(prov_timing.keys())
                        prov_durations = list(prov_timing.values())

                        fig.add_trace(go.Bar(
                            x=prov_operations,
                            y=prov_durations,
                            name='Provenance Operations',
                            marker_color='lightsalmon'
                        ))

                    # Update layout
                    fig.update_layout(
                        title='Performance Comparison: Audit vs Provenance Operations',
                        xaxis_title='Operation',
                        yaxis_title='Duration (ms)',
                        barmode='group',
                        height=600,
                        width=1000
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
                else:
                    # Static visualization with matplotlib
                    plt.figure(figsize=(14, 8))

                    # Set width of bars
                    bar_width = 0.35

                    # Set positions of the bars
                    all_operations = set()

                    # Add audit operations
                    if audit_performance and 'avg_duration' in audit_performance:
                        all_operations.update(audit_performance['avg_duration'].keys())

                    # Add provenance operations
                    if prov_timing:
                        all_operations.update(prov_timing.keys())

                    # Sort operations alphabetically
                    all_operations = sorted(all_operations)

                    # Set up positions
                    positions = np.arange(len(all_operations))

                    # Create audit bars
                    audit_durations = []
                    if audit_performance and 'avg_duration' in audit_performance:
                        for op in all_operations:
                            audit_durations.append(audit_performance['avg_duration'].get(op, 0))

                    # Create provenance bars
                    prov_durations = []
                    if prov_timing:
                        for op in all_operations:
                            prov_durations.append(prov_timing.get(op, 0))

                    # Create bars
                    if audit_durations:
                        plt.bar(positions - bar_width/2, audit_durations, bar_width,
                               label='Audit Operations', color='indianred')

                    if prov_durations:
                        plt.bar(positions + bar_width/2, prov_durations, bar_width,
                               label='Provenance Operations', color='lightsalmon')

                    # Add labels, title and legend
                    plt.xlabel('Operation')
                    plt.ylabel('Duration (ms)')
                    plt.title('Performance Comparison: Audit vs Provenance Operations')
                    plt.xticks(positions, all_operations, rotation=45, ha='right')
                    plt.legend()

                    plt.tight_layout()

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

            elif metrics_type == 'security':
                # For security metrics, focus on anomalies and security insights
                audit_security = self.audit_metrics.get_security_insights()

                # Get provenance security insights (if available)
                prov_security = provenance_summary.get('security', {})

                # Create static visualization for security metrics
                plt.figure(figsize=(14, 8))

                # Plot trend comparison
                audit_trends = {}
                if 'trending_actions' in audit_security:
                    audit_trends = audit_security['trending_actions']

                prov_trends = {}
                if 'trending_operations' in prov_security:
                    prov_trends = prov_security['trending_operations']

                # Combine and select top trends from both
                all_trends = {}
                all_trends.update(audit_trends)
                all_trends.update(prov_trends)

                # Sort and get top items
                sorted_trends = sorted(all_trends.items(), key=lambda x: x[1], reverse=True)[:10]

                labels = [item[0] for item in sorted_trends]
                values = [item[1] for item in sorted_trends]

                # Create horizontal bar chart
                colors = ['red' if item[0] in audit_trends else 'blue' for item in sorted_trends]
                plt.barh(labels, values, color=colors, alpha=0.7)

                # Add labels and title
                plt.xlabel('Trend Score')
                plt.title('Top Trending Operations in Audit and Provenance Events')

                # Add legend
                from matplotlib.patches import Patch
                legend_elements = [
                    Patch(facecolor='red', alpha=0.7, label='Audit Events'),
                    Patch(facecolor='blue', alpha=0.7, label='Provenance Events')
                ]
                plt.legend(handles=legend_elements)

                plt.tight_layout()

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
                logging.warning(f"Unknown metrics type: {metrics_type}")
                return None

        except Exception as e:
            logging.error(f"Error creating metrics comparison: {str(e)}")
            import traceback
            logging.error(traceback.format_exc())
            return None

    def create_integrated_dashboard(
        self,
        output_dir: str,
        data_ids: Optional[List[str]] = None,
        dashboard_name: str = "integrated_dashboard.html"
    ) -> str:
        """
        Create an integrated dashboard with audit, provenance, and query metrics.

        Args:
            output_dir: Directory to save the dashboard files
            data_ids: Optional list of data IDs to focus on
            dashboard_name: Name of the main dashboard HTML file

        Returns:
            str: Path to the main dashboard file
        """
        if not self.template_engine_available:
            logging.error("Template engine not available, cannot create dashboard")
            return None

        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)

        dashboard_path = os.path.join(output_dir, dashboard_name)

        # If no data_ids specified, try to get recent entities
        if not data_ids:
            try:
                # Get recent provenance entities
                data_ids = self._get_recent_entities(10)
            except Exception as e:
                logging.warning(f"Could not get recent entities: {str(e)}")
                data_ids = []

        # Generate visualizations for the dashboard
        chart_paths = {}

        try:
            # Create audit visualizations
            chart_paths['events_by_category'] = os.path.join(output_dir, "events_by_category.png")
            self.audit_visualizer.plot_events_by_category(output_file=chart_paths['events_by_category'])

            chart_paths['events_by_level'] = os.path.join(output_dir, "events_by_level.png")
            self.audit_visualizer.plot_events_by_level(output_file=chart_paths['events_by_level'])

            chart_paths['event_timeline'] = os.path.join(output_dir, "event_timeline.png")
            self.audit_visualizer.plot_event_timeline(output_file=chart_paths['event_timeline'])

            # Create provenance visualizations if data_ids available
            if data_ids:
                chart_paths['data_lineage'] = os.path.join(output_dir, "data_lineage.png")
                self.provenance_dashboard.visualize_data_lineage(
                    data_ids=data_ids,
                    output_file=chart_paths['data_lineage']
                )

                # Add cross-document lineage if available
                if self.provenance_dashboard.lineage_tracker:
                    chart_paths['cross_doc_lineage'] = os.path.join(output_dir, "cross_doc_lineage.png")
                    self.provenance_dashboard.visualize_cross_document_lineage(
                        document_ids=data_ids,
                        output_file=chart_paths['cross_doc_lineage']
                    )

            # Create integrated timeline
            chart_paths['integrated_timeline'] = os.path.join(output_dir, "integrated_timeline.png")
            self.create_provenance_audit_timeline(
                data_ids=data_ids if data_ids else [],
                output_file=chart_paths['integrated_timeline']
            )

            # Create metrics comparison
            chart_paths['metrics_comparison'] = os.path.join(output_dir, "metrics_comparison.png")
            self.create_provenance_metrics_comparison(
                metrics_type='overview',
                output_file=chart_paths['metrics_comparison']
            )

            # Create query performance visualization if available
            if self.query_visualizer:
                chart_paths['query_performance'] = os.path.join(output_dir, "query_performance.png")
                self.query_visualizer.plot_query_performance(
                    output_file=chart_paths['query_performance']
                )

        except Exception as e:
            logging.error(f"Error creating dashboard visualizations: {str(e)}")
            import traceback
            logging.error(traceback.format_exc())

        # Get metric summaries
        audit_summary = self.audit_metrics.get_metrics_summary()
        provenance_summary = self._get_provenance_metrics()
        query_summary = {}
        if self.query_visualizer:
            query_summary = self.query_visualizer.metrics.get_metrics_summary()

        # Create HTML dashboard
        template_string = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Integrated Audit and Provenance Dashboard</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    max-width: 1200px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #f5f5f5;
                }
                h1, h2, h3, h4 {
                    color: #1a5276;
                }
                .header {
                    margin-bottom: 30px;
                    border-bottom: 1px solid #ddd;
                    padding-bottom: 10px;
                    text-align: center;
                    background-color: #fff;
                    padding: 20px;
                    border-radius: 5px;
                    box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                }
                .section {
                    margin-bottom: 30px;
                    padding: 20px;
                    background-color: #fff;
                    border-radius: 5px;
                    box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                }
                .dashboard-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                    gap: 20px;
                    margin-bottom: 20px;
                }
                .metric-card {
                    background-color: #f9f9f9;
                    padding: 15px;
                    border-radius: 5px;
                    text-align: center;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                }
                .metric-card h3 {
                    margin-top: 0;
                    font-size: 16px;
                }
                .metric-card p {
                    font-size: 24px;
                    font-weight: bold;
                    margin: 5px 0;
                }
                .chart-container {
                    margin-bottom: 20px;
                    background-color: #fff;
                    padding: 15px;
                    border-radius: 5px;
                    text-align: center;
                }
                .chart-container img {
                    max-width: 100%;
                    height: auto;
                    border: 1px solid #ddd;
                    border-radius: 5px;
                }
                table {
                    width: 100%;
                    border-collapse: collapse;
                    margin-bottom: 20px;
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
                .footer {
                    text-align: center;
                    margin-top: 30px;
                    color: #777;
                    font-size: 0.8em;
                }
                .tabs {
                    display: flex;
                    margin-bottom: 20px;
                }
                .tab {
                    padding: 10px 20px;
                    background-color: #f2f2f2;
                    border: 1px solid #ddd;
                    border-bottom: none;
                    cursor: pointer;
                    margin-right: 5px;
                    border-top-left-radius: 5px;
                    border-top-right-radius: 5px;
                }
                .tab.active {
                    background-color: #fff;
                    border-bottom: 1px solid #fff;
                    margin-bottom: -1px;
                }
                .tab-content {
                    display: none;
                    padding: 20px;
                    border: 1px solid #ddd;
                    background-color: #fff;
                    border-radius: 0 5px 5px 5px;
                }
                .tab-content.active {
                    display: block;
                }
                .alert {
                    padding: 15px;
                    margin-bottom: 20px;
                    border: 1px solid transparent;
                    border-radius: 4px;
                }
                .alert-warning {
                    color: #8a6d3b;
                    background-color: #fcf8e3;
                    border-color: #faebcc;
                }
                .alert-danger {
                    color: #a94442;
                    background-color: #f2dede;
                    border-color: #ebccd1;
                }
            </style>
            <script>
                function openTab(evt, tabName) {
                    var i, tabcontent, tablinks;
                    tabcontent = document.getElementsByClassName("tab-content");
                    for (i = 0; i < tabcontent.length; i++) {
                        tabcontent[i].style.display = "none";
                    }
                    tablinks = document.getElementsByClassName("tab");
                    for (i = 0; i < tablinks.length; i++) {
                        tablinks[i].className = tablinks[i].className.replace(" active", "");
                    }
                    document.getElementById(tabName).style.display = "block";
                    evt.currentTarget.className += " active";
                }
            </script>
        </head>
        <body>
            <div class="header">
                <h1>Integrated Audit and Provenance Dashboard</h1>
                <p>Generated: {{ generated_at }}</p>
            </div>

            <div class="section">
                <h2>Overview</h2>
                <div class="dashboard-grid">
                    <div class="metric-card">
                        <h3>Total Audit Events</h3>
                        <p>{{ audit_summary.total_events }}</p>
                    </div>
                    <div class="metric-card">
                        <h3>Audit Error Rate</h3>
                        <p>{{ (audit_summary.error_rate * 100)|round(1) }}%</p>
                    </div>
                    <div class="metric-card">
                        <h3>Provenance Records</h3>
                        <p>{{ provenance_summary.total_records }}</p>
                    </div>
                    <div class="metric-card">
                        <h3>Data Entities</h3>
                        <p>{{ provenance_summary.total_entities }}</p>
                    </div>
                    {% if query_summary %}
                    <div class="metric-card">
                        <h3>Total Queries</h3>
                        <p>{{ query_summary.total_queries }}</p>
                    </div>
                    <div class="metric-card">
                        <h3>Query Success Rate</h3>
                        <p>{{ (query_summary.success_rate * 100)|round(1) }}%</p>
                    </div>
                    {% endif %}
                </div>

                <!-- Integrated timeline visualization -->
                {% if 'integrated_timeline' in chart_paths %}
                <div class="chart-container">
                    <h3>Integrated Audit and Provenance Timeline</h3>
                    <img src="integrated_timeline.png" alt="Integrated Timeline">
                </div>
                {% endif %}

                <!-- Metrics comparison visualization -->
                {% if 'metrics_comparison' in chart_paths %}
                <div class="chart-container">
                    <h3>Metrics Comparison</h3>
                    <img src="metrics_comparison.png" alt="Metrics Comparison">
                </div>
                {% endif %}
            </div>

            <div class="section">
                <div class="tabs">
                    <div class="tab active" onclick="openTab(event, 'audit-tab')">Audit Metrics</div>
                    <div class="tab" onclick="openTab(event, 'provenance-tab')">Provenance Tracking</div>
                    {% if query_summary %}
                    <div class="tab" onclick="openTab(event, 'query-tab')">Query Performance</div>
                    {% endif %}
                </div>

                <div id="audit-tab" class="tab-content active">
                    <h2>Audit Metrics</h2>

                    <!-- Events by category visualization -->
                    {% if 'events_by_category' in chart_paths %}
                    <div class="chart-container">
                        <h3>Events by Category</h3>
                        <img src="events_by_category.png" alt="Events by Category">
                    </div>
                    {% endif %}

                    <!-- Events by level visualization -->
                    {% if 'events_by_level' in chart_paths %}
                    <div class="chart-container">
                        <h3>Events by Severity Level</h3>
                        <img src="events_by_level.png" alt="Events by Level">
                    </div>
                    {% endif %}

                    <!-- Event timeline visualization -->
                    {% if 'event_timeline' in chart_paths %}
                    <div class="chart-container">
                        <h3>Event Timeline</h3>
                        <img src="event_timeline.png" alt="Event Timeline">
                    </div>
                    {% endif %}

                    <h3>Top User Activity</h3>
                    <table>
                        <thead>
                            <tr>
                                <th>User</th>
                                <th>Event Count</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for user, count in audit_summary.top_users.items() %}
                            <tr>
                                <td>{{ user }}</td>
                                <td>{{ count }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>

                    <h3>Top Actions</h3>
                    <table>
                        <thead>
                            <tr>
                                <th>Action</th>
                                <th>Event Count</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for action, count in audit_summary.top_actions.items() %}
                            <tr>
                                <td>{{ action }}</td>
                                <td>{{ count }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>

                    {% if audit_summary.recent_spikes %}
                    <h3>Recent Anomalies</h3>
                    <table>
                        <thead>
                            <tr>
                                <th>Category</th>
                                <th>Action</th>
                                <th>Timestamp</th>
                                <th>Magnitude</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for spike in audit_summary.recent_spikes %}
                            <tr>
                                <td>{{ spike.category }}</td>
                                <td>{{ spike.action }}</td>
                                <td>{{ spike.timestamp }}</td>
                                <td>{{ spike.magnitude|round(2) }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                    {% endif %}
                </div>

                <div id="provenance-tab" class="tab-content">
                    <h2>Provenance Tracking</h2>

                    {% if data_ids %}
                    <div class="chart-container">
                        <h3>Data IDs in Focus</h3>
                        <div style="padding: 10px; background-color: #f9f9f9; border-radius: 5px; text-align: left;">
                            <ul>
                                {% for data_id in data_ids %}
                                <li>{{ data_id }}</li>
                                {% endfor %}
                            </ul>
                        </div>
                    </div>
                    {% endif %}

                    <!-- Data lineage visualization -->
                    {% if 'data_lineage' in chart_paths %}
                    <div class="chart-container">
                        <h3>Data Lineage Graph</h3>
                        <img src="data_lineage.png" alt="Data Lineage">
                    </div>
                    {% endif %}

                    <!-- Cross-document lineage visualization -->
                    {% if 'cross_doc_lineage' in chart_paths %}
                    <div class="chart-container">
                        <h3>Cross-Document Lineage</h3>
                        <img src="cross_doc_lineage.png" alt="Cross-Document Lineage">
                    </div>
                    {% endif %}

                    <h3>Provenance Records by Type</h3>
                    <table>
                        <thead>
                            <tr>
                                <th>Record Type</th>
                                <th>Count</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for rec_type, count in provenance_summary.by_type.items() %}
                            <tr>
                                <td>{{ rec_type }}</td>
                                <td>{{ count }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>

                    {% if provenance_summary.recent_operations %}
                    <h3>Recent Operations</h3>
                    <table>
                        <thead>
                            <tr>
                                <th>Operation</th>
                                <th>Entity ID</th>
                                <th>Time</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for op in provenance_summary.recent_operations %}
                            <tr>
                                <td>{{ op.operation }}</td>
                                <td>{{ op.entity_id }}</td>
                                <td>{{ op.timestamp }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                    {% endif %}
                </div>

                {% if query_summary %}
                <div id="query-tab" class="tab-content">
                    <h2>Query Performance</h2>

                    <!-- Query performance visualization -->
                    {% if 'query_performance' in chart_paths %}
                    <div class="chart-container">
                        <h3>Query Performance Metrics</h3>
                        <img src="query_performance.png" alt="Query Performance">
                    </div>
                    {% endif %}

                    <div class="dashboard-grid">
                        <div class="metric-card">
                            <h3>Total Queries</h3>
                            <p>{{ query_summary.total_queries }}</p>
                        </div>
                        <div class="metric-card">
                            <h3>Avg Duration</h3>
                            <p>{{ query_summary.avg_duration|round(2) }}s</p>
                        </div>
                        <div class="metric-card">
                            <h3>Success Rate</h3>
                            <p>{{ (query_summary.success_rate * 100)|round(1) }}%</p>
                        </div>
                        <div class="metric-card">
                            <h3>Error Rate</h3>
                            <p>{{ (query_summary.error_rate * 100)|round(1) }}%</p>
                        </div>
                    </div>

                    {% if query_summary.performance_by_type %}
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
                            {% for query_type, stats in query_summary.performance_by_type.items() %}
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

                    {% if query_summary.top_queries %}
                    <h3>Top Queries</h3>
                    <table>
                        <thead>
                            <tr>
                                <th>Query</th>
                                <th>Count</th>
                                <th>Avg Duration (s)</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for query, stats in query_summary.top_queries.items() %}
                            <tr>
                                <td>{{ query }}</td>
                                <td>{{ stats.count }}</td>
                                <td>{{ stats.avg_duration|round(3) }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                    {% endif %}
                </div>
                {% endif %}
            </div>

            <div class="footer">
                <p>Generated by Audit-Provenance Dashboard | IPFS Datasets Python</p>
            </div>
        </body>
        </html>
        """

        # Create the template
        template = Template(template_string)

        # Render the HTML
        html = template.render(
            generated_at=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            audit_summary=audit_summary,
            provenance_summary=provenance_summary,
            query_summary=query_summary,
            data_ids=data_ids,
            chart_paths={os.path.basename(path): path for path in chart_paths}
        )

        # Write to file
        with open(dashboard_path, 'w') as f:
            f.write(html)

        return dashboard_path

    def _get_provenance_events(self, data_ids: List[str]) -> List[Dict[str, Any]]:
        """
        Get provenance events for specific data entities.

        Args:
            data_ids: List of data entity IDs

        Returns:
            List[Dict[str, Any]]: List of provenance events
        """
        events = []

        # Check if provenance manager is available
        if not hasattr(self.provenance_dashboard, 'provenance_manager') or \
           not self.provenance_dashboard.provenance_manager:
            return events

        provenance_manager = self.provenance_dashboard.provenance_manager

        # For each data ID, get its provenance records
        for data_id in data_ids:
            try:
                # Get lineage for this entity
                lineage = provenance_manager.get_data_lineage(data_id)

                # Convert record to event format
                if 'record' in lineage and 'record_id' in lineage:
                    record = lineage['record']

                    events.append({
                        'entity_id': data_id,
                        'record_id': lineage['record_id'],
                        'type': record.get('record_type', 'unknown'),
                        'description': record.get('description', ''),
                        'timestamp': record.get('timestamp', 0),
                        'parameters': record.get('parameters', {})
                    })

                # Process parent records
                if 'parents' in lineage:
                    for parent in lineage['parents']:
                        if 'record' in parent and 'record_id' in parent:
                            parent_record = parent['record']

                            events.append({
                                'entity_id': parent.get('entity_id', 'unknown'),
                                'record_id': parent['record_id'],
                                'type': parent_record.get('record_type', 'unknown'),
                                'description': parent_record.get('description', ''),
                                'timestamp': parent_record.get('timestamp', 0),
                                'parameters': parent_record.get('parameters', {})
                            })
            except Exception as e:
                logging.warning(f"Error getting provenance events for {data_id}: {str(e)}")

        # Sort events by timestamp
        events.sort(key=lambda x: x['timestamp'])

        return events

    def _get_audit_events_for_entities(self, data_ids: List[str], hours: int = 24) -> List[Dict[str, Any]]:
        """
        Get audit events related to specific data entities.

        Args:
            data_ids: List of data entity IDs
            hours: Number of hours to look back

        Returns:
            List[Dict[str, Any]]: List of audit events
        """
        events = []

        # Calculate time range
        end_time = time.time()
        start_time = end_time - (hours * 3600)

        # TODO: This is a placeholder - in a real implementation, we would filter audit events
        # based on the data_ids. For now, we'll just return all recent audit events.

        # Get time series data from audit metrics
        time_series = self.audit_metrics.time_series['by_category_action']

        # Filter buckets by time range
        buckets = sorted([ts for ts in time_series.keys() if ts >= start_time])

        # Convert to events
        for bucket in buckets:
            for category, actions in time_series[bucket].items():
                for action, count in actions.items():
                    for _ in range(count):
                        events.append({
                            'category': category,
                            'action': action,
                            'timestamp': bucket,
                            'status': 'success'  # Placeholder
                        })

        # Sort by timestamp
        events.sort(key=lambda x: x['timestamp'])

        return events

    def _get_provenance_metrics(self) -> Dict[str, Any]:
        """
        Get metrics about provenance tracking.

        Returns:
            Dict[str, Any]: Provenance metrics summary
        """
        metrics = {
            'total_records': 0,
            'total_entities': 0,
            'by_type': {},
            'recent_operations': []
        }

        # Check if provenance manager is available
        if not hasattr(self.provenance_dashboard, 'provenance_manager') or \
           not self.provenance_dashboard.provenance_manager:
            return metrics

        provenance_manager = self.provenance_dashboard.provenance_manager

        # Get total number of records
        metrics['total_records'] = len(provenance_manager.records)

        # Get total number of entities
        metrics['total_entities'] = len(provenance_manager.entity_latest_record)

        # Get record types
        record_types = {}
        for record_id, record in provenance_manager.records.items():
            record_type = record.record_type
            record_types[record_type] = record_types.get(record_type, 0) + 1

        metrics['by_type'] = record_types

        # Get recent operations
        recent_operations = []

        # Sort records by timestamp and take the 10 most recent
        sorted_records = sorted(
            [(record_id, record) for record_id, record in provenance_manager.records.items()],
            key=lambda x: x[1].timestamp,
            reverse=True
        )[:10]

        # Convert to operation list
        for record_id, record in sorted_records:
            # Find entity ID for this record
            entity_id = "unknown"
            for ent_id, rec_id in provenance_manager.entity_latest_record.items():
                if rec_id == record_id:
                    entity_id = ent_id
                    break

            # Add to recent operations
            recent_operations.append({
                'operation': record.record_type,
                'entity_id': entity_id,
                'record_id': record_id,
                'timestamp': datetime.datetime.fromtimestamp(record.timestamp).strftime('%Y-%m-%d %H:%M:%S'),
                'description': record.description
            })

        metrics['recent_operations'] = recent_operations

        # Add timing information if available
        timing = {}
        for record_id, record in provenance_manager.records.items():
            if hasattr(record, 'parameters') and record.parameters:
                duration = record.parameters.get('duration_ms')
                if duration:
                    operation = record.record_type
                    if operation not in timing:
                        timing[operation] = []
                    timing[operation].append(duration)

        # Calculate average durations
        avg_timing = {}
        for operation, durations in timing.items():
            avg_timing[operation] = sum(durations) / len(durations)

        metrics['timing'] = avg_timing

        return metrics

    def _get_recent_entities(self, limit: int = 10) -> List[str]:
        """
        Get the most recent data entities from the provenance manager.

        Args:
            limit: Maximum number of entities to return

        Returns:
            List[str]: List of recent entity IDs
        """
        # Check if provenance dashboard is available
        if not hasattr(self.provenance_dashboard, '_get_recent_entities'):
            raise ValueError("Provenance dashboard not properly initialized")

        return self.provenance_dashboard._get_recent_entities(limit)


def setup_audit_provenance_dashboard(
    audit_logger: Optional[AuditLogger] = None,
    provenance_manager: Optional[ProvenanceManager] = None,
    query_visualizer: Optional[RAGQueryVisualizer] = None
) -> AuditProvenanceDashboard:
    """
    Set up an integrated audit-provenance dashboard with all available components.

    Args:
        audit_logger: Optional AuditLogger instance
        provenance_manager: Optional ProvenanceManager instance
        query_visualizer: Optional RAGQueryVisualizer instance

    Returns:
        AuditProvenanceDashboard: Configured dashboard instance
    """
    # Create audit metrics aggregator
    audit_metrics = AuditMetricsAggregator()

    # Create audit logger if not provided
    if not audit_logger:
        audit_logger = AuditLogger()
        # Add handler to feed events to metrics aggregator
        audit_logger.add_handler(lambda event: audit_metrics.process_event(event))

    # Set up provenance dashboard
    from ipfs_datasets_py.provenance_dashboard import setup_provenance_dashboard
    provenance_dashboard = setup_provenance_dashboard(
        provenance_manager=provenance_manager,
        query_metrics=query_visualizer.metrics if query_visualizer else None,
        audit_metrics=audit_metrics
    )

    # Create the integrated dashboard
    dashboard = AuditProvenanceDashboard(
        audit_metrics=audit_metrics,
        provenance_dashboard=provenance_dashboard,
        audit_logger=audit_logger,
        query_visualizer=query_visualizer
    )

    return dashboard
