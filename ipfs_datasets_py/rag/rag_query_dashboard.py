"""
Unified Real-Time Dashboard for RAG Query and Audit Data

This module provides a comprehensive dashboard that integrates RAG query metrics
and audit data in a real-time updating interface. It combines static visualizations
with interactive components that can be updated as new data becomes available.
"""

import os
import time
import json
import logging
import threading
import datetime
from typing import Dict, List, Any, Optional, Tuple, Union, Set
from collections import defaultdict

# Import visualization components
try:
    import numpy as np
    import pandas as pd
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend for server environments
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import MaxNLocator
    from matplotlib.figure import Figure
    import seaborn as sns
    VISUALIZATION_LIBS_AVAILABLE = True
except ImportError:
    VISUALIZATION_LIBS_AVAILABLE = False

# Import interactive visualization libraries
try:
    import plotly.express as px
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    INTERACTIVE_LIBS_AVAILABLE = True
except ImportError:
    INTERACTIVE_LIBS_AVAILABLE = False

# Import template engine for dashboard generation
try:
    from jinja2 import Template, Environment, FileSystemLoader
    TEMPLATE_ENGINE_AVAILABLE = True
except ImportError:
    TEMPLATE_ENGINE_AVAILABLE = False

# Import WebSocket libraries for real-time updates
try:
    import websocket
    import tornado.ioloop
    import tornado.web
    import tornado.websocket
    REALTIME_LIBS_AVAILABLE = True
except ImportError:
    REALTIME_LIBS_AVAILABLE = False

# Import visualization components from other modules
from ipfs_datasets_py.rag_query_visualization import (
    RAGQueryDashboard,
    EnhancedQueryVisualizer
)

from ipfs_datasets_py.rag_query_optimizer import (
    QueryMetricsCollector,
    GraphRAGQueryStats
)

# Import audit components
try:
    from ipfs_datasets_py.audit.audit_visualization import (
        AuditMetricsAggregator,
        AuditVisualizer,
        create_interactive_audit_trends
    )
    from ipfs_datasets_py.audit.audit_logger import (
        AuditLogger, AuditEvent, AuditLevel, AuditCategory
    )
    AUDIT_COMPONENTS_AVAILABLE = True
except ImportError:
    AUDIT_COMPONENTS_AVAILABLE = False

# Try to import enhanced visualization component if available
try:
    from ipfs_datasets_py.enhanced_rag_visualization import EnhancedQueryAuditVisualizer
    ENHANCED_VIS_AVAILABLE = True
except ImportError:
    ENHANCED_VIS_AVAILABLE = False


class RealTimeDashboardServer:
    """
    WebSocket server that provides real-time dashboard updates.

    This class manages WebSocket connections and broadcasts updates
    to connected clients when new metrics data is available.
    """

    def __init__(self, port=8888, update_interval=5):
        """
        Initialize the real-time dashboard server.

        Args:
            port: Port number for the WebSocket server
            update_interval: How often to check for updates (seconds)
        """
        if not REALTIME_LIBS_AVAILABLE:
            raise ImportError("Real-time libraries (tornado, websocket) not available")

        self.port = port
        self.update_interval = update_interval
        self.clients = set()
        self.metrics_data = {}
        self.update_thread = None
        self.running = False
        self.application = None
        self.metrics_collectors = []

    def register_metrics_collector(self, collector):
        """
        Register a metrics collector with the dashboard server.

        Args:
            collector: QueryMetricsCollector or AuditMetricsAggregator
        """
        self.metrics_collectors.append(collector)

    def start(self):
        """Start the WebSocket server and updater thread."""
        if self.running:
            logging.warning("Dashboard server is already running")
            return

        # Define WebSocket handler
        dashboard_server = self

        class DashboardWebSocketHandler(tornado.websocket.WebSocketHandler):
            def check_origin(self, origin):
                # Allow connections from any origin
                return True

            def open(self):
                logging.info("New dashboard client connected")
                dashboard_server.clients.add(self)
                # Send initial data
                self.write_message(json.dumps(dashboard_server.metrics_data))

            def on_close(self):
                logging.info("Dashboard client disconnected")
                dashboard_server.clients.remove(self)

        # Create Tornado application
        self.application = tornado.web.Application([
            (r"/dashboardws", DashboardWebSocketHandler),
            (r"/(.*)", tornado.web.StaticFileHandler, {"path": os.path.join(os.path.dirname(__file__), "static/dashboard"), "default_filename": "index.html"})
        ])

        # Start server
        self.application.listen(self.port)
        logging.info(f"Dashboard server started on port {self.port}")

        # Start updater thread
        self.running = True
        self.update_thread = threading.Thread(target=self._update_loop)
        self.update_thread.daemon = True
        self.update_thread.start()

        # Start Tornado IO loop
        tornado.ioloop.IOLoop.current().start()

    def stop(self):
        """Stop the WebSocket server and updater thread."""
        if not self.running:
            return

        self.running = False
        if self.update_thread:
            self.update_thread.join(timeout=2)

        # Stop Tornado IO loop
        tornado.ioloop.IOLoop.current().stop()
        logging.info("Dashboard server stopped")

    def _update_loop(self):
        """Background thread that periodically checks for updates and broadcasts to clients."""
        while self.running:
            try:
                # Collect metrics from all registered collectors
                has_updates = self._collect_metrics()

                # Broadcast updates if there are any
                if has_updates and self.clients:
                    message = json.dumps(self.metrics_data)
                    for client in list(self.clients):
                        try:
                            client.write_message(message)
                        except Exception as e:
                            logging.error(f"Error sending to client: {str(e)}")
                            # Remove failed client
                            if client in self.clients:
                                self.clients.remove(client)
            except Exception as e:
                logging.error(f"Error in update loop: {str(e)}")

            # Sleep until next update
            time.sleep(self.update_interval)

    def _collect_metrics(self):
        """
        Collect metrics from all registered collectors.

        Returns:
            bool: True if there were updates, False otherwise
        """
        has_updates = False
        new_data = {}

        # Collect query metrics
        for collector in self.metrics_collectors:
            try:
                if isinstance(collector, QueryMetricsCollector):
                    metrics = self._collect_query_metrics(collector)
                    if metrics:
                        new_data["query_metrics"] = metrics
                        has_updates = True

                elif isinstance(collector, AuditMetricsAggregator):
                    metrics = self._collect_audit_metrics(collector)
                    if metrics:
                        new_data["audit_metrics"] = metrics
                        has_updates = True
            except Exception as e:
                logging.error(f"Error collecting metrics from {type(collector).__name__}: {str(e)}")

        # Update metrics data if there were changes
        if has_updates:
            self.metrics_data.update(new_data)

        return has_updates

    def _collect_query_metrics(self, collector):
        """
        Collect metrics from a QueryMetricsCollector.

        Args:
            collector: QueryMetricsCollector instance

        Returns:
            dict: Query metrics data
        """
        metrics = {}

        # Basic query statistics
        metrics["query_count"] = collector.get_query_count()
        metrics["avg_latency"] = collector.get_average_latency()
        metrics["success_rate"] = collector.get_success_rate()

        # Recent queries
        recent_queries = collector.get_recent_queries(10)
        metrics["recent_queries"] = [
            {
                "query_id": q.query_id,
                "timestamp": q.timestamp,
                "duration_ms": q.duration_ms,
                "status": q.status,
                "query_type": q.query_type
            } for q in recent_queries
        ]

        # Performance over time (last hour in 5-minute intervals)
        time_series = collector.get_performance_time_series(
            metrics=["latency", "success_rate"],
            interval_minutes=5,
            lookback_hours=1
        )
        metrics["time_series"] = time_series

        return metrics

    def _collect_audit_metrics(self, collector):
        """
        Collect metrics from an AuditMetricsAggregator.

        Args:
            collector: AuditMetricsAggregator instance

        Returns:
            dict: Audit metrics data
        """
        metrics = {}

        # Get summary metrics
        summary = collector.get_metrics_summary()
        metrics["summary"] = summary

        # Get security insights
        security = collector.get_security_insights()
        metrics["security"] = security

        # Recent events
        time_series = collector.get_time_series_data()
        metrics["time_series"] = {
            # Convert to a format suitable for JSON
            "by_level": {
                level: [
                    {"timestamp": item["timestamp"], "count": item["count"]}
                    for item in data
                ]
                for level, data in time_series.get("by_level", {}).items()
            },
            "by_category": {
                category: [
                    {"timestamp": item["timestamp"], "count": item["count"]}
                    for item in data
                ]
                for category, data in time_series.get("by_category", {}).items()
            }
        }

        return metrics


class UnifiedDashboard:
    """
    Unified dashboard that combines RAG query metrics and audit data.

    This class provides methods to generate comprehensive dashboards
    with both static and real-time components.
    """

    def __init__(self, dashboard_dir=None, enable_realtime=False, port=8888):
        """
        Initialize the unified dashboard.

        Args:
            dashboard_dir: Directory to store dashboard files
            enable_realtime: Whether to enable real-time updates
            port: Port for real-time server (if enabled)
        """
        # Create dashboard directory if not specified
        if dashboard_dir is None:
            dashboard_dir = os.path.join(os.getcwd(), "dashboard")

        self.dashboard_dir = dashboard_dir
        os.makedirs(dashboard_dir, exist_ok=True)

        # Create static directory for dashboard assets
        self.static_dir = os.path.join(dashboard_dir, "static")
        os.makedirs(self.static_dir, exist_ok=True)

        # Set up visualization components
        self.rag_dashboard = RAGQueryDashboard()

        if AUDIT_COMPONENTS_AVAILABLE:
            if ENHANCED_VIS_AVAILABLE:
                self.visualizer = EnhancedQueryAuditVisualizer()
            else:
                self.visualizer = AuditVisualizer()
        else:
            self.visualizer = None

        # Set up real-time server if enabled
        self.enable_realtime = enable_realtime and REALTIME_LIBS_AVAILABLE
        self.server = None

        if self.enable_realtime:
            try:
                self.server = RealTimeDashboardServer(port=port)
            except ImportError:
                logging.warning("Real-time libraries not available. Falling back to static dashboard.")
                self.enable_realtime = False

    def register_metrics_collector(self, collector):
        """
        Register a metrics collector with the dashboard.

        Args:
            collector: QueryMetricsCollector or AuditMetricsAggregator
        """
        if self.enable_realtime and self.server:
            self.server.register_metrics_collector(collector)

    def generate_dashboard(
        self,
        query_metrics_collector=None,
        audit_metrics_aggregator=None,
        title="Unified Query & Audit Dashboard",
        theme="light",
        include_performance=True,
        include_security=True,
        include_interactive=True,
        include_realtime=None  # None means use the instance default
    ):
        """
        Generate a comprehensive dashboard with both static and real-time components.

        Args:
            query_metrics_collector: QueryMetricsCollector for query metrics
            audit_metrics_aggregator: AuditMetricsAggregator for audit metrics
            title: Dashboard title
            theme: Dashboard theme ('light' or 'dark')
            include_performance: Whether to include performance metrics
            include_security: Whether to include security insights
            include_interactive: Whether to include interactive visualizations
            include_realtime: Override whether to include real-time components

        Returns:
            str: Path to the dashboard HTML file
        """
        # Determine whether to include real-time components
        if include_realtime is None:
            include_realtime = self.enable_realtime

        # Register collectors if they're not already registered
        if include_realtime and self.server:
            if query_metrics_collector:
                self.server.register_metrics_collector(query_metrics_collector)
            if audit_metrics_aggregator:
                self.server.register_metrics_collector(audit_metrics_aggregator)

        # Set up paths
        dashboard_path = os.path.join(self.dashboard_dir, "index.html")
        static_visualizations_dir = os.path.join(self.static_dir, "visualizations")
        os.makedirs(static_visualizations_dir, exist_ok=True)

        # Generate static visualizations
        visualization_paths = {}

        # Generate query metrics visualizations
        if query_metrics_collector:
            # Generate performance visualizations
            if include_performance:
                perf_path = os.path.join(static_visualizations_dir, "query_performance.png")
                self.rag_dashboard.visualize_query_performance(
                    metrics_collector=query_metrics_collector,
                    output_file=perf_path,
                    show_plot=False
                )
                visualization_paths["query_performance"] = os.path.relpath(perf_path, self.dashboard_dir)

                # Generate query type distribution
                types_path = os.path.join(static_visualizations_dir, "query_types.png")
                self.rag_dashboard.visualize_query_types(
                    metrics_collector=query_metrics_collector,
                    output_file=types_path,
                    show_plot=False
                )
                visualization_paths["query_types"] = os.path.relpath(types_path, self.dashboard_dir)

        # Generate audit visualizations
        if audit_metrics_aggregator and AUDIT_COMPONENTS_AVAILABLE:
            # Generate security visualizations
            if include_security:
                # Create AuditVisualizer if not already created
                if self.visualizer is None:
                    self.visualizer = AuditVisualizer(metrics=audit_metrics_aggregator)

                # Plot events by category
                category_path = os.path.join(static_visualizations_dir, "events_by_category.png")
                self.visualizer.plot_events_by_category(output_file=category_path)
                visualization_paths["events_by_category"] = os.path.relpath(category_path, self.dashboard_dir)

                # Plot events by level
                level_path = os.path.join(static_visualizations_dir, "events_by_level.png")
                self.visualizer.plot_events_by_level(output_file=level_path)
                visualization_paths["events_by_level"] = os.path.relpath(level_path, self.dashboard_dir)

                # Plot login failures
                login_path = os.path.join(static_visualizations_dir, "login_failures.png")
                self.visualizer.plot_login_failures(output_file=login_path)
                visualization_paths["login_failures"] = os.path.relpath(login_path, self.dashboard_dir)

        # Generate integrated visualizations if both collectors are available
        if query_metrics_collector and audit_metrics_aggregator:
            # Generate query-audit correlation timeline
            timeline_path = os.path.join(static_visualizations_dir, "query_audit_timeline.png")
            try:
                self.rag_dashboard.visualize_query_audit_metrics(
                    audit_metrics_aggregator=audit_metrics_aggregator,
                    output_file=timeline_path,
                    show_plot=False
                )
                visualization_paths["query_audit_timeline"] = os.path.relpath(timeline_path, self.dashboard_dir)
            except Exception as e:
                logging.error(f"Error generating query-audit timeline: {str(e)}")

            # Generate correlation analysis
            if ENHANCED_VIS_AVAILABLE:
                correlation_path = os.path.join(static_visualizations_dir, "query_audit_correlation.png")
                try:
                    self.rag_dashboard.analyze_query_audit_correlation(
                        audit_metrics_aggregator=audit_metrics_aggregator,
                        output_file=correlation_path,
                        show_plot=False
                    )
                    visualization_paths["query_audit_correlation"] = os.path.relpath(correlation_path, self.dashboard_dir)
                except Exception as e:
                    logging.error(f"Error generating correlation analysis: {str(e)}")

        # Generate interactive visualizations
        interactive_visualizations = {}
        if include_interactive and INTERACTIVE_LIBS_AVAILABLE:
            # Create interactive directory
            interactive_dir = os.path.join(self.static_dir, "interactive")
            os.makedirs(interactive_dir, exist_ok=True)

            # Generate query performance interactive visualization
            if query_metrics_collector:
                perf_interactive_path = os.path.join(interactive_dir, "query_performance_interactive.html")
                try:
                    self.rag_dashboard.visualize_query_performance(
                        metrics_collector=query_metrics_collector,
                        output_file=perf_interactive_path,
                        interactive=True,
                        show_plot=False
                    )
                    interactive_visualizations["query_performance"] = os.path.relpath(perf_interactive_path, self.dashboard_dir)
                except Exception as e:
                    logging.error(f"Error generating interactive query performance: {str(e)}")

            # Generate audit trends interactive visualization
            if audit_metrics_aggregator and AUDIT_COMPONENTS_AVAILABLE:
                # Daily trends
                daily_trends_path = os.path.join(interactive_dir, "daily_audit_trends.html")
                try:
                    self.rag_dashboard.generate_interactive_audit_trends(
                        audit_metrics_aggregator=audit_metrics_aggregator,
                        period="daily",
                        lookback_days=30,
                        output_file=daily_trends_path,
                        show_plot=False
                    )
                    interactive_visualizations["daily_audit_trends"] = os.path.relpath(daily_trends_path, self.dashboard_dir)
                except Exception as e:
                    logging.error(f"Error generating interactive daily audit trends: {str(e)}")

                # Hourly trends
                hourly_trends_path = os.path.join(interactive_dir, "hourly_audit_trends.html")
                try:
                    self.rag_dashboard.generate_interactive_audit_trends(
                        audit_metrics_aggregator=audit_metrics_aggregator,
                        period="hourly",
                        lookback_days=7,
                        output_file=hourly_trends_path,
                        show_plot=False
                    )
                    interactive_visualizations["hourly_audit_trends"] = os.path.relpath(hourly_trends_path, self.dashboard_dir)
                except Exception as e:
                    logging.error(f"Error generating interactive hourly audit trends: {str(e)}")

                # Security-focused trends
                security_trends_path = os.path.join(interactive_dir, "security_audit_trends.html")
                try:
                    self.rag_dashboard.generate_interactive_audit_trends(
                        audit_metrics_aggregator=audit_metrics_aggregator,
                        period="daily",
                        lookback_days=30,
                        categories=["AUTHENTICATION", "AUTHORIZATION", "SECURITY"],
                        output_file=security_trends_path,
                        show_plot=False
                    )
                    interactive_visualizations["security_audit_trends"] = os.path.relpath(security_trends_path, self.dashboard_dir)
                except Exception as e:
                    logging.error(f"Error generating interactive security audit trends: {str(e)}")

        # Generate dashboard HTML
        if not TEMPLATE_ENGINE_AVAILABLE:
            # Basic HTML generation without Jinja2
            dashboard_html = self._generate_basic_html(
                title=title,
                theme=theme,
                static_visualizations=visualization_paths,
                interactive_visualizations=interactive_visualizations,
                has_query_metrics=query_metrics_collector is not None,
                has_audit_metrics=audit_metrics_aggregator is not None,
                enable_realtime=include_realtime,
                websocket_port=self.server.port if self.server else None
            )
        else:
            # Use Jinja2 for more sophisticated templates
            dashboard_html = self._generate_template_html(
                title=title,
                theme=theme,
                static_visualizations=visualization_paths,
                interactive_visualizations=interactive_visualizations,
                has_query_metrics=query_metrics_collector is not None,
                has_audit_metrics=audit_metrics_aggregator is not None,
                enable_realtime=include_realtime,
                websocket_port=self.server.port if self.server else None
            )

        # Write dashboard HTML
        with open(dashboard_path, "w") as f:
            f.write(dashboard_html)

        # Generate necessary JavaScript for real-time updates
        if include_realtime:
            self._generate_realtime_js()

        # Start real-time server if not already running
        if include_realtime and self.server and not self.server.running:
            # Start server in a separate thread
            server_thread = threading.Thread(target=self.server.start)
            server_thread.daemon = True
            server_thread.start()

        return dashboard_path

    def _generate_basic_html(
        self,
        title,
        theme,
        static_visualizations,
        interactive_visualizations,
        has_query_metrics,
        has_audit_metrics,
        enable_realtime,
        websocket_port
    ):
        """
        Generate basic HTML for the dashboard without using Jinja2.

        Args:
            title: Dashboard title
            theme: 'light' or 'dark'
            static_visualizations: Paths to static visualizations
            interactive_visualizations: Paths to interactive visualizations
            has_query_metrics: Whether query metrics are available
            has_audit_metrics: Whether audit metrics are available
            enable_realtime: Whether to include real-time updates
            websocket_port: Port for WebSocket connection

        Returns:
            str: HTML content
        """
        # Determine CSS class based on theme
        theme_class = "dashboard-dark" if theme == "dark" else "dashboard-light"

        # Start HTML
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 0;
            background-color: {('#1a1a1a' if theme == 'dark' else '#f5f5f5')};
            color: {('#f5f5f5' if theme == 'dark' else '#333')};
        }}
        .dashboard {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }}
        header {{
            margin-bottom: 20px;
            border-bottom: 1px solid {('#444' if theme == 'dark' else '#ddd')};
            padding-bottom: 10px;
        }}
        h1, h2, h3 {{
            color: {('#fff' if theme == 'dark' else '#333')};
        }}
        .section {{
            margin-bottom: 30px;
            background-color: {('#2a2a2a' if theme == 'dark' else '#fff')};
            border-radius: 5px;
            padding: 15px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
        .visualization {{
            text-align: center;
            margin: 15px 0;
        }}
        .visualization img {{
            max-width: 100%;
            border-radius: 5px;
            border: 1px solid {('#444' if theme == 'dark' else '#ddd')};
        }}
        .interactive-frame {{
            width: 100%;
            height: 600px;
            border: none;
            border-radius: 5px;
            background-color: {('#fff' if theme == 'dark' else '#fff')};
        }}
        .stats-box {{
            display: inline-block;
            background-color: {('#3a3a3a' if theme == 'dark' else '#f9f9f9')};
            border-radius: 5px;
            padding: 15px;
            margin: 10px;
            min-width: 150px;
            text-align: center;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
        .stats-value {{
            font-size: 24px;
            font-weight: bold;
            margin: 10px 0;
        }}
        .stats-label {{
            font-size: 14px;
            color: {('#aaa' if theme == 'dark' else '#666')};
        }}
        .tabbed-content {{
            margin-top: 20px;
        }}
        .tab-links {{
            display: flex;
            border-bottom: 1px solid {('#444' if theme == 'dark' else '#ddd')};
        }}
        .tab-link {{
            padding: 10px 15px;
            background-color: {('#3a3a3a' if theme == 'dark' else '#f9f9f9')};
            border: none;
            border-radius: 5px 5px 0 0;
            margin-right: 5px;
            cursor: pointer;
            color: {('#ddd' if theme == 'dark' else '#333')};
        }}
        .tab-link.active {{
            background-color: {('#4a4a4a' if theme == 'dark' else '#fff')};
            color: {('#fff' if theme == 'dark' else '#000')};
        }}
        .tab-content {{
            display: none;
            padding: 15px;
            background-color: {('#2a2a2a' if theme == 'dark' else '#fff')};
            border-radius: 0 5px 5px 5px;
        }}
        .tab-content.active {{
            display: block;
        }}
    </style>
</head>
<body>
    <div class="dashboard {theme_class}">
        <header>
            <h1>{title}</h1>
            <p>Generated on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </header>
"""

        # Add real-time metrics section if enabled
        if enable_realtime:
            html += """
        <div class="section" id="realtime-metrics">
            <h2>Real-Time Metrics</h2>
            <div class="row" id="realtime-stats">
                <div class="stats-box">
                    <div class="stats-value" id="rt-query-count">-</div>
                    <div class="stats-label">Total Queries</div>
                </div>
                <div class="stats-box">
                    <div class="stats-value" id="rt-avg-latency">-</div>
                    <div class="stats-label">Avg Latency (ms)</div>
                </div>
                <div class="stats-box">
                    <div class="stats-value" id="rt-success-rate">-</div>
                    <div class="stats-label">Success Rate (%)</div>
                </div>
                <div class="stats-box">
                    <div class="stats-value" id="rt-audit-count">-</div>
                    <div class="stats-label">Audit Events</div>
                </div>
                <div class="stats-box">
                    <div class="stats-value" id="rt-error-rate">-</div>
                    <div class="stats-label">Error Rate (%)</div>
                </div>
            </div>
            <div id="realtime-chart" style="width:100%; height:300px;"></div>
            <div class="tabbed-content">
                <div class="tab-links">
                    <button class="tab-link active" onclick="openTab(event, 'rt-recent-queries')">Recent Queries</button>
                    <button class="tab-link" onclick="openTab(event, 'rt-security-events')">Security Events</button>
                </div>
                <div id="rt-recent-queries" class="tab-content active">
                    <table id="recent-queries-table" style="width:100%; border-collapse: collapse;">
                        <thead>
                            <tr>
                                <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Query ID</th>
                                <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Time</th>
                                <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Type</th>
                                <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Duration (ms)</th>
                                <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Status</th>
                            </tr>
                        </thead>
                        <tbody id="recent-queries-body">
                            <tr><td colspan="5" style="text-align:center; padding:10px;">Waiting for data...</td></tr>
                        </tbody>
                    </table>
                </div>
                <div id="rt-security-events" class="tab-content">
                    <div id="security-alerts">
                        <p>Waiting for security events...</p>
                    </div>
                </div>
            </div>
        </div>
"""

        # Add static visualizations section
        if static_visualizations:
            html += """
        <div class="section">
            <h2>Static Visualizations</h2>
            <div class="tabbed-content">
                <div class="tab-links">
                    <button class="tab-link active" onclick="openTab(event, 'tab-query-metrics')">Query Metrics</button>
                    <button class="tab-link" onclick="openTab(event, 'tab-audit-metrics')">Audit Metrics</button>
                    <button class="tab-link" onclick="openTab(event, 'tab-integrated')">Integrated View</button>
                </div>
"""

            # Query metrics tab
            html += """
                <div id="tab-query-metrics" class="tab-content active">
"""
            if "query_performance" in static_visualizations:
                html += f"""
                    <div class="visualization">
                        <h3>Query Performance</h3>
                        <img src="{static_visualizations['query_performance']}" alt="Query Performance">
                    </div>
"""
            if "query_types" in static_visualizations:
                html += f"""
                    <div class="visualization">
                        <h3>Query Type Distribution</h3>
                        <img src="{static_visualizations['query_types']}" alt="Query Types">
                    </div>
"""
            html += """
                </div>
"""

            # Audit metrics tab
            html += """
                <div id="tab-audit-metrics" class="tab-content">
"""
            if "events_by_category" in static_visualizations:
                html += f"""
                    <div class="visualization">
                        <h3>Events by Category</h3>
                        <img src="{static_visualizations['events_by_category']}" alt="Events by Category">
                    </div>
"""
            if "events_by_level" in static_visualizations:
                html += f"""
                    <div class="visualization">
                        <h3>Events by Level</h3>
                        <img src="{static_visualizations['events_by_level']}" alt="Events by Level">
                    </div>
"""
            if "login_failures" in static_visualizations:
                html += f"""
                    <div class="visualization">
                        <h3>Login Failures</h3>
                        <img src="{static_visualizations['login_failures']}" alt="Login Failures">
                    </div>
"""
            html += """
                </div>
"""

            # Integrated view tab
            html += """
                <div id="tab-integrated" class="tab-content">
"""
            if "query_audit_timeline" in static_visualizations:
                html += f"""
                    <div class="visualization">
                        <h3>Query-Audit Timeline</h3>
                        <img src="{static_visualizations['query_audit_timeline']}" alt="Query-Audit Timeline">
                    </div>
"""
            if "query_audit_correlation" in static_visualizations:
                html += f"""
                    <div class="visualization">
                        <h3>Query-Audit Correlation Analysis</h3>
                        <img src="{static_visualizations['query_audit_correlation']}" alt="Query-Audit Correlation">
                    </div>
"""
            html += """
                </div>
            </div>
        </div>
"""

        # Add interactive visualizations section
        if interactive_visualizations:
            html += """
        <div class="section">
            <h2>Interactive Visualizations</h2>
            <div class="tabbed-content">
                <div class="tab-links">
"""
            # Create tabs for different types of interactive visualizations
            has_perf = "query_performance" in interactive_visualizations
            has_daily = "daily_audit_trends" in interactive_visualizations
            has_hourly = "hourly_audit_trends" in interactive_visualizations
            has_security = "security_audit_trends" in interactive_visualizations

            if has_perf:
                html += """
                    <button class="tab-link active" onclick="openTab(event, 'tab-inter-query')">Query Performance</button>
"""
            if has_daily:
                active = "" if has_perf else "active"
                html += f"""
                    <button class="tab-link {active}" onclick="openTab(event, 'tab-inter-daily')">Daily Audit Trends</button>
"""
            if has_hourly:
                active = "" if has_perf or has_daily else "active"
                html += f"""
                    <button class="tab-link {active}" onclick="openTab(event, 'tab-inter-hourly')">Hourly Audit Trends</button>
"""
            if has_security:
                active = "" if has_perf or has_daily or has_hourly else "active"
                html += f"""
                    <button class="tab-link {active}" onclick="openTab(event, 'tab-inter-security')">Security Trends</button>
"""
            html += """
                </div>
"""

            # Add content for each tab
            if has_perf:
                html += f"""
                <div id="tab-inter-query" class="tab-content active">
                    <div class="visualization">
                        <h3>Interactive Query Performance</h3>
                        <iframe class="interactive-frame" src="{interactive_visualizations['query_performance']}"></iframe>
                    </div>
                </div>
"""
            if has_daily:
                active = "" if has_perf else "active"
                html += f"""
                <div id="tab-inter-daily" class="tab-content {active}">
                    <div class="visualization">
                        <h3>Daily Audit Trends (30 Days)</h3>
                        <iframe class="interactive-frame" src="{interactive_visualizations['daily_audit_trends']}"></iframe>
                    </div>
                </div>
"""
            if has_hourly:
                active = "" if has_perf or has_daily else "active"
                html += f"""
                <div id="tab-inter-hourly" class="tab-content {active}">
                    <div class="visualization">
                        <h3>Hourly Audit Trends (7 Days)</h3>
                        <iframe class="interactive-frame" src="{interactive_visualizations['hourly_audit_trends']}"></iframe>
                    </div>
                </div>
"""
            if has_security:
                active = "" if has_perf or has_daily or has_hourly else "active"
                html += f"""
                <div id="tab-inter-security" class="tab-content {active}">
                    <div class="visualization">
                        <h3>Security Event Trends</h3>
                        <iframe class="interactive-frame" src="{interactive_visualizations['security_audit_trends']}"></iframe>
                    </div>
                </div>
"""
            html += """
            </div>
        </div>
"""

        # Add JavaScript for tabs and real-time updates
        html += """
        <script>
            function openTab(evt, tabName) {
                var i, tabContent, tabLinks;

                // Hide all tab content
                tabContent = document.getElementsByClassName("tab-content");
                for (i = 0; i < tabContent.length; i++) {
                    tabContent[i].style.display = "none";
                }

                // Remove active class from all tab links
                tabLinks = document.getElementsByClassName("tab-link");
                for (i = 0; i < tabLinks.length; i++) {
                    tabLinks[i].className = tabLinks[i].className.replace(" active", "");
                }

                // Show the selected tab and add active class to the button
                document.getElementById(tabName).style.display = "block";
                evt.currentTarget.className += " active";
            }
        </script>
"""

        # Add WebSocket connection if real-time is enabled
        if enable_realtime:
            html += f"""
        <script src="static/dashboard.js"></script>
        <script>
            // Initialize WebSocket connection to real-time server
            initDashboard({websocket_port});
        </script>
"""

        # Close HTML
        html += """
    </div>
</body>
</html>
"""
        return html

    def _generate_template_html(
        self,
        title,
        theme,
        static_visualizations,
        interactive_visualizations,
        has_query_metrics,
        has_audit_metrics,
        enable_realtime,
        websocket_port
    ):
        """
        Generate HTML using Jinja2 templates.

        Args:
            title: Dashboard title
            theme: 'light' or 'dark'
            static_visualizations: Paths to static visualizations
            interactive_visualizations: Paths to interactive visualizations
            has_query_metrics: Whether query metrics are available
            has_audit_metrics: Whether audit metrics are available
            enable_realtime: Whether to include real-time updates
            websocket_port: Port for WebSocket connection

        Returns:
            str: HTML content
        """
        # Load template from string since we don't have a template file
        template_str = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }}</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 0;
            background-color: {{ theme_colors.background }};
            color: {{ theme_colors.text }};
        }
        .dashboard {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        header {
            margin-bottom: 20px;
            border-bottom: 1px solid {{ theme_colors.border }};
            padding-bottom: 10px;
        }
        h1, h2, h3 {
            color: {{ theme_colors.heading }};
        }
        .section {
            margin-bottom: 30px;
            background-color: {{ theme_colors.section_bg }};
            border-radius: 5px;
            padding: 15px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }
        .visualization {
            text-align: center;
            margin: 15px 0;
        }
        .visualization img {
            max-width: 100%;
            border-radius: 5px;
            border: 1px solid {{ theme_colors.border }};
        }
        .interactive-frame {
            width: 100%;
            height: 600px;
            border: none;
            border-radius: 5px;
            background-color: #fff;
        }
        .stats-box {
            display: inline-block;
            background-color: {{ theme_colors.stats_bg }};
            border-radius: 5px;
            padding: 15px;
            margin: 10px;
            min-width: 150px;
            text-align: center;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }
        .stats-value {
            font-size: 24px;
            font-weight: bold;
            margin: 10px 0;
        }
        .stats-label {
            font-size: 14px;
            color: {{ theme_colors.muted_text }};
        }
        .tabbed-content {
            margin-top: 20px;
        }
        .tab-links {
            display: flex;
            border-bottom: 1px solid {{ theme_colors.border }};
        }
        .tab-link {
            padding: 10px 15px;
            background-color: {{ theme_colors.tab_bg }};
            border: none;
            border-radius: 5px 5px 0 0;
            margin-right: 5px;
            cursor: pointer;
            color: {{ theme_colors.tab_text }};
        }
        .tab-link.active {
            background-color: {{ theme_colors.active_tab_bg }};
            color: {{ theme_colors.active_tab_text }};
        }
        .tab-content {
            display: none;
            padding: 15px;
            background-color: {{ theme_colors.section_bg }};
            border-radius: 0 5px 5px 5px;
        }
        .tab-content.active {
            display: block;
        }
    </style>
</head>
<body>
    <div class="dashboard dashboard-{{ theme }}">
        <header>
            <h1>{{ title }}</h1>
            <p>Generated on {{ generation_time }}</p>
        </header>

        {% if enable_realtime %}
        <div class="section" id="realtime-metrics">
            <h2>Real-Time Metrics</h2>
            <div class="row" id="realtime-stats">
                <div class="stats-box">
                    <div class="stats-value" id="rt-query-count">-</div>
                    <div class="stats-label">Total Queries</div>
                </div>
                <div class="stats-box">
                    <div class="stats-value" id="rt-avg-latency">-</div>
                    <div class="stats-label">Avg Latency (ms)</div>
                </div>
                <div class="stats-box">
                    <div class="stats-value" id="rt-success-rate">-</div>
                    <div class="stats-label">Success Rate (%)</div>
                </div>
                <div class="stats-box">
                    <div class="stats-value" id="rt-audit-count">-</div>
                    <div class="stats-label">Audit Events</div>
                </div>
                <div class="stats-box">
                    <div class="stats-value" id="rt-error-rate">-</div>
                    <div class="stats-label">Error Rate (%)</div>
                </div>
            </div>
            <div id="realtime-chart" style="width:100%; height:300px;"></div>
            <div class="tabbed-content">
                <div class="tab-links">
                    <button class="tab-link active" onclick="openTab(event, 'rt-recent-queries')">Recent Queries</button>
                    <button class="tab-link" onclick="openTab(event, 'rt-security-events')">Security Events</button>
                </div>
                <div id="rt-recent-queries" class="tab-content active">
                    <table id="recent-queries-table" style="width:100%; border-collapse: collapse;">
                        <thead>
                            <tr>
                                <th style="text-align:left; padding:8px; border-bottom:1px solid {{ theme_colors.border }};">Query ID</th>
                                <th style="text-align:left; padding:8px; border-bottom:1px solid {{ theme_colors.border }};">Time</th>
                                <th style="text-align:left; padding:8px; border-bottom:1px solid {{ theme_colors.border }};">Type</th>
                                <th style="text-align:left; padding:8px; border-bottom:1px solid {{ theme_colors.border }};">Duration (ms)</th>
                                <th style="text-align:left; padding:8px; border-bottom:1px solid {{ theme_colors.border }};">Status</th>
                            </tr>
                        </thead>
                        <tbody id="recent-queries-body">
                            <tr><td colspan="5" style="text-align:center; padding:10px;">Waiting for data...</td></tr>
                        </tbody>
                    </table>
                </div>
                <div id="rt-security-events" class="tab-content">
                    <div id="security-alerts">
                        <p>Waiting for security events...</p>
                    </div>
                </div>
            </div>
        </div>
        {% endif %}

        {% if static_visualizations %}
        <div class="section">
            <h2>Static Visualizations</h2>
            <div class="tabbed-content">
                <div class="tab-links">
                    <button class="tab-link active" onclick="openTab(event, 'tab-query-metrics')">Query Metrics</button>
                    <button class="tab-link" onclick="openTab(event, 'tab-audit-metrics')">Audit Metrics</button>
                    <button class="tab-link" onclick="openTab(event, 'tab-integrated')">Integrated View</button>
                </div>

                <div id="tab-query-metrics" class="tab-content active">
                    {% if 'query_performance' in static_visualizations %}
                    <div class="visualization">
                        <h3>Query Performance</h3>
                        <img src="{{ static_visualizations.query_performance }}" alt="Query Performance">
                    </div>
                    {% endif %}

                    {% if 'query_types' in static_visualizations %}
                    <div class="visualization">
                        <h3>Query Type Distribution</h3>
                        <img src="{{ static_visualizations.query_types }}" alt="Query Types">
                    </div>
                    {% endif %}
                </div>

                <div id="tab-audit-metrics" class="tab-content">
                    {% if 'events_by_category' in static_visualizations %}
                    <div class="visualization">
                        <h3>Events by Category</h3>
                        <img src="{{ static_visualizations.events_by_category }}" alt="Events by Category">
                    </div>
                    {% endif %}

                    {% if 'events_by_level' in static_visualizations %}
                    <div class="visualization">
                        <h3>Events by Level</h3>
                        <img src="{{ static_visualizations.events_by_level }}" alt="Events by Level">
                    </div>
                    {% endif %}

                    {% if 'login_failures' in static_visualizations %}
                    <div class="visualization">
                        <h3>Login Failures</h3>
                        <img src="{{ static_visualizations.login_failures }}" alt="Login Failures">
                    </div>
                    {% endif %}
                </div>

                <div id="tab-integrated" class="tab-content">
                    {% if 'query_audit_timeline' in static_visualizations %}
                    <div class="visualization">
                        <h3>Query-Audit Timeline</h3>
                        <img src="{{ static_visualizations.query_audit_timeline }}" alt="Query-Audit Timeline">
                    </div>
                    {% endif %}

                    {% if 'query_audit_correlation' in static_visualizations %}
                    <div class="visualization">
                        <h3>Query-Audit Correlation Analysis</h3>
                        <img src="{{ static_visualizations.query_audit_correlation }}" alt="Query-Audit Correlation">
                    </div>
                    {% endif %}
                </div>
            </div>
        </div>
        {% endif %}

        {% if interactive_visualizations %}
        <div class="section">
            <h2>Interactive Visualizations</h2>
            <div class="tabbed-content">
                <div class="tab-links">
                    {% set has_perf = 'query_performance' in interactive_visualizations %}
                    {% set has_daily = 'daily_audit_trends' in interactive_visualizations %}
                    {% set has_hourly = 'hourly_audit_trends' in interactive_visualizations %}
                    {% set has_security = 'security_audit_trends' in interactive_visualizations %}

                    {% if has_perf %}
                    <button class="tab-link active" onclick="openTab(event, 'tab-inter-query')">Query Performance</button>
                    {% endif %}

                    {% if has_daily %}
                    <button class="tab-link {{ '' if has_perf else 'active' }}" onclick="openTab(event, 'tab-inter-daily')">Daily Audit Trends</button>
                    {% endif %}

                    {% if has_hourly %}
                    <button class="tab-link {{ '' if has_perf or has_daily else 'active' }}" onclick="openTab(event, 'tab-inter-hourly')">Hourly Audit Trends</button>
                    {% endif %}

                    {% if has_security %}
                    <button class="tab-link {{ '' if has_perf or has_daily or has_hourly else 'active' }}" onclick="openTab(event, 'tab-inter-security')">Security Trends</button>
                    {% endif %}
                </div>

                {% if has_perf %}
                <div id="tab-inter-query" class="tab-content active">
                    <div class="visualization">
                        <h3>Interactive Query Performance</h3>
                        <iframe class="interactive-frame" src="{{ interactive_visualizations.query_performance }}"></iframe>
                    </div>
                </div>
                {% endif %}

                {% if has_daily %}
                <div id="tab-inter-daily" class="tab-content {{ '' if has_perf else 'active' }}">
                    <div class="visualization">
                        <h3>Daily Audit Trends (30 Days)</h3>
                        <iframe class="interactive-frame" src="{{ interactive_visualizations.daily_audit_trends }}"></iframe>
                    </div>
                </div>
                {% endif %}

                {% if has_hourly %}
                <div id="tab-inter-hourly" class="tab-content {{ '' if has_perf or has_daily else 'active' }}">
                    <div class="visualization">
                        <h3>Hourly Audit Trends (7 Days)</h3>
                        <iframe class="interactive-frame" src="{{ interactive_visualizations.hourly_audit_trends }}"></iframe>
                    </div>
                </div>
                {% endif %}

                {% if has_security %}
                <div id="tab-inter-security" class="tab-content {{ '' if has_perf or has_daily or has_hourly else 'active' }}">
                    <div class="visualization">
                        <h3>Security Event Trends</h3>
                        <iframe class="interactive-frame" src="{{ interactive_visualizations.security_audit_trends }}"></iframe>
                    </div>
                </div>
                {% endif %}
            </div>
        </div>
        {% endif %}

        <script>
            function openTab(evt, tabName) {
                var i, tabContent, tabLinks;

                // Hide all tab content
                tabContent = document.getElementsByClassName("tab-content");
                for (i = 0; i < tabContent.length; i++) {
                    tabContent[i].style.display = "none";
                }

                // Remove active class from all tab links
                tabLinks = document.getElementsByClassName("tab-link");
                for (i = 0; i < tabLinks.length; i++) {
                    tabLinks[i].className = tabLinks[i].className.replace(" active", "");
                }

                // Show the selected tab and add active class to the button
                document.getElementById(tabName).style.display = "block";
                evt.currentTarget.className += " active";
            }
        </script>

        {% if enable_realtime %}
        <script src="static/dashboard.js"></script>
        <script>
            // Initialize WebSocket connection to real-time server
            initDashboard({{ websocket_port }});
        </script>
        {% endif %}
    </div>
</body>
</html>"""

        # Set theme colors based on theme
        if theme == "dark":
            theme_colors = {
                "background": "#1a1a1a",
                "text": "#f5f5f5",
                "heading": "#fff",
                "section_bg": "#2a2a2a",
                "border": "#444",
                "stats_bg": "#3a3a3a",
                "muted_text": "#aaa",
                "tab_bg": "#3a3a3a",
                "tab_text": "#ddd",
                "active_tab_bg": "#4a4a4a",
                "active_tab_text": "#fff"
            }
        else:
            theme_colors = {
                "background": "#f5f5f5",
                "text": "#333",
                "heading": "#333",
                "section_bg": "#fff",
                "border": "#ddd",
                "stats_bg": "#f9f9f9",
                "muted_text": "#666",
                "tab_bg": "#f9f9f9",
                "tab_text": "#333",
                "active_tab_bg": "#fff",
                "active_tab_text": "#000"
            }

        # Create template and render
        template = Template(template_str)
        html = template.render(
            title=title,
            theme=theme,
            theme_colors=theme_colors,
            static_visualizations=static_visualizations,
            interactive_visualizations=interactive_visualizations,
            has_query_metrics=has_query_metrics,
            has_audit_metrics=has_audit_metrics,
            enable_realtime=enable_realtime,
            websocket_port=websocket_port,
            generation_time=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )

        return html

    def _generate_realtime_js(self):
        """Generate JavaScript for real-time dashboard updates."""
        js_content = """
// Dashboard JavaScript for real-time updates

// Create a Plotly chart for time series data
let realtimeChart = null;
let chartData = {
    'query_latency': {
        x: [],
        y: [],
        name: 'Query Latency (ms)',
        type: 'scatter',
        line: { color: '#1f77b4' }
    },
    'success_rate': {
        x: [],
        y: [],
        name: 'Success Rate (%)',
        type: 'scatter',
        line: { color: '#2ca02c' },
        yaxis: 'y2'
    }
};

// WebSocket connection
let socket = null;

// Initialize the dashboard
function initDashboard(port) {
    // Set up the real-time chart
    setupChart();

    // Connect WebSocket
    connectWebSocket(port);

    // Set up reconnection handler
    window.onbeforeunload = function() {
        if (socket) {
            socket.close();
        }
    };
}

// Set up the real-time chart
function setupChart() {
    let layout = {
        title: 'Real-Time Performance Metrics',
        xaxis: {
            title: 'Time',
            type: 'date'
        },
        yaxis: {
            title: 'Latency (ms)',
            side: 'left'
        },
        yaxis2: {
            title: 'Success Rate (%)',
            side: 'right',
            overlaying: 'y',
            range: [0, 100]
        },
        showlegend: true,
        legend: {
            x: 0,
            y: 1.1,
            orientation: 'h'
        },
        margin: {
            l: 50,
            r: 50,
            b: 50,
            t: 50,
            pad: 4
        }
    };

    // Initialize the chart with empty data
    let plotData = [chartData.query_latency, chartData.success_rate];
    Plotly.newPlot('realtime-chart', plotData, layout);
    realtimeChart = document.getElementById('realtime-chart');
}

// Connect to WebSocket server
function connectWebSocket(port) {
    const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
    const host = window.location.hostname || 'localhost';
    const wsUrl = protocol + host + ':' + port + '/dashboardws';

    socket = new WebSocket(wsUrl);

    socket.onopen = function(e) {
        console.log('WebSocket connection established');
    };

    socket.onmessage = function(event) {
        const data = JSON.parse(event.data);
        updateDashboard(data);
    };

    socket.onclose = function(event) {
        if (event.wasClean) {
            console.log(`WebSocket connection closed cleanly, code=${event.code} reason=${event.reason}`);
        } else {
            console.log('WebSocket connection died');
            // Try to reconnect after a delay
            setTimeout(function() {
                connectWebSocket(port);
            }, 5000);
        }
    };

    socket.onerror = function(error) {
        console.error(`WebSocket error: ${error.message}`);
    };
}

// Update dashboard with new data
function updateDashboard(data) {
    // Update summary statistics
    if (data.query_metrics) {
        updateQueryMetrics(data.query_metrics);
    }

    if (data.audit_metrics) {
        updateAuditMetrics(data.audit_metrics);
    }

    // Update time series chart
    updateTimeSeriesChart(data);
}

// Update query metrics
function updateQueryMetrics(metrics) {
    // Update statistics
    document.getElementById('rt-query-count').textContent = metrics.query_count || '-';
    document.getElementById('rt-avg-latency').textContent = metrics.avg_latency ?
        metrics.avg_latency.toFixed(2) : '-';
    document.getElementById('rt-success-rate').textContent = metrics.success_rate ?
        (metrics.success_rate * 100).toFixed(1) + '%' : '-';

    // Update recent queries table
    if (metrics.recent_queries && metrics.recent_queries.length > 0) {
        const tableBody = document.getElementById('recent-queries-body');
        tableBody.innerHTML = '';

        metrics.recent_queries.forEach(query => {
            const row = document.createElement('tr');
            const statusClass = query.status === 'success' ? 'success' : 'error';

            row.innerHTML = `
                <td style="padding:8px; border-bottom:1px solid #ddd;">${query.query_id}</td>
                <td style="padding:8px; border-bottom:1px solid #ddd;">${formatTimestamp(query.timestamp)}</td>
                <td style="padding:8px; border-bottom:1px solid #ddd;">${query.query_type || '-'}</td>
                <td style="padding:8px; border-bottom:1px solid #ddd;">${query.duration_ms ? query.duration_ms.toFixed(2) : '-'}</td>
                <td style="padding:8px; border-bottom:1px solid #ddd; color:${statusClass === 'success' ? 'green' : 'red'};">
                    ${query.status}
                </td>
            `;

            tableBody.appendChild(row);
        });
    }
}

// Update audit metrics
function updateAuditMetrics(metrics) {
    // Update statistics
    if (metrics.summary) {
        document.getElementById('rt-audit-count').textContent = metrics.summary.total_events || '-';
        document.getElementById('rt-error-rate').textContent = metrics.summary.error_rate ?
            (metrics.summary.error_rate * 100).toFixed(1) + '%' : '-';
    }

    // Update security alerts
    if (metrics.security && metrics.security.recent_spikes) {
        const alertsContainer = document.getElementById('security-alerts');
        if (metrics.security.recent_spikes.length === 0) {
            alertsContainer.innerHTML = '<p>No recent security alerts.</p>';
        } else {
            alertsContainer.innerHTML = '';
            const alertsList = document.createElement('ul');
            alertsList.style.listStyle = 'none';
            alertsList.style.padding = '0';

            metrics.security.recent_spikes.forEach(spike => {
                const alertItem = document.createElement('li');
                alertItem.style.padding = '10px';
                alertItem.style.margin = '5px 0';
                alertItem.style.backgroundColor = '#ffe8e8';
                alertItem.style.borderLeft = '4px solid #ff6b6b';
                alertItem.style.borderRadius = '4px';

                alertItem.innerHTML = `
                    <div style="font-weight:bold; color:#d32f2f;">Anomaly Detected: ${spike.category} / ${spike.action}</div>
                    <div>Time: ${formatTimestamp(spike.timestamp)}</div>
                    <div>Magnitude: ${spike.magnitude.toFixed(2)}x above normal</div>
                `;

                alertsList.appendChild(alertItem);
            });

            alertsContainer.appendChild(alertsList);
        }
    }
}

// Update time series chart
function updateTimeSeriesChart(data) {
    if (!realtimeChart) return;

    let updatedTime = false;

    // Update query performance data
    if (data.query_metrics && data.query_metrics.time_series) {
        const series = data.query_metrics.time_series;

        if (series.latency) {
            const timestamps = series.latency.map(point => new Date(point.timestamp * 1000));
            const values = series.latency.map(point => point.value);

            // Update chart data
            chartData.query_latency.x = timestamps;
            chartData.query_latency.y = values;
            updatedTime = true;
        }

        if (series.success_rate) {
            const timestamps = series.success_rate.map(point => new Date(point.timestamp * 1000));
            const values = series.success_rate.map(point => point.value * 100); // Convert to percentage

            // Update chart data
            chartData.success_rate.x = timestamps;
            chartData.success_rate.y = values;
            updatedTime = true;
        }
    }

    // Update the chart if data changed
    if (updatedTime) {
        Plotly.update(realtimeChart,
            [chartData.query_latency, chartData.success_rate],
            {},
            [0, 1]
        );
    }
}

// Helper to format timestamps
function formatTimestamp(timestamp) {
    if (!timestamp) return '-';

    const date = new Date(timestamp * 1000);
    return date.toLocaleString();
}
"""

        # Write to dashboard.js
        js_path = os.path.join(self.static_dir, "dashboard.js")
        os.makedirs(os.path.dirname(js_path), exist_ok=True)

        with open(js_path, "w") as f:
            f.write(js_content)


# Example usage
def run_demonstration(dashboard_dir=None, enable_realtime=True):
    """Run a demonstration of the unified dashboard."""
    if dashboard_dir is None:
        dashboard_dir = os.path.join(os.getcwd(), "dashboard")

    # Create sample metrics
    query_metrics = QueryMetricsCollector()

    # Add sample query metrics
    for i in range(50):
        query_type = random.choice(["vector", "hybrid", "graph", "keyword"])
        duration = random.uniform(50, 500)  # Random duration between 50-500ms
        status = random.choices(["success", "failure"], weights=[0.9, 0.1])[0]

        # Create query with timestamp in the past 24 hours
        timestamp = time.time() - random.uniform(0, 24 * 3600)

        # Add to metrics
        query_metrics.record_query(
            query_id=f"query_{i}",
            query_type=query_type,
            duration_ms=duration,
            result_count=random.randint(1, 20),
            status=status,
            timestamp=timestamp
        )

    # Create sample audit metrics
    if AUDIT_COMPONENTS_AVAILABLE:
        audit_metrics = AuditMetricsAggregator(
            window_size=30 * 86400,  # 30 days
            bucket_size=3600  # 1 hour buckets
        )

        # Generate sample audit events
        audit_logger = AuditLogger()
        audit_logger.add_handler(lambda event: audit_metrics.process_event(event))

        categories = [c.name for c in AuditCategory]
        levels = [l.name for l in AuditLevel]
        actions = ["login", "logout", "create", "read", "update", "delete", "query"]
        users = ["user1", "user2", "admin1", "admin2"]

        # Generate events over the past 30 days
        now = time.time()
        start_time = now - (30 * 86400)

        for i in range(500):
            # Create random timestamp
            event_time = start_time + random.random() * (now - start_time)
            event_datetime = datetime.datetime.fromtimestamp(event_time)

            # Create event
            category = random.choice(categories)
            level = random.choice(levels)
            action = random.choice(actions)
            user = random.choice(users)

            # Add some patterns for correlation analysis
            # Make some query-time errors correlated with authentication events
            if action == "query" and random.random() < 0.2:
                # Find a query within 5 minutes of this event
                query_time = event_time + random.uniform(-300, 300)
                query_id = f"query_corr_{i}"
                query_metrics.record_query(
                    query_id=query_id,
                    query_type="vector",
                    duration_ms=random.uniform(200, 1000),  # Slower than average
                    result_count=random.randint(0, 5),  # Fewer results
                    status=random.choices(["success", "failure"], weights=[0.6, 0.4])[0],
                    timestamp=query_time
                )

            # Create the event
            audit_event = AuditEvent(
                category=category,
                level=level,
                action=action,
                status=random.choices(["success", "failure"], weights=[0.9, 0.1])[0],
                user=user,
                timestamp=event_datetime.isoformat()
            )

            # Log the event
            audit_logger.log_event(audit_event)
    else:
        audit_metrics = None

    # Create dashboard
    dashboard = UnifiedDashboard(
        dashboard_dir=dashboard_dir,
        enable_realtime=enable_realtime
    )

    # Register metrics
    dashboard.register_metrics_collector(query_metrics)
    if audit_metrics:
        dashboard.register_metrics_collector(audit_metrics)

    # Generate dashboard
    dashboard_path = dashboard.generate_dashboard(
        query_metrics_collector=query_metrics,
        audit_metrics_aggregator=audit_metrics,
        title="RAG Query & Audit Dashboard Demo",
        theme="light",
        include_performance=True,
        include_security=True,
        include_interactive=True,
        include_realtime=enable_realtime
    )

    print(f"Dashboard generated at: {dashboard_path}")
    print("Open this file in a web browser to view the dashboard.")

    if enable_realtime:
        print(f"Real-time updates available at http://localhost:{dashboard.server.port}")

        # Keep server running until interrupted
        try:
            print("Press Ctrl+C to stop the server...")
            # We don't need to keep this thread running explicitly
            # since the server thread is started as a daemon
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Stopping server...")
            if dashboard.server:
                dashboard.server.stop()

    return dashboard_path


if __name__ == "__main__":
    run_demonstration()
