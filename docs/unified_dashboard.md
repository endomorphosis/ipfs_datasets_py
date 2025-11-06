# Unified Monitoring Dashboard

The Unified Monitoring Dashboard provides a comprehensive monitoring solution for the RAG Query Optimizer by integrating multiple monitoring components, including learning metrics visualization, alert notifications, performance statistics, and system health indicators.

## Overview

The dashboard combines data from several sources into a cohesive, interactive web interface that provides a complete view of system health and performance. It is designed to be:

- **Comprehensive**: Integrates all monitoring components in one place
- **Real-time**: Provides up-to-date information with configurable refresh intervals
- **Interactive**: Allows filtering and exploration of monitoring data
- **Extensible**: Can be easily extended with new metrics and visualizations

## Components

The unified dashboard integrates the following components:

### 1. Learning Metrics Visualization

- Visualizes how the optimizer learns over time
- Shows parameter adaptations and their effects
- Displays strategy effectiveness across different query types
- Provides both static and interactive visualizations

### 2. Alert Notifications

- Displays alerts from the Learning Alert System
- Categorizes alerts by severity (critical, warning, info)
- Provides filtering capabilities for focused analysis
- Shows detailed alert information including affected parameters

### 3. Performance Statistics

- Tracks query success rates and latencies
- Monitors resource usage (CPU, memory)
- Provides query breakdown by type and strategy
- Shows percentile-based performance metrics

### 4. System Health Indicators

- Provides at-a-glance system status
- Tracks learning status (enabled/disabled)
- Shows active alerts by severity
- Monitors critical performance metrics

## Dashboard Structure

The dashboard is organized into tabs for easy navigation:

1. **Overview**: Provides a summary of system status, recent alerts, and key metrics
2. **Learning Metrics**: Detailed view of learning cycles, parameter adaptations, and strategy effectiveness
3. **Alerts**: Complete alert history with filtering capabilities
4. **Performance**: Comprehensive performance metrics and resource usage

## Getting Started

### Installation

No additional installation is required beyond the core `ipfs_datasets_py` package.

### Basic Usage

```python
from ipfs_datasets_py.unified_monitoring_dashboard import create_unified_dashboard
from ipfs_datasets_py.audit.audit_visualization import OptimizerLearningMetricsVisualizer
from ipfs_datasets_py.optimizer_alert_system import LearningAlertSystem

# Create dashboard
dashboard = create_unified_dashboard(
    dashboard_dir="./monitoring_dashboard",
    dashboard_title="RAG Optimizer Dashboard",
    refresh_interval=300,  # 5 minutes
    auto_refresh=True
)

# Register components
dashboard.register_learning_visualizer(my_visualizer)
dashboard.register_alert_system(my_alert_system)
dashboard.register_metrics_collector(my_metrics_collector)

# Update dashboard (also happens automatically with auto_refresh)
dashboard.update_dashboard()
```

### Running the Demo

To see the dashboard in action, run the provided example:

```bash
python examples/unified_dashboard_example.py --dir ./dashboard_demo --duration 300
```

This will create a demo dashboard with simulated data that updates in real-time.

## Configuration Options

The dashboard can be configured with the following options:

| Option | Description | Default |
|--------|-------------|---------|
| `dashboard_dir` | Directory to store dashboard files | *Required* |
| `dashboard_title` | Title for the dashboard | "RAG Optimizer Monitoring Dashboard" |
| `refresh_interval` | Interval in seconds for automatic updates | 300 (5 minutes) |
| `auto_refresh` | Whether to enable automatic updates | True |
| `max_alerts` | Maximum number of alerts to display | 100 |
| `template_dir` | Directory for custom dashboard templates | None |

## Integration with Existing Components

### Learning Metrics Visualizer

Register an existing `OptimizerLearningMetricsVisualizer` instance:

```python
dashboard.register_learning_visualizer(visualizer)
```

### Alert System

Register an existing `LearningAlertSystem` instance:

```python
dashboard.register_alert_system(alert_system)
```

This will automatically register an alert handler with the alert system to capture alerts for display in the dashboard.

### Metrics Collector

Register an existing `MetricsCollector` instance:

```python
dashboard.register_metrics_collector(metrics_collector)
```

## Custom Templates

You can provide custom dashboard templates by specifying a `template_dir`:

```python
dashboard = create_unified_dashboard(
    dashboard_dir="./dashboard",
    template_dir="./custom_templates"
)
```

The system will look for the following template files:
- `dashboard.html`: Main dashboard template
- `overview.html`: Overview tab template
- `learning.html`: Learning metrics tab template
- `alerts.html`: Alerts tab template
- `performance.html`: Performance tab template

## Auto-Refresh Control

You can programmatically start and stop the auto-refresh functionality:

```python
# Start auto-refresh
dashboard.start_auto_refresh()

# Stop auto-refresh
dashboard.stop_auto_refresh()
```

## Best Practices

### Performance Considerations

- Set an appropriate refresh interval based on your monitoring needs
- Consider using static visualizations for better performance
- Limit the number of alerts stored for display

### Integration with Other Systems

The dashboard can be easily integrated with other monitoring systems:

- Use the JSON exports for integration with other dashboards
- Implement custom alert handlers to forward alerts to systems like Slack or email
- Schedule regular updates using cron or other schedulers

## API Reference

### UnifiedDashboard Class

The main class that implements the unified dashboard functionality.

#### Methods

- `register_learning_visualizer(visualizer)`: Register a learning metrics visualizer
- `register_alert_system(alert_system)`: Register an alert system
- `register_metrics_collector(metrics_collector)`: Register a metrics collector
- `update_dashboard()`: Update the dashboard with current data
- `start_auto_refresh()`: Start automatic dashboard refreshing
- `stop_auto_refresh()`: Stop automatic dashboard refreshing

#### Helper Function

- `create_unified_dashboard(...)`: Create and set up a dashboard instance

## Example Integration

Here's a complete example showing how to integrate the unified dashboard with actual components:

```python
from ipfs_datasets_py.unified_monitoring_dashboard import create_unified_dashboard
from ipfs_datasets_py.audit.audit_visualization import OptimizerLearningMetricsVisualizer
from ipfs_datasets_py.optimizer_alert_system import setup_learning_alerts
from ipfs_datasets_py.monitoring import setup_metrics_collection
from ipfs_datasets_py.rag.rag_query_optimizer import QueryOptimizer

# Create optimizer
optimizer = QueryOptimizer()

# Set up monitoring components
metrics_collector = setup_metrics_collection(optimizer)
visualizer = OptimizerLearningMetricsVisualizer(metrics_collector)
alert_system = setup_learning_alerts(metrics_collector)

# Create dashboard
dashboard = create_unified_dashboard(
    dashboard_dir="./monitoring",
    dashboard_title="Production RAG Optimizer Dashboard",
    refresh_interval=600  # 10 minutes
)

# Register components
dashboard.register_metrics_collector(metrics_collector)
dashboard.register_learning_visualizer(visualizer)
dashboard.register_alert_system(alert_system)

# Initial update
dashboard.update_dashboard()

# Start automatic refreshing
dashboard.start_auto_refresh()
```