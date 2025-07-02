#!/usr/bin/env python3
"""
Unified Monitoring Dashboard

This module provides a comprehensive dashboard that integrates multiple monitoring
components including learning metrics visualization, alert notifications,
performance statistics, and system health indicators.
"""

import os
import json
import time
import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Union, Callable

# Import visualization and monitoring components
from ipfs_datasets_py.audit.audit_visualization import OptimizerLearningMetricsVisualizer
from ipfs_datasets_py.rag.rag_query_visualization import create_learning_metrics_visualizations
from ipfs_datasets_py.optimizers.optimizer_alert_system import LearningAlertSystem, LearningAnomaly
from ipfs_datasets_py.monitoring import MetricsCollector

# Setup logging
logger = logging.getLogger(__name__)


class UnifiedDashboard:
    """Unified dashboard that integrates multiple monitoring components.

    This class provides a comprehensive monitoring solution that combines:
    - Learning metrics visualizations
    - Alert notifications
    - Performance statistics
    - System health indicators
    """

    def __init__(
        self,
        dashboard_dir: str,
        dashboard_title: str = "RAG Optimizer Monitoring Dashboard",
        refresh_interval: int = 300,  # 5 minutes
        auto_refresh: bool = True,
        max_alerts: int = 100,
        template_dir: Optional[str] = None
    ) -> None:
        """
        Initialize the unified dashboard.

        Args:
            dashboard_dir: Directory to store dashboard files
            dashboard_title: Title for the dashboard
            refresh_interval: Interval in seconds for automatic dashboard updates
            auto_refresh: Whether to enable automatic updates
            max_alerts: Maximum number of alerts to display
            template_dir: Directory containing custom templates (optional)

        Attributes set during initialization:
            dashboard_dir (str): Directory to store dashboard files
            dashboard_title (str): Title for the dashboard
            refresh_interval (int): Interval in seconds for automatic dashboard updates
            auto_refresh (bool): Whether to enable automatic updates
            max_alerts (int): Maximum number of alerts to display
            template_dir (Optional[str]): Directory containing custom templates
            visualizations_dir (str): Directory for visualization outputs
            alerts_dir (str): Directory for alert files
            metrics_dir (str): Directory for metrics files
            assets_dir (str): Directory for dashboard assets
            last_update_time (Optional): Timestamp of last dashboard update
            dashboard_path (str): Path to the main dashboard HTML file
            alerts_json_path (str): Path to the alerts JSON file
            metrics_json_path (str): Path to the metrics JSON file
            config_json_path (str): Path to the configuration JSON file
            learning_visualizer: Reference to learning visualization component
            alert_system: Reference to alert system component
            metrics_collector: Reference to metrics collection component
            recent_alerts (list): List of recent alerts
            _stop_refresh (threading.Event): Event to control auto-refresh thread
            _refresh_thread: Thread for automatic dashboard refresh
        """
        self.dashboard_dir = dashboard_dir
        self.dashboard_title = dashboard_title
        self.refresh_interval = refresh_interval
        self.auto_refresh = auto_refresh
        self.max_alerts = max_alerts
        self.template_dir = template_dir

        # Create dashboard directory if it doesn't exist
        if not os.path.exists(self.dashboard_dir):
            os.makedirs(self.dashboard_dir, exist_ok=True)

        # Subdirectories for different component outputs
        self.visualizations_dir = os.path.join(self.dashboard_dir, "visualizations")
        self.alerts_dir = os.path.join(self.dashboard_dir, "alerts")
        self.metrics_dir = os.path.join(self.dashboard_dir, "metrics")
        self.assets_dir = os.path.join(self.dashboard_dir, "assets")

        # Create subdirectories
        for directory in [self.visualizations_dir, self.alerts_dir, self.metrics_dir, self.assets_dir]:
            if not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)

        # Dashboard state
        self.last_update_time = None
        self.dashboard_path = os.path.join(self.dashboard_dir, "index.html")
        self.alerts_json_path = os.path.join(self.alerts_dir, "alerts.json")
        self.metrics_json_path = os.path.join(self.metrics_dir, "metrics.json")
        self.config_json_path = os.path.join(self.dashboard_dir, "config.json")

        # Component references
        self.learning_visualizer = None
        self.alert_system = None
        self.metrics_collector = None

        # Alert tracking
        self.recent_alerts = []

        # Auto-refresh thread
        self._stop_refresh = threading.Event()
        self._refresh_thread = None

        # Save dashboard configuration
        self._save_config()

        # Start auto-refresh if enabled
        if self.auto_refresh:
            self.start_auto_refresh()

    def _save_config(self):
        """Save dashboard configuration to JSON file."""
        config = {
            "dashboard_title": self.dashboard_title,
            "refresh_interval": self.refresh_interval,
            "auto_refresh": self.auto_refresh,
            "max_alerts": self.max_alerts,
            "dashboard_dir": self.dashboard_dir,
            "last_update": self.last_update_time.isoformat() if self.last_update_time else None
        }

        with open(self.config_json_path, 'w') as f:
            json.dump(config, f, indent=2)

    def register_learning_visualizer(self, visualizer: OptimizerLearningMetricsVisualizer):
        """
        Register a learning metrics visualizer component.

        Args:
            visualizer: The metrics visualizer to register
        """
        self.learning_visualizer = visualizer
        logger.info("Registered learning metrics visualizer")

    def register_alert_system(self, alert_system: LearningAlertSystem):
        """
        Register an alert system component.

        Args:
            alert_system: The alert system to register
        """
        self.alert_system = alert_system

        # Register an alert handler for the dashboard
        if not hasattr(alert_system, 'alert_handlers') or alert_system.alert_handlers is None:
            alert_system.alert_handlers = []

        alert_system.alert_handlers.append(self._alert_handler)
        logger.info("Registered alert system")

    def register_metrics_collector(self, metrics_collector: MetricsCollector):
        """
        Register a metrics collector component.

        Args:
            metrics_collector: The metrics collector to register
        """
        self.metrics_collector = metrics_collector
        logger.info("Registered metrics collector")

    def _alert_handler(self, anomaly: LearningAnomaly):
        """
        Handle alerts from the alert system.

        Args:
            anomaly: The detected anomaly
        """
        # Add to recent alerts
        self.recent_alerts.append(anomaly)

        # Keep only max_alerts most recent
        if len(self.recent_alerts) > self.max_alerts:
            self.recent_alerts = self.recent_alerts[-self.max_alerts:]

        # Save alerts to JSON
        self._save_alerts()

        # Update dashboard
        self.update_dashboard()

        logger.info(f"Handled alert: {anomaly.anomaly_type} - {anomaly.description}")

    def _save_alerts(self):
        """Save recent alerts to JSON file."""
        alerts_data = []

        for anomaly in self.recent_alerts:
            try:
                alert_entry = anomaly.to_dict()
                alerts_data.append(alert_entry)
            except Exception as e:
                logger.error(f"Error serializing alert: {e}")

        with open(self.alerts_json_path, 'w') as f:
            json.dump(alerts_data, f, indent=2)

    def update_dashboard(self):
        """Update the unified dashboard with current data from all components."""
        self.last_update_time = datetime.now()

        # Update visualizations if available
        viz_outputs = {}
        if self.learning_visualizer is not None:
            try:
                # Generate visualization filenames with timestamp
                timestamp = self.last_update_time.strftime("%Y%m%d_%H%M%S")

                # Paths for static visualizations
                cycles_png = os.path.join(self.visualizations_dir, f"learning_cycles_{timestamp}.png")
                params_png = os.path.join(self.visualizations_dir, f"parameter_adaptations_{timestamp}.png")
                strategy_png = os.path.join(self.visualizations_dir, f"strategy_effectiveness_{timestamp}.png")

                # Generate visualizations
                viz_results = self.learning_visualizer.update_visualizations(create_dashboard=False)
                viz_outputs.update(viz_results)

                logger.info("Updated learning visualizations")
            except Exception as e:
                logger.error(f"Error updating learning visualizations: {e}")

        # Update metrics if available
        metrics_data = {}
        if self.metrics_collector is not None:
            try:
                # Get current metrics snapshot
                metrics_data = self.metrics_collector.get_metrics_snapshot()

                # Save metrics to JSON
                with open(self.metrics_json_path, 'w') as f:
                    json.dump(metrics_data, f, indent=2)

                logger.info("Updated metrics data")
            except Exception as e:
                logger.error(f"Error updating metrics data: {e}")

        # Generate main dashboard HTML
        try:
            self._generate_dashboard_html(viz_outputs, metrics_data)
            logger.info(f"Updated unified dashboard at {self.dashboard_path}")
        except Exception as e:
            logger.error(f"Error generating dashboard HTML: {e}")

        # Update configuration
        self._save_config()

    def _generate_dashboard_html(self, viz_outputs: Dict[str, str], metrics_data: Dict[str, Any]):
        """
        Generate the main dashboard HTML.

        Args:
            viz_outputs: Paths to visualization outputs
            metrics_data: Current metrics data
        """
        # Create dashboard HTML
        with open(self.dashboard_path, 'w') as f:
            # Basic HTML structure
            f.write(f"""
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>{self.dashboard_title}</title>
                <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
                <style>
                    body {{ padding: 20px; }}
                    .dashboard-header {{ margin-bottom: 20px; padding-bottom: 10px; border-bottom: 1px solid #eee; }}
                    .alert-panel {{ margin-bottom: 20px; }}
                    .alert-item {{ padding: 10px; margin-bottom: 10px; border-radius: 4px; }}
                    .alert-item.critical {{ background-color: #f8d7da; }}
                    .alert-item.warning {{ background-color: #fff3cd; }}
                    .alert-item.info {{ background-color: #d1ecf1; }}
                    .alert-item.minor {{ background-color: #d1e7dd; }}
                    .visualization-image {{ max-width: 100%; margin-bottom: 15px; }}
                    .metrics-panel {{ padding: 15px; background-color: #f8f9fa; border-radius: 4px; }}
                    .nav-pills .nav-link.active {{ background-color: #6c757d; }}
                    .tab-content {{ padding-top: 20px; }}
                    .refresh-info {{ font-size: 0.8rem; color: #6c757d; margin-top: 5px; }}
                </style>
            </head>
            <body>
                <div class="container-fluid">
                    <div class="dashboard-header">
                        <div class="row">
                            <div class="col-md-8">
                                <h1>{self.dashboard_title}</h1>
                                <p class="refresh-info">Last updated: {self.last_update_time.strftime('%Y-%m-%d %H:%M:%S')}</p>
                            </div>
                            <div class="col-md-4 text-end">
                                <button class="btn btn-primary" onclick="window.location.reload();">Refresh Dashboard</button>
                            </div>
                        </div>
                    </div>

                    <ul class="nav nav-pills mb-3" id="dashboard-tabs" role="tablist">
                        <li class="nav-item" role="presentation">
                            <button class="nav-link active" id="overview-tab" data-bs-toggle="pill" data-bs-target="#overview"
                                type="button" role="tab" aria-controls="overview" aria-selected="true">Overview</button>
                        </li>
                        <li class="nav-item" role="presentation">
                            <button class="nav-link" id="learning-tab" data-bs-toggle="pill" data-bs-target="#learning"
                                type="button" role="tab" aria-controls="learning" aria-selected="false">Learning Metrics</button>
                        </li>
                        <li class="nav-item" role="presentation">
                            <button class="nav-link" id="alerts-tab" data-bs-toggle="pill" data-bs-target="#alerts"
                                type="button" role="tab" aria-controls="alerts" aria-selected="false">Alerts</button>
                        </li>
                        <li class="nav-item" role="presentation">
                            <button class="nav-link" id="performance-tab" data-bs-toggle="pill" data-bs-target="#performance"
                                type="button" role="tab" aria-controls="performance" aria-selected="false">Performance</button>
                        </li>
                    </ul>

                    <div class="tab-content" id="dashboard-content">
                        <!-- Overview Tab -->
                        <div class="tab-pane fade show active" id="overview" role="tabpanel" aria-labelledby="overview-tab">
                            <div class="row">
                                <div class="col-md-4">
                                    <div class="card">
                                        <div class="card-header">
                                            <h5>System Status</h5>
                                        </div>
                                        <div class="card-body">
                                            <ul class="list-group">
            """)

            # Add system status indicators
            system_status = "Healthy"
            status_class = "text-success"

            if len(self.recent_alerts) > 0:
                critical_alerts = [a for a in self.recent_alerts if a.severity == 'critical']
                warning_alerts = [a for a in self.recent_alerts if a.severity == 'warning']

                if critical_alerts:
                    system_status = "Critical Issues"
                    status_class = "text-danger"
                elif warning_alerts:
                    system_status = "Warnings"
                    status_class = "text-warning"

            f.write(f"""
                                                <li class="list-group-item d-flex justify-content-between align-items-center">
                                                    Overall Status
                                                    <span class="{status_class} fw-bold">{system_status}</span>
                                                </li>
                                                <li class="list-group-item d-flex justify-content-between align-items-center">
                                                    Active Alerts
                                                    <span class="badge bg-secondary rounded-pill">{len(self.recent_alerts)}</span>
                                                </li>
            """)

            # Add learning status if available
            if metrics_data and 'learning_status' in metrics_data:
                learning_enabled = metrics_data.get('learning_status', {}).get('enabled', False)
                learning_status = "Enabled" if learning_enabled else "Disabled"
                learning_class = "text-success" if learning_enabled else "text-danger"

                f.write(f"""
                                                <li class="list-group-item d-flex justify-content-between align-items-center">
                                                    Learning Status
                                                    <span class="{learning_class}">{learning_status}</span>
                                                </li>
                """)

            # Add performance indicators if available
            if metrics_data and 'performance' in metrics_data:
                perf = metrics_data.get('performance', {})
                success_rate = perf.get('success_rate', 0) * 100
                latency = perf.get('avg_latency', 0)

                success_class = "text-success"
                if success_rate < 80:
                    success_class = "text-danger"
                elif success_rate < 90:
                    success_class = "text-warning"

                f.write(f"""
                                                <li class="list-group-item d-flex justify-content-between align-items-center">
                                                    Success Rate
                                                    <span class="{success_class}">{success_rate:.1f}%</span>
                                                </li>
                                                <li class="list-group-item d-flex justify-content-between align-items-center">
                                                    Avg Latency
                                                    <span>{latency:.1f} ms</span>
                                                </li>
                """)

            f.write("""
                                            </ul>
                                        </div>
                                    </div>
                                </div>

                                <div class="col-md-8">
                                    <div class="card">
                                        <div class="card-header">
                                            <h5>Recent Alerts</h5>
                                        </div>
                                        <div class="card-body">
                                            <div class="alert-panel">
            """)

            # Add recent alerts (up to 5)
            recent_alerts_to_show = sorted(
                self.recent_alerts,
                key=lambda x: x.timestamp,
                reverse=True
            )[:5]

            if recent_alerts_to_show:
                for alert in recent_alerts_to_show:
                    severity_class = {
                        'critical': 'critical',
                        'major': 'critical',
                        'warning': 'warning',
                        'moderate': 'warning',
                        'minor': 'info',
                        'info': 'info'
                    }.get(alert.severity, 'info')

                    f.write(f"""
                                                <div class="alert-item {severity_class}">
                                                    <h6>{alert.anomaly_type.replace('_', ' ').title()}</h6>
                                                    <p>{alert.description}</p>
                                                    <small>{alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</small>
                                                </div>
                    """)
            else:
                f.write("""
                                                <p class="text-muted">No recent alerts</p>
                """)

            f.write("""
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <div class="row mt-4">
                                <div class="col-12">
                                    <div class="card">
                                        <div class="card-header">
                                            <h5>Learning Metrics Summary</h5>
                                        </div>
                                        <div class="card-body">
            """)

            # Add visualization images if available
            if viz_outputs:
                # Get the most recent file of each type
                viz_files = {}
                for output_type, output_path in viz_outputs.items():
                    if os.path.exists(output_path) and output_path.endswith('.png'):
                        rel_path = os.path.relpath(output_path, self.dashboard_dir)
                        viz_files[output_type] = rel_path

                if viz_files:
                    f.write("""
                                            <div class="row">
                    """)

                    for viz_type, viz_file in viz_files.items():
                        viz_title = viz_type.replace('_', ' ').title()
                        f.write(f"""
                                                <div class="col-md-4 text-center">
                                                    <h6>{viz_title}</h6>
                                                    <img src="{viz_file}" class="visualization-image" alt="{viz_title}">
                                                </div>
                        """)

                    f.write("""
                                            </div>
                    """)
                else:
                    f.write("""
                                            <p class="text-muted">No visualization data available</p>
                    """)
            else:
                f.write("""
                                            <p class="text-muted">No visualization data available</p>
                """)

            f.write("""
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Learning Metrics Tab -->
                        <div class="tab-pane fade" id="learning" role="tabpanel" aria-labelledby="learning-tab">
                            <div class="row">
                                <div class="col-12">
                                    <div class="card">
                                        <div class="card-header">
                                            <h5>Learning Metrics Details</h5>
                                        </div>
                                        <div class="card-body">
            """)

            # Add learning metrics details if available
            if metrics_data and 'learning_metrics' in metrics_data:
                learning_metrics = metrics_data.get('learning_metrics', {})

                # Learning cycles stats
                cycles = learning_metrics.get('learning_cycles', {})
                total_cycles = cycles.get('total_cycles', 0)
                analyzed_queries = cycles.get('total_analyzed_queries', 0)
                patterns_identified = cycles.get('total_patterns', 0)
                parameters_adjusted = cycles.get('total_adjustments', 0)

                # Parameter adaptations
                adaptations = learning_metrics.get('parameter_adaptations', {})

                # Strategy effectiveness
                strategies = learning_metrics.get('strategy_effectiveness', {})

                f.write(f"""
                                            <div class="row mb-4">
                                                <div class="col-md-6">
                                                    <h6>Learning Cycles</h6>
                                                    <table class="table table-sm">
                                                        <tr>
                                                            <td>Total Cycles</td>
                                                            <td>{total_cycles}</td>
                                                        </tr>
                                                        <tr>
                                                            <td>Analyzed Queries</td>
                                                            <td>{analyzed_queries}</td>
                                                        </tr>
                                                        <tr>
                                                            <td>Patterns Identified</td>
                                                            <td>{patterns_identified}</td>
                                                        </tr>
                                                        <tr>
                                                            <td>Parameters Adjusted</td>
                                                            <td>{parameters_adjusted}</td>
                                                        </tr>
                                                    </table>
                                                </div>
                """)

                if adaptations:
                    f.write(f"""
                                                <div class="col-md-6">
                                                    <h6>Recent Parameter Adaptations</h6>
                                                    <table class="table table-sm">
                                                        <thead>
                                                            <tr>
                                                                <th>Parameter</th>
                                                                <th>Old Value</th>
                                                                <th>New Value</th>
                                                            </tr>
                                                        </thead>
                                                        <tbody>
                    """)

                    # Add up to 5 most recent parameter adaptations
                    for param_name, param_data in list(adaptations.items())[:5]:
                        old_value = param_data.get('old_value', 'N/A')
                        new_value = param_data.get('new_value', 'N/A')
                        f.write(f"""
                                                            <tr>
                                                                <td>{param_name}</td>
                                                                <td>{old_value}</td>
                                                                <td>{new_value}</td>
                                                            </tr>
                        """)

                    f.write("""
                                                        </tbody>
                                                    </table>
                                                </div>
                    """)

                f.write("""
                                            </div>
                """)

                # Add strategy effectiveness if available
                if strategies:
                    f.write("""
                                            <div class="row">
                                                <div class="col-12">
                                                    <h6>Strategy Effectiveness</h6>
                                                    <table class="table">
                                                        <thead>
                                                            <tr>
                                                                <th>Strategy</th>
                                                                <th>Query Type</th>
                                                                <th>Success Rate</th>
                                                                <th>Avg Latency</th>
                                                            </tr>
                                                        </thead>
                                                        <tbody>
                    """)

                    for strategy_name, strategy_data in strategies.items():
                        for query_type, type_data in strategy_data.items():
                            success_rate = type_data.get('success_rate', 0) * 100
                            latency = type_data.get('mean_latency', 0)

                            success_class = ""
                            if success_rate < 70:
                                success_class = "text-danger"
                            elif success_rate < 85:
                                success_class = "text-warning"
                            else:
                                success_class = "text-success"

                            f.write(f"""
                                                            <tr>
                                                                <td>{strategy_name}</td>
                                                                <td>{query_type}</td>
                                                                <td class="{success_class}">{success_rate:.1f}%</td>
                                                                <td>{latency:.1f} ms</td>
                                                            </tr>
                            """)

                    f.write("""
                                                        </tbody>
                                                    </table>
                                                </div>
                                            </div>
                    """)
            else:
                f.write("""
                                            <p class="text-muted">No learning metrics data available</p>
                """)

            f.write("""
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Alerts Tab -->
                        <div class="tab-pane fade" id="alerts" role="tabpanel" aria-labelledby="alerts-tab">
                            <div class="row">
                                <div class="col-12">
                                    <div class="card">
                                        <div class="card-header">
                                            <div class="d-flex justify-content-between align-items-center">
                                                <h5>Alert History</h5>
                                                <div>
                                                    <select class="form-select form-select-sm" id="alertSeverityFilter">
                                                        <option value="all">All Severities</option>
                                                        <option value="critical">Critical</option>
                                                        <option value="warning">Warning</option>
                                                        <option value="info">Info</option>
                                                    </select>
                                                </div>
                                            </div>
                                        </div>
                                        <div class="card-body">
                                            <div class="alert-panel">
            """)

            # Add all alerts
            if self.recent_alerts:
                for alert in sorted(self.recent_alerts, key=lambda x: x.timestamp, reverse=True):
                    severity_class = {
                        'critical': 'critical',
                        'major': 'critical',
                        'warning': 'warning',
                        'moderate': 'warning',
                        'minor': 'info',
                        'info': 'info'
                    }.get(alert.severity, 'info')

                    # Add data attributes for filtering
                    f.write(f"""
                                                <div class="alert-item {severity_class}" data-severity="{alert.severity}">
                                                    <div class="d-flex justify-content-between">
                                                        <h6>{alert.anomaly_type.replace('_', ' ').title()}</h6>
                                                        <span class="badge bg-secondary">{alert.severity.upper()}</span>
                                                    </div>
                                                    <p>{alert.description}</p>
                    """)

                    # Add any additional metadata
                    if hasattr(alert, 'affected_parameters') and alert.affected_parameters:
                        affected = ', '.join(alert.affected_parameters)
                        f.write(f"""
                                                    <p><small>Affected: {affected}</small></p>
                        """)

                    f.write(f"""
                                                    <small>{alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</small>
                                                </div>
                    """)
            else:
                f.write("""
                                                <p class="text-muted">No alerts recorded</p>
                """)

            f.write("""
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Performance Tab -->
                        <div class="tab-pane fade" id="performance" role="tabpanel" aria-labelledby="performance-tab">
                            <div class="row">
                                <div class="col-12">
                                    <div class="card">
                                        <div class="card-header">
                                            <h5>Performance Metrics</h5>
                                        </div>
                                        <div class="card-body">
            """)

            # Add performance metrics if available
            if metrics_data and 'performance' in metrics_data:
                perf = metrics_data.get('performance', {})

                # Key metrics
                total_queries = perf.get('total_queries', 0)
                success_rate = perf.get('success_rate', 0) * 100
                avg_latency = perf.get('avg_latency', 0)
                p95_latency = perf.get('p95_latency', 0)
                p99_latency = perf.get('p99_latency', 0)

                # Resource usage
                resources = metrics_data.get('resources', {})
                cpu_usage = resources.get('cpu_usage', 0)
                memory_usage = resources.get('memory_usage', 0)

                f.write(f"""
                                            <div class="row">
                                                <div class="col-md-6">
                                                    <h6>Query Metrics</h6>
                                                    <table class="table table-sm">
                                                        <tr>
                                                            <td>Total Queries</td>
                                                            <td>{total_queries}</td>
                                                        </tr>
                                                        <tr>
                                                            <td>Success Rate</td>
                                                            <td>{success_rate:.1f}%</td>
                                                        </tr>
                                                        <tr>
                                                            <td>Average Latency</td>
                                                            <td>{avg_latency:.1f} ms</td>
                                                        </tr>
                                                        <tr>
                                                            <td>95th Percentile Latency</td>
                                                            <td>{p95_latency:.1f} ms</td>
                                                        </tr>
                                                        <tr>
                                                            <td>99th Percentile Latency</td>
                                                            <td>{p99_latency:.1f} ms</td>
                                                        </tr>
                                                    </table>
                                                </div>
                                                <div class="col-md-6">
                                                    <h6>Resource Usage</h6>
                                                    <table class="table table-sm">
                                                        <tr>
                                                            <td>CPU Usage</td>
                                                            <td>{cpu_usage:.1f}%</td>
                                                        </tr>
                                                        <tr>
                                                            <td>Memory Usage</td>
                                                            <td>{memory_usage:.1f} MB</td>
                                                        </tr>
                                                    </table>
                                                </div>
                                            </div>
                """)

                # Add query type breakdown if available
                if 'query_types' in perf:
                    query_types = perf.get('query_types', {})

                    f.write("""
                                            <div class="row mt-4">
                                                <div class="col-12">
                                                    <h6>Query Type Breakdown</h6>
                                                    <table class="table">
                                                        <thead>
                                                            <tr>
                                                                <th>Query Type</th>
                                                                <th>Count</th>
                                                                <th>Success Rate</th>
                                                                <th>Avg Latency</th>
                                                            </tr>
                                                        </thead>
                                                        <tbody>
                    """)

                    for query_type, type_data in query_types.items():
                        count = type_data.get('count', 0)
                        success = type_data.get('success_rate', 0) * 100
                        latency = type_data.get('avg_latency', 0)

                        success_class = ""
                        if success < 70:
                            success_class = "text-danger"
                        elif success < 85:
                            success_class = "text-warning"
                        else:
                            success_class = "text-success"

                        f.write(f"""
                                                            <tr>
                                                                <td>{query_type}</td>
                                                                <td>{count}</td>
                                                                <td class="{success_class}">{success:.1f}%</td>
                                                                <td>{latency:.1f} ms</td>
                                                            </tr>
                        """)

                    f.write("""
                                                        </tbody>
                                                    </table>
                                                </div>
                                            </div>
                    """)
            else:
                f.write("""
                                            <p class="text-muted">No performance metrics available</p>
                """)

            f.write("""
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/js/bootstrap.bundle.min.js"></script>
                <script>
                    // Filter alerts by severity
                    document.getElementById('alertSeverityFilter').addEventListener('change', function() {
                        const severity = this.value;
                        const alerts = document.querySelectorAll('#alerts .alert-item');

                        alerts.forEach(alert => {
                            if (severity === 'all' || alert.getAttribute('data-severity') === severity) {
                                alert.style.display = 'block';
                            } else {
                                alert.style.display = 'none';
                            }
                        });
                    });

                    // Auto-refresh handling
                    const autoRefresh = """ + str(self.auto_refresh).lower() + """;
                    const refreshInterval = """ + str(self.refresh_interval * 1000) + """;

                    if (autoRefresh) {
                        setTimeout(() => {
                            window.location.reload();
                        }, refreshInterval);
                    }
                </script>
            </body>
            </html>
            """)

    def start_auto_refresh(self):
        """Start automatic dashboard refreshing."""
        if self._refresh_thread is not None and self._refresh_thread.is_alive():
            logger.warning("Auto-refresh thread is already running")
            return

        self._stop_refresh.clear()
        self._refresh_thread = threading.Thread(
            target=self._auto_refresh_loop,
            daemon=True
        )
        self._refresh_thread.start()
        logger.info(f"Started auto-refresh with interval {self.refresh_interval} seconds")

    def stop_auto_refresh(self):
        """Stop automatic dashboard refreshing."""
        if self._refresh_thread is None or not self._refresh_thread.is_alive():
            logger.warning("Auto-refresh thread is not running")
            return

        self._stop_refresh.set()
        self._refresh_thread.join(timeout=5.0)
        logger.info("Stopped auto-refresh")

    def _auto_refresh_loop(self):
        """Background thread for automatic dashboard refreshing."""
        while not self._stop_refresh.is_set():
            # Wait for refresh interval
            for _ in range(min(self.refresh_interval, 60)):  # Check at most every second
                if self._stop_refresh.is_set():
                    return
                time.sleep(1)

            # Update dashboard
            try:
                logger.info("Auto-refreshing dashboard")
                self.update_dashboard()
            except Exception as e:
                logger.error(f"Error during auto-refresh: {e}")


# Helper function to create and set up a unified dashboard
def create_unified_dashboard(
    dashboard_dir: str,
    dashboard_title: str = "RAG Optimizer Monitoring Dashboard",
    refresh_interval: int = 300,
    auto_refresh: bool = True,
    max_alerts: int = 100,
    template_dir: Optional[str] = None
) -> UnifiedDashboard:
    """
    Create and set up a unified monitoring dashboard.

    Args:
        dashboard_dir: Directory to store dashboard files
        dashboard_title: Title for the dashboard
        refresh_interval: Interval in seconds for automatic dashboard updates
        auto_refresh: Whether to enable automatic updates
        max_alerts: Maximum number of alerts to display
        template_dir: Directory containing custom templates (optional)

    Returns:
        UnifiedDashboard: Configured dashboard instance
    """
    dashboard = UnifiedDashboard(
        dashboard_dir=dashboard_dir,
        dashboard_title=dashboard_title,
        refresh_interval=refresh_interval,
        auto_refresh=auto_refresh,
        max_alerts=max_alerts,
        template_dir=template_dir
    )

    # Initial dashboard update
    dashboard.update_dashboard()

    return dashboard


if __name__ == "__main__":
    # Simple demonstration
    import sys

    # Create dashboard directory
    dashboard_dir = "./unified_dashboard"
    os.makedirs(dashboard_dir, exist_ok=True)

    # Create unified dashboard
    dashboard = create_unified_dashboard(
        dashboard_dir=dashboard_dir,
        dashboard_title="RAG Optimizer Monitoring Demo",
        refresh_interval=30,  # 30 seconds for demo
        auto_refresh=True
    )

    # Add sample alerts
    for i in range(3):
        severity = ["info", "warning", "critical"][i % 3]
        anomaly = LearningAnomaly(
            anomaly_type=["parameter_oscillation", "performance_decline", "learning_stall"][i % 3],
            severity=severity,
            description=f"Sample alert {i+1} for demonstration purposes",
            affected_parameters=["param1", "param2"] if i % 2 == 0 else [],
            timestamp=datetime.now() - timedelta(minutes=i*10)
        )
        dashboard._alert_handler(anomaly)

    print(f"Demo dashboard created at: {os.path.join(dashboard_dir, 'index.html')}")
    print("Press Ctrl+C to stop auto-refresh")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        dashboard.stop_auto_refresh()
        print("Demo stopped")
