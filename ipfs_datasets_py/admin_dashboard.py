"""
Administration Dashboard for IPFS Datasets.

This module provides a web-based dashboard for monitoring, visualizing,
and managing IPFS Datasets Python operations, including:
- Real-time metrics visualization
- Log viewing and filtering
- System status monitoring
- Node management
- Operation tracking
- Configuration management

The dashboard uses Flask for the backend web server and Chart.js for visualization.
"""
import logging
import os
import platform
import socket
import threading
import time
import webbrowser
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, Callable


# Web server
try:
    from flask import (
        Flask, render_template, jsonify, request, Response,
        send_from_directory, redirect, url_for
    )
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

# Import monitoring system
from ipfs_datasets_py.monitoring import (
    MonitoringSystem, get_logger, get_metrics_registry,
    MonitoringConfig, LoggerConfig, MetricsConfig, LogLevel
)

# Optional imports for extra functionality
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


# Constants
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8888
DEFAULT_REFRESH_INTERVAL = 5  # seconds
DEFAULT_LOG_LINES = 100
DEFAULT_DATA_DIR = os.path.expanduser("~/.ipfs_datasets/admin")
DEFAULT_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static", "admin")
DEFAULT_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates", "admin")
DEFAULT_CONFIG_FILE = os.path.join(DEFAULT_DATA_DIR, "dashboard_config.json")


@dataclass
class DashboardConfig:
    """Configuration for the admin dashboard.

    Attributes:
        enabled (bool): Whether the dashboard is enabled. Defaults to True.
        host (str): The host address to bind the dashboard server to. Defaults to DEFAULT_HOST.
        port (int): The port number to bind the dashboard server to. Defaults to DEFAULT_PORT.
        refresh_interval (int): The interval in seconds for dashboard auto-refresh. Defaults to DEFAULT_REFRESH_INTERVAL.
        open_browser (bool): Whether to automatically open the browser when starting the dashboard. Defaults to True.
        data_dir (str): The directory path for storing dashboard data. Defaults to DEFAULT_DATA_DIR.
        max_log_lines (int): Maximum number of log lines to display in the dashboard. Defaults to DEFAULT_LOG_LINES.
        require_auth (bool): Whether authentication is required to access the dashboard. Defaults to False.
        username (Optional[str]): Username for dashboard authentication. Defaults to None.
        password (Optional[str]): Password for dashboard authentication. Defaults to None.
        monitoring_config (Optional[MonitoringConfig]): Configuration for monitoring features. Defaults to None.
    """
    enabled: bool = True
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    refresh_interval: int = DEFAULT_REFRESH_INTERVAL
    open_browser: bool = True
    data_dir: str = DEFAULT_DATA_DIR
    max_log_lines: int = DEFAULT_LOG_LINES
    require_auth: bool = False
    username: Optional[str] = None
    password: Optional[str] = None
    monitoring_config: Optional[MonitoringConfig] = None


class AdminDashboard:
    """Administration dashboard for IPFS Datasets."""

    _instance = None

    @classmethod
    def get_instance(cls) -> 'AdminDashboard':
        """Get the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def initialize(cls, config: Optional[DashboardConfig] = None) -> 'AdminDashboard':
        """Initialize the admin dashboard.

        Args:
            config: Configuration for the dashboard

        Returns:
            AdminDashboard: The initialized dashboard
        """
        instance = cls.get_instance()
        instance.configure(config or DashboardConfig())
        return instance

    def __init__(self):
        """Initialize the admin dashboard."""
        self.config = DashboardConfig()
        self.logger = logging.getLogger(__name__)
        self.app = None
        self.server_thread = None
        self.running = False
        self.initialized = False
        self.start_time = time.time()

        # Node information
        self.node_info = {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "start_time": datetime.now().isoformat(),
            "ipfs_datasets_version": "0.1.0"  # TODO: Get actual version
        }

        # Initialize data directory
        if not os.path.exists(DEFAULT_DATA_DIR):
            os.makedirs(DEFAULT_DATA_DIR, exist_ok=True)

    def configure(self, config: DashboardConfig) -> None:
        """Configure the admin dashboard.

        Args:
            config: Configuration for the dashboard
        """
        self.config = config

        # Initialize monitoring if needed
        if config.monitoring_config is not None:
            MonitoringSystem.initialize(config.monitoring_config)

        # Set up logger
        self.logger = get_logger("admin_dashboard")

        # Create data directory if needed
        if not os.path.exists(config.data_dir):
            os.makedirs(config.data_dir, exist_ok=True)

        # Initialize Flask app if available
        if FLASK_AVAILABLE:
            self._initialize_flask_app()

        self.initialized = True
        self.logger.info(f"Admin dashboard initialized (port {config.port})")

    def _initialize_flask_app(self) -> None:
        """Initialize the Flask web application."""
        # Create templates directory if needed
        if not os.path.exists(DEFAULT_TEMPLATES_DIR):
            os.makedirs(DEFAULT_TEMPLATES_DIR, exist_ok=True)
            self._create_default_templates()

        # Create static directory if needed
        if not os.path.exists(DEFAULT_STATIC_DIR):
            os.makedirs(DEFAULT_STATIC_DIR, exist_ok=True)
            self._create_default_static_files()

        # Initialize Flask app
        self.app = Flask(
            __name__,
            template_folder=DEFAULT_TEMPLATES_DIR,
            static_folder=DEFAULT_STATIC_DIR
        )

        # Set up routes
        self._setup_routes()
        
        # Register patent dashboard routes
        try:
            from ipfs_datasets_py.patent_dashboard import register_patent_routes
            register_patent_routes(self.app)
        except Exception as e:
            self.logger.warning(f"Could not register patent dashboard routes: {e}")

    def _create_default_templates(self) -> None:
        """Create default template files if they don't exist."""
        templates = {
            "index.html": """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IPFS Datasets Admin Dashboard</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/bootstrap.min.css') }}">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/dashboard.css') }}">
    <meta http-equiv="refresh" content="{{ refresh_interval }}">
</head>
<body>
    <nav class="navbar navbar-dark fixed-top bg-dark flex-md-nowrap p-0 shadow">
        <a class="navbar-brand col-sm-3 col-md-2 mr-0" href="#">IPFS Datasets Admin</a>
        <ul class="navbar-nav px-3">
            <li class="nav-item text-nowrap">
                <span class="nav-link">{{ node_info.hostname }}</span>
            </li>
        </ul>
    </nav>

    <div class="container-fluid">
        <div class="row">
            <nav class="col-md-2 d-none d-md-block bg-light sidebar">
                <div class="sidebar-sticky">
                    <ul class="nav flex-column">
                        <li class="nav-item">
                            <a class="nav-link active" href="#overview">
                                Overview
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="#metrics">
                                Metrics
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="#logs">
                                Logs
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="#nodes">
                                Nodes
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="#operations">
                                Operations
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="#config">
                                Configuration
                            </a>
                        </li>
                    </ul>
                </div>
            </nav>

            <main role="main" class="col-md-9 ml-sm-auto col-lg-10 px-4">
                <div class="d-flex justify-content-between flex-wrap flex-md-nowrap align-items-center pt-3 pb-2 mb-3 border-bottom">
                    <h1 class="h2">Dashboard Overview</h1>
                    <div class="btn-toolbar mb-2 mb-md-0">
                        <div class="btn-group mr-2">
                            <button type="button" class="btn btn-sm btn-outline-secondary" onclick="window.location.reload()">Refresh</button>
                        </div>
                        <div class="btn-group mr-2">
                            <span class="text-muted">Last updated: {{ last_updated }}</span>
                        </div>
                    </div>
                </div>

                <section id="overview">
                    <h2>System Status</h2>
                    <div class="row">
                        <div class="col-md-4">
                            <div class="card">
                                <div class="card-body">
                                    <h5 class="card-title">System</h5>
                                    <p class="card-text">
                                        <strong>Hostname:</strong> {{ node_info.hostname }}<br>
                                        <strong>Platform:</strong> {{ node_info.platform }}<br>
                                        <strong>Python:</strong> {{ node_info.python_version }}<br>
                                        <strong>Uptime:</strong> {{ uptime }}
                                    </p>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-4">
                            <div class="card">
                                <div class="card-body">
                                    <h5 class="card-title">Resource Usage</h5>
                                    <p class="card-text">
                                        <strong>CPU:</strong> {{ system_stats.cpu_percent }}%<br>
                                        <strong>Memory:</strong> {{ system_stats.memory_used }} / {{ system_stats.memory_total }} ({{ system_stats.memory_percent }}%)<br>
                                        <strong>Disk:</strong> {{ system_stats.disk_used }} / {{ system_stats.disk_total }} ({{ system_stats.disk_percent }}%)
                                    </p>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-4">
                            <div class="card">
                                <div class="card-body">
                                    <h5 class="card-title">Application</h5>
                                    <p class="card-text">
                                        <strong>Version:</strong> {{ node_info.ipfs_datasets_version }}<br>
                                        <strong>Started:</strong> {{ node_info.start_time }}<br>
                                        <strong>Status:</strong> <span class="badge badge-success">Running</span>
                                    </p>
                                </div>
                            </div>
                        </div>
                    </div>
                </section>

                <section id="metrics" class="mt-4">
                    <h2>Metrics</h2>
                    <div class="row">
                        <div class="col-md-6">
                            <div class="card">
                                <div class="card-body">
                                    <h5 class="card-title">CPU Usage</h5>
                                    <canvas id="cpuChart" width="400" height="200"></canvas>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-6">
                            <div class="card">
                                <div class="card-body">
                                    <h5 class="card-title">Memory Usage</h5>
                                    <canvas id="memoryChart" width="400" height="200"></canvas>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="row mt-3">
                        <div class="col-md-12">
                            <div class="card">
                                <div class="card-body">
                                    <h5 class="card-title">Custom Metrics</h5>
                                    <table class="table table-striped">
                                        <thead>
                                            <tr>
                                                <th>Metric</th>
                                                <th>Type</th>
                                                <th>Value</th>
                                                <th>Labels</th>
                                                <th>Last Updated</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {% for metric_name, metric_instances in metrics.items() %}
                                                {% for metric in metric_instances %}
                                                <tr>
                                                    <td>{{ metric_name }}</td>
                                                    <td>{{ metric.type }}</td>
                                                    <td>{{ metric.value }}</td>
                                                    <td>{{ metric.labels }}</td>
                                                    <td>{{ metric.timestamp }}</td>
                                                </tr>
                                                {% endfor %}
                                            {% endfor %}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </div>
                    </div>
                </section>

                <section id="logs" class="mt-4">
                    <h2>Logs</h2>
                    <div class="card">
                        <div class="card-body">
                            <div class="form-group">
                                <label for="logFilter">Filter logs:</label>
                                <input type="text" class="form-control" id="logFilter" placeholder="Type to filter logs">
                            </div>
                            <div class="log-container">
                                {% for log in logs %}
                                <div class="log-entry log-{{ log.level|lower }}">
                                    <span class="log-timestamp">{{ log.timestamp }}</span>
                                    <span class="log-level log-level-{{ log.level|lower }}">{{ log.level }}</span>
                                    <span class="log-name">{{ log.name }}</span>
                                    <span class="log-message">{{ log.message }}</span>
                                </div>
                                {% endfor %}
                            </div>
                        </div>
                    </div>
                </section>

                <section id="nodes" class="mt-4">
                    <h2>Connected Nodes</h2>
                    <div class="card">
                        <div class="card-body">
                            <table class="table table-striped">
                                <thead>
                                    <tr>
                                        <th>Node ID</th>
                                        <th>Status</th>
                                        <th>Address</th>
                                        <th>Last Seen</th>
                                        <th>Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {% for node in nodes %}
                                    <tr>
                                        <td>{{ node.id }}</td>
                                        <td>
                                            {% if node.status == 'online' %}
                                            <span class="badge badge-success">Online</span>
                                            {% else %}
                                            <span class="badge badge-danger">Offline</span>
                                            {% endif %}
                                        </td>
                                        <td>{{ node.address }}</td>
                                        <td>{{ node.last_seen }}</td>
                                        <td>
                                            <button class="btn btn-sm btn-primary">Details</button>
                                        </td>
                                    </tr>
                                    {% endfor %}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </section>

                <section id="operations" class="mt-4">
                    <h2>Active Operations</h2>
                    <div class="card">
                        <div class="card-body">
                            <table class="table table-striped">
                                <thead>
                                    <tr>
                                        <th>Operation ID</th>
                                        <th>Type</th>
                                        <th>Status</th>
                                        <th>Start Time</th>
                                        <th>Duration</th>
                                        <th>Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {% for op in operations %}
                                    <tr>
                                        <td>{{ op.operation_id }}</td>
                                        <td>{{ op.operation_type }}</td>
                                        <td>
                                            {% if op.status == 'success' %}
                                            <span class="badge badge-success">Success</span>
                                            {% elif op.status == 'error' %}
                                            <span class="badge badge-danger">Error</span>
                                            {% else %}
                                            <span class="badge badge-warning">{{ op.status }}</span>
                                            {% endif %}
                                        </td>
                                        <td>{{ op.start_time }}</td>
                                        <td>{{ op.duration_ms|round(2) if op.duration_ms else 'N/A' }} ms</td>
                                        <td>
                                            <button class="btn btn-sm btn-primary">Details</button>
                                        </td>
                                    </tr>
                                    {% endfor %}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </section>

                <section id="config" class="mt-4">
                    <h2>Configuration</h2>
                    <div class="card">
                        <div class="card-body">
                            <div class="accordion" id="configAccordion">
                                <div class="card">
                                    <div class="card-header" id="headingDashboard">
                                        <h2 class="mb-0">
                                            <button class="btn btn-link" type="button" data-toggle="collapse" data-target="#collapseDashboard">
                                                Dashboard Configuration
                                            </button>
                                        </h2>
                                    </div>
                                    <div id="collapseDashboard" class="collapse show" aria-labelledby="headingDashboard" data-parent="#configAccordion">
                                        <div class="card-body">
                                            <pre>{{ dashboard_config|tojson(indent=4) }}</pre>
                                        </div>
                                    </div>
                                </div>
                                <div class="card">
                                    <div class="card-header" id="headingMonitoring">
                                        <h2 class="mb-0">
                                            <button class="btn btn-link collapsed" type="button" data-toggle="collapse" data-target="#collapseMonitoring">
                                                Monitoring Configuration
                                            </button>
                                        </h2>
                                    </div>
                                    <div id="collapseMonitoring" class="collapse" aria-labelledby="headingMonitoring" data-parent="#configAccordion">
                                        <div class="card-body">
                                            <pre>{{ monitoring_config|tojson(indent=4) }}</pre>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </section>
            </main>
        </div>
    </div>

    <script src="{{ url_for('static', filename='js/jquery.min.js') }}"></script>
    <script src="{{ url_for('static', filename='js/bootstrap.bundle.min.js') }}"></script>
    <script src="{{ url_for('static', filename='js/chart.min.js') }}"></script>
    <script src="{{ url_for('static', filename='js/dashboard.js') }}"></script>
</body>
</html>""",

            "login.html": """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IPFS Datasets Admin - Login</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/bootstrap.min.css') }}">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/login.css') }}">
</head>
<body class="text-center">
    <form class="form-signin" method="post" action="{{ url_for('login') }}">
        <h1 class="h3 mb-3 font-weight-normal">IPFS Datasets Admin</h1>
        <h2 class="h5 mb-3 font-weight-normal">Please sign in</h2>

        {% if error %}
        <div class="alert alert-danger">{{ error }}</div>
        {% endif %}

        <label for="username" class="sr-only">Username</label>
        <input type="text" id="username" name="username" class="form-control" placeholder="Username" required autofocus>

        <label for="password" class="sr-only">Password</label>
        <input type="password" id="password" name="password" class="form-control" placeholder="Password" required>

        <button class="btn btn-lg btn-primary btn-block" type="submit">Sign in</button>
        <p class="mt-5 mb-3 text-muted">&copy; 2023 IPFS Datasets</p>
    </form>

    <script src="{{ url_for('static', filename='js/jquery.min.js') }}"></script>
    <script src="{{ url_for('static', filename='js/bootstrap.bundle.min.js') }}"></script>
</body>
</html>""",

            "error.html": """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Error - IPFS Datasets Admin</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/bootstrap.min.css') }}">
</head>
<body class="text-center">
    <div class="container mt-5">
        <div class="row">
            <div class="col-md-8 offset-md-2">
                <div class="card">
                    <div class="card-header bg-danger text-white">
                        <h2>{{ error_title }}</h2>
                    </div>
                    <div class="card-body">
                        <p>{{ error_message }}</p>
                        <hr>
                        <div class="text-center">
                            <a href="{{ url_for('index') }}" class="btn btn-primary">Return to Dashboard</a>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</body>
</html>"""
        }

        # Write template files
        for filename, content in templates.items():
            file_path = os.path.join(DEFAULT_TEMPLATES_DIR, filename)
            with open(file_path, 'w') as f:
                f.write(content)

    def _create_default_static_files(self) -> None:
        """Create default static files if they don't exist."""
        # Create subdirectories
        os.makedirs(os.path.join(DEFAULT_STATIC_DIR, "css"), exist_ok=True)
        os.makedirs(os.path.join(DEFAULT_STATIC_DIR, "js"), exist_ok=True)

        # CSS files
        css_files = {
            "css/dashboard.css": """/* Dashboard styles */
body {
    font-size: .875rem;
}

.feather {
    width: 16px;
    height: 16px;
    vertical-align: text-bottom;
}

/* Sidebar */
.sidebar {
    position: fixed;
    top: 0;
    bottom: 0;
    left: 0;
    z-index: 100;
    padding: 48px 0 0;
    box-shadow: inset -1px 0 0 rgba(0, 0, 0, .1);
}

.sidebar-sticky {
    position: relative;
    top: 0;
    height: calc(100vh - 48px);
    padding-top: .5rem;
    overflow-x: hidden;
    overflow-y: auto;
}

.sidebar .nav-link {
    font-weight: 500;
    color: #333;
}

.sidebar .nav-link.active {
    color: #007bff;
}

/* Content */
[role="main"] {
    padding-top: 48px;
}

/* Log styles */
.log-container {
    background-color: #f8f9fa;
    border: 1px solid #ddd;
    border-radius: 3px;
    height: 400px;
    overflow-y: auto;
    font-family: monospace;
    font-size: 12px;
    padding: 10px;
}

.log-entry {
    margin-bottom: 5px;
    padding: 3px 0;
    border-bottom: 1px solid #eee;
}

.log-timestamp {
    color: #6c757d;
    margin-right: 10px;
}

.log-level {
    display: inline-block;
    min-width: 60px;
    text-align: center;
    margin-right: 10px;
    padding: 0 5px;
    border-radius: 3px;
}

.log-level-debug {
    background-color: #d1ecf1;
    color: #0c5460;
}

.log-level-info {
    background-color: #d4edda;
    color: #155724;
}

.log-level-warning {
    background-color: #fff3cd;
    color: #856404;
}

.log-level-error, .log-level-critical {
    background-color: #f8d7da;
    color: #721c24;
}

.log-name {
    color: #007bff;
    margin-right: 10px;
}

.log-message {
    color: #333;
}

/* Card */
.card {
    margin-bottom: 15px;
}""",

            "css/login.css": """html,
body {
    height: 100%;
}

body {
    display: -ms-flexbox;
    display: flex;
    -ms-flex-align: center;
    align-items: center;
    padding-top: 40px;
    padding-bottom: 40px;
    background-color: #f5f5f5;
}

.form-signin {
    width: 100%;
    max-width: 330px;
    padding: 15px;
    margin: auto;
}

.form-signin .checkbox {
    font-weight: 400;
}

.form-signin .form-control {
    position: relative;
    box-sizing: border-box;
    height: auto;
    padding: 10px;
    font-size: 16px;
}

.form-signin .form-control:focus {
    z-index: 2;
}

.form-signin input[type="text"] {
    margin-bottom: -1px;
    border-bottom-right-radius: 0;
    border-bottom-left-radius: 0;
}

.form-signin input[type="password"] {
    margin-bottom: 10px;
    border-top-left-radius: 0;
    border-top-right-radius: 0;
}"""
        }

        # JavaScript files
        js_files = {
            "js/dashboard.js": """// Dashboard JavaScript
document.addEventListener('DOMContentLoaded', function() {
    // Initialize charts
    initCharts();

    // Set up log filtering
    setupLogFilter();

    // Set up page navigation
    setupNavigation();
});

function initCharts() {
    // CPU chart
    const cpuCtx = document.getElementById('cpuChart').getContext('2d');
    const cpuChart = new Chart(cpuCtx, {
        type: 'line',
        data: {
            labels: Array.from({length: 10}, (_, i) => i),
            datasets: [{
                label: 'CPU Usage (%)',
                data: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                backgroundColor: 'rgba(75, 192, 192, 0.2)',
                borderColor: 'rgba(75, 192, 192, 1)',
                borderWidth: 1
            }]
        },
        options: {
            scales: {
                y: {
                    beginAtZero: true,
                    max: 100
                }
            }
        }
    });

    // Memory chart
    const memoryCtx = document.getElementById('memoryChart').getContext('2d');
    const memoryChart = new Chart(memoryCtx, {
        type: 'line',
        data: {
            labels: Array.from({length: 10}, (_, i) => i),
            datasets: [{
                label: 'Memory Usage (%)',
                data: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                backgroundColor: 'rgba(153, 102, 255, 0.2)',
                borderColor: 'rgba(153, 102, 255, 1)',
                borderWidth: 1
            }]
        },
        options: {
            scales: {
                y: {
                    beginAtZero: true,
                    max: 100
                }
            }
        }
    });

    // In a real implementation, we would fetch data periodically
}

function setupLogFilter() {
    const logFilter = document.getElementById('logFilter');
    if (!logFilter) return;

    logFilter.addEventListener('input', function() {
        const filterText = this.value.toLowerCase();
        const logEntries = document.querySelectorAll('.log-entry');

        logEntries.forEach(entry => {
            const text = entry.textContent.toLowerCase();
            if (text.includes(filterText)) {
                entry.style.display = '';
            } else {
                entry.style.display = 'none';
            }
        });
    });
}

function setupNavigation() {
    // Smooth scrolling for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function(e) {
            e.preventDefault();
            document.querySelector(this.getAttribute('href')).scrollIntoView({
                behavior: 'smooth'
            });
        });
    });

    // Highlight current section in sidebar
    window.addEventListener('scroll', highlightCurrentSection);
}

function highlightCurrentSection() {
    const sections = document.querySelectorAll('section');
    const navLinks = document.querySelectorAll('.nav-link');

    let currentSection = '';

    sections.forEach(section => {
        const sectionTop = section.offsetTop;
        const sectionHeight = section.clientHeight;

        if (window.pageYOffset >= sectionTop - 100) {
            currentSection = section.getAttribute('id');
        }
    });

    navLinks.forEach(link => {
        link.classList.remove('active');
        if (link.getAttribute('href') === `#${currentSection}`) {
            link.classList.add('active');
        }
    });
}

// Fetch updated data from API periodically
function fetchUpdatedData() {
    // In a real implementation, we would fetch updates from API endpoints
    // and update the charts and tables
}"""
        }

        # Download core libraries (Bootstrap, jQuery, Chart.js)
        # In a real implementation, we might include these files directly
        # or use CDN links. For this example, we'll create placeholder files.
        library_files = {
            "css/bootstrap.min.css": "/* Bootstrap CSS would be here */",
            "js/jquery.min.js": "/* jQuery would be here */",
            "js/bootstrap.bundle.min.js": "/* Bootstrap JS would be here */",
            "js/chart.min.js": "/* Chart.js would be here */"
        }

        # Write all static files
        for filename, content in {**css_files, **js_files, **library_files}.items():
            file_path = os.path.join(DEFAULT_STATIC_DIR, filename)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, 'w') as f:
                f.write(content)

    def _setup_routes(self) -> None:
        """Set up Flask routes for the dashboard."""
        if not self.app:
            return

        def _make_json_serializable(value: Any) -> Any:
            """Convert values to JSON-serializable equivalents.

            This is primarily used to keep dashboard templates resilient when they
            use Jinja's `tojson` filter (which relies on Flask's JSON provider).
            """
            if isinstance(value, Enum):
                # Use the symbolic name for readability/stability (e.g. LogLevel.INFO)
                return value.name
            if isinstance(value, dict):
                return {k: _make_json_serializable(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [_make_json_serializable(v) for v in value]
            return value

        @self.app.route('/')
        def index():
            """Render the main dashboard page."""
            # Check authentication if required
            if self.config.require_auth:
                if not self._check_auth():
                    return redirect(url_for('login'))

            # Get monitoring data
            metrics_registry = get_metrics_registry()

            # Convert metric values to serializable format
            metrics = {}
            for name, instances in metrics_registry.metrics.items():
                metrics[name] = [
                    {
                        "name": m.name,
                        "type": m.type.value,
                        "value": m.value,
                        "timestamp": datetime.fromtimestamp(m.timestamp).strftime('%Y-%m-%d %H:%M:%S'),
                        "labels": m.labels
                    }
                    for m in instances.values()
                ]

            # Get active operations
            operations = [op.to_dict() for op in metrics_registry.operations.values()]
            for op in operations:
                if op['start_time']:
                    op['start_time'] = datetime.fromtimestamp(op['start_time']).strftime('%Y-%m-%d %H:%M:%S')

            # Get system stats
            system_stats = self._get_system_stats()

            # Get logs
            logs = self._get_recent_logs()

            # Get connected nodes (placeholder data)
            nodes = [
                {
                    "id": "QmYourNodeId",
                    "status": "online",
                    "address": "/ip4/127.0.0.1/tcp/4001",
                    "last_seen": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
            ]

            # Calculate uptime
            uptime_seconds = time.time() - self.start_time
            uptime = str(timedelta(seconds=int(uptime_seconds)))

            # Prepare dashboard data
            dashboard_data = {
                "metrics": metrics,
                "operations": operations,
                "logs": logs,
                "nodes": nodes,
                "system_stats": system_stats,
                "node_info": self.node_info,
                "uptime": uptime,
                "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "refresh_interval": self.config.refresh_interval,
                "dashboard_config": asdict(self.config),
                "monitoring_config": _make_json_serializable(
                    asdict(MonitoringSystem.get_instance().config)
                )
            }

            return render_template('index.html', **dashboard_data)

        @self.app.route('/login', methods=['GET', 'POST'])
        def login():
            """Handle login."""
            if request.method == 'POST':
                username = request.form['username']
                password = request.form['password']

                if username == self.config.username and password == self.config.password:
                    # In a real implementation, we would use a session or JWT
                    return redirect(url_for('index'))
                else:
                    return render_template('login.html', error="Invalid credentials")

            return render_template('login.html')

        @self.app.route('/api/metrics')
        def api_metrics():
            """Return metrics data as JSON."""
            metrics_registry = get_metrics_registry()

            # Convert metric values to serializable format
            metrics = {}
            for name, instances in metrics_registry.metrics.items():
                metrics[name] = [
                    {
                        "name": m.name,
                        "type": m.type.value,
                        "value": m.value,
                        "timestamp": m.timestamp,
                        "labels": m.labels
                    }
                    for m in instances.values()
                ]

            return jsonify({"metrics": metrics})

        @self.app.route('/api/operations')
        def api_operations():
            """Return operations data as JSON."""
            metrics_registry = get_metrics_registry()
            operations = [op.to_dict() for op in metrics_registry.operations.values()]

            return jsonify({"operations": operations})

        @self.app.route('/api/logs')
        def api_logs():
            """Return recent logs as JSON."""
            logs = self._get_recent_logs()

            return jsonify({"logs": logs})

        @self.app.route('/api/system')
        def api_system():
            """Return system stats as JSON."""
            system_stats = self._get_system_stats()

            return jsonify({
                "system_stats": system_stats,
                "node_info": self.node_info,
                "uptime": int(time.time() - self.start_time)
            })

    def _get_system_stats(self) -> Dict[str, Any]:
        """Get system statistics."""
        stats = {
            "cpu_percent": 0,
            "memory_used": "0 MB",
            "memory_total": "0 MB",
            "memory_percent": 0,
            "disk_used": "0 GB",
            "disk_total": "0 GB",
            "disk_percent": 0
        }

        if PSUTIL_AVAILABLE:
            try:
                # CPU
                stats["cpu_percent"] = psutil.cpu_percent(interval=0.1)

                # Memory
                memory = psutil.virtual_memory()
                stats["memory_used"] = f"{memory.used / (1024 * 1024):.2f} MB"
                stats["memory_total"] = f"{memory.total / (1024 * 1024):.2f} MB"
                stats["memory_percent"] = memory.percent

                # Disk
                disk = psutil.disk_usage('/')
                stats["disk_used"] = f"{disk.used / (1024 * 1024 * 1024):.2f} GB"
                stats["disk_total"] = f"{disk.total / (1024 * 1024 * 1024):.2f} GB"
                stats["disk_percent"] = disk.percent
            except Exception as e:
                self.logger.warning(f"Error getting system stats: {str(e)}")

        return stats

    def _get_recent_logs(self) -> List[Dict[str, Any]]:
        """Get recent log entries."""
        logs = []

        try:
            log_file = MonitoringSystem.get_instance().config.logger.file_path

            if log_file and os.path.exists(log_file):
                with open(log_file, 'r') as f:
                    # Read last N lines
                    lines = f.readlines()[-self.config.max_log_lines:]

                    for line in lines:
                        # Parse log line (very basic parsing, would need to be improved)
                        parts = line.strip().split(' - ', 3)
                        if len(parts) >= 4:
                            timestamp, name, level, message = parts
                            logs.append({
                                "timestamp": timestamp,
                                "name": name,
                                "level": level,
                                "message": message
                            })
        except Exception as e:
            self.logger.warning(f"Error reading logs: {str(e)}")
            # Add the error as a log entry
            logs.append({
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "name": "admin_dashboard",
                "level": "ERROR",
                "message": f"Error reading log file: {str(e)}"
            })

        return logs

    def _check_auth(self) -> bool:
        """Check if the user is authenticated."""
        # TODO In a real implementation, we would use sessions or JWT. DO SO FUCKING DO IT!!!
        return True

    def start(self) -> bool:
        """
        Start the admin dashboard.

        Returns:
            bool: Whether the dashboard was started successfully
        """
        if not self.initialized:
            self.logger.error("Admin dashboard not initialized")
            return False

        if not FLASK_AVAILABLE:
            self.logger.error("Flask is not available. Install with: pip install flask")
            return False

        if self.running:
            self.logger.warning("Admin dashboard already running")
            return True

        # Start the server in a separate thread
        self.running = True
        self.server_thread = threading.Thread(
            target=self._run_server,
            daemon=True
        )
        self.server_thread.start()

        # Open browser if configured
        if self.config.open_browser:
            url = f"http://{self.config.host}:{self.config.port}"
            threading.Timer(1.0, lambda: webbrowser.open(url)).start()

        self.logger.info(f"Admin dashboard started on http://{self.config.host}:{self.config.port}")
        return True

    def _run_server(self) -> None:
        """Run the Flask server."""
        try:
            self.app.run(
                host=self.config.host,
                port=self.config.port,
                debug=False,
                use_reloader=False,
                threaded=True
            )
        except Exception as e:
            self.logger.error(f"Error running admin dashboard server: {str(e)}")
            self.running = False

    def stop(self) -> bool:
        """
        Stop the admin dashboard.

        Returns:
            bool: Whether the dashboard was stopped successfully
        """
        if not self.running:
            self.logger.warning("Admin dashboard not running")
            return True

        # Stop the server
        self.running = False

        # In a real implementation, we would gracefully shut down the Flask server
        # TODO Write a REAL FUCKING IMPLEMENTATION FOR SHUTTING DOWN THE SERVER!!!!
        # For this example, we'll just join the thread
        if self.server_thread:
            self.server_thread.join(timeout=1.0)

        self.logger.info("Admin dashboard stopped")
        return True

    def get_status(self) -> Dict[str, Any]:
        """
        Get the status of the admin dashboard.

        Returns:
            dict: Dashboard status
        """
        return {
            "running": self.running,
            "initialized": self.initialized,
            "host": self.config.host,
            "port": self.config.port,
            "uptime": time.time() - self.start_time if self.running else 0
        }


def start_dashboard(config: Optional[DashboardConfig] = None) -> AdminDashboard:
    """
    Start the admin dashboard with the given configuration.

    Args:
        config: Dashboard configuration

    Returns:
        AdminDashboard: The dashboard instance
    """
    # Initialize dashboard
    dashboard = AdminDashboard.initialize(config or DashboardConfig())

    # Start the dashboard
    dashboard.start()

    return dashboard


def stop_dashboard() -> bool:
    """
    Stop the admin dashboard.

    Returns:
        bool: Whether the dashboard was stopped successfully
    """
    dashboard = AdminDashboard.get_instance()
    return dashboard.stop()


def get_dashboard_status() -> Dict[str, Any]:
    """
    Get the status of the admin dashboard.

    Returns:
        dict: Dashboard status
    """
    dashboard = AdminDashboard.get_instance()
    return dashboard.get_status()



def example_main():
    # Example usage
    from ipfs_datasets_py.monitoring import MonitoringConfig, LoggerConfig, MetricsConfig, LogLevel

    # Configure monitoring
    monitoring_config = MonitoringConfig(
        enabled=True,
        logger=LoggerConfig(
            name="ipfs_datasets",
            level=LogLevel.DEBUG,
            file_path="ipfs_datasets.log",
            console=True
        ),
        metrics=MetricsConfig(
            enabled=True,
            system_metrics=True,
            collect_interval=5
        )
    )

    # Configure and start dashboard
    dashboard_config = DashboardConfig(
        enabled=True,
        host="127.0.0.1",
        port=8888,
        refresh_interval=5,
        open_browser=True,
        monitoring_config=monitoring_config
    )

    # Start dashboard
    dashboard = start_dashboard(dashboard_config)

    # Keep running until user interrupts
    try:
        print(f"Dashboard running at http://{dashboard_config.host}:{dashboard_config.port}")
        print("Press Ctrl+C to stop")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping dashboard...")
        stop_dashboard()
        print("Dashboard stopped")


if __name__ == "__main__":
    example_main()
