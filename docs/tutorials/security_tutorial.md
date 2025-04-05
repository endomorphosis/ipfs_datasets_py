# Security and Performance Visualization Tutorial

This tutorial demonstrates how to use the visualization components to monitor, analyze, and correlate security events and query performance in your IPFS Datasets Python applications.

## Table of Contents

1. [Introduction](#introduction)
2. [Prerequisites](#prerequisites)
3. [Setting Up the Audit and Metrics System](#setting-up-the-audit-and-metrics-system)
4. [Generating Basic Visualizations](#generating-basic-visualizations)
5. [Creating an Integrated Dashboard](#creating-an-integrated-dashboard)
6. [Creating a Query-Audit Timeline](#creating-a-query-audit-timeline)
7. [Launching a Real-time Monitoring Dashboard](#launching-a-real-time-monitoring-dashboard)
8. [Adding Simulated Data for Testing](#adding-simulated-data-for-testing)
9. [Using the Dashboard for Analysis](#using-the-dashboard-for-analysis)
10. [Complete Example](#complete-example)
11. [Advanced Techniques](#advanced-techniques)
12. [Best Practices](#best-practices)

## Introduction

Understanding the relationship between security events and system performance is crucial for maintaining reliable, secure applications. The IPFS Datasets Python library provides integrated visualization tools that allow you to:

1. Monitor security audit events in real-time
2. Track query performance metrics
3. Correlate security events with performance impacts
4. Identify potential security issues through visual analysis
5. Generate comprehensive dashboards for monitoring and reporting

This tutorial will guide you through the process of setting up these visualization components and using them effectively.

## Prerequisites

Before starting this tutorial, ensure you have:

- IPFS Datasets Python library installed with audit logging and visualization components
- Basic familiarity with the audit logging system
- Python environment with matplotlib, seaborn, and jinja2 installed

Required packages:
```bash
pip install matplotlib seaborn jinja2 ipfs_datasets_py
```

## Setting Up the Audit and Metrics System

First, we need to set up the audit logging system and metrics collectors:

```python
from ipfs_datasets_py.audit.audit_logger import AuditLogger, AuditLevel, AuditCategory
from ipfs_datasets_py.audit.audit_visualization import (
    AuditMetricsAggregator, 
    AuditVisualizer, 
    setup_audit_visualization
)
from ipfs_datasets_py.rag_query_optimizer import QueryMetricsCollector

# Get the audit logger
audit_logger = AuditLogger.get_instance()

# Set up audit metrics aggregator and visualizer
metrics_aggregator, visualizer = setup_audit_visualization(audit_logger)

# Create a query metrics collector for tracking query performance
query_metrics = QueryMetricsCollector()
```

## Generating Basic Visualizations

Let's start with generating some basic visualizations of security event data:

```python
# Generate security event distribution by category
visualizer.plot_events_by_category(output_file="events_by_category.png")

# Generate security event severity distribution
visualizer.plot_events_by_level(output_file="events_by_level.png")

# Generate event timeline
visualizer.plot_event_timeline(output_file="event_timeline.png")

# Generate top actions chart
visualizer.plot_top_actions(output_file="top_actions.png")

# Generate error trends visualization
visualizer.plot_error_trends(output_file="error_trends.png")

print("Basic visualizations generated in current directory.")
```

## Creating an Integrated Dashboard

Now, let's create a comprehensive dashboard that integrates both security audit events and query performance metrics:

```python
from ipfs_datasets_py.audit.audit_visualization import generate_integrated_dashboard

# Generate the integrated dashboard
dashboard_path = generate_integrated_dashboard(
    output_file="integrated_dashboard.html",
    audit_logger=audit_logger,
    metrics=metrics_aggregator,
    query_metrics_collector=query_metrics,
    title="Security and Performance Dashboard",
    include_performance=True,
    include_security=True,
    theme="light"  # or "dark"
)

print(f"Integrated dashboard generated at: {dashboard_path}")
```

## Creating a Query-Audit Timeline

The most powerful visualization is the combined timeline showing the relationship between security events and query performance:

```python
from ipfs_datasets_py.audit.audit_visualization import create_query_audit_timeline

# Generate a timeline correlating security events and query performance
timeline_fig = create_query_audit_timeline(
    query_metrics_collector=query_metrics,
    audit_metrics=metrics_aggregator,
    output_file="combined_timeline.png",
    hours_back=24,  # Show last 24 hours
    theme="light",  # or "dark"
    figsize=(12, 8)  # Width, height in inches
)

if timeline_fig:
    print("Combined timeline visualization generated as combined_timeline.png")
```

## Launching a Real-time Monitoring Dashboard

For continuous monitoring, you can launch a real-time dashboard that updates automatically:

```python
from ipfs_datasets_py.rag_query_visualization import RAGQueryDashboard

# Create dashboard with both audit and query metrics
dashboard = RAGQueryDashboard(
    metrics_collector=query_metrics,
    dashboard_dir="./dashboard",
    theme="dark",
    auto_refresh=True,
    refresh_interval=60  # seconds
)

# Generate integrated dashboard with audit metrics
dashboard.generate_integrated_dashboard(
    output_file="./dashboard/dashboard.html",
    audit_metrics_aggregator=metrics_aggregator,
    audit_logger=audit_logger,
    title="Real-time Security and Performance Monitor"
)

# Launch interactive dashboard server
dashboard.launch_dashboard(
    port=8050,
    open_browser=True,
    title="Interactive Monitoring Dashboard"
)
```

## Adding Simulated Data for Testing

For testing purposes, let's add some simulated audit events and query metrics:

```python
import time
import random
import datetime

def generate_test_data(audit_logger, query_metrics, duration_minutes=10):
    """Generate test data for visualization demonstration."""
    print(f"Generating {duration_minutes} minutes of simulated data...")
    
    # Categories and levels for audit events
    categories = [
        AuditCategory.AUTHENTICATION, 
        AuditCategory.DATA_ACCESS,
        AuditCategory.DATA_MODIFICATION,
        AuditCategory.SECURITY
    ]
    
    levels = [
        AuditLevel.INFO,
        AuditLevel.WARNING,
        AuditLevel.ERROR
    ]
    
    actions = [
        "login", "read", "write", "update", "delete", "search", 
        "transform", "export", "verify", "scan"
    ]
    
    # Timespan for data generation
    start_time = time.time() - (duration_minutes * 60)
    end_time = time.time()
    
    # Generate audit events
    timestamp = start_time
    while timestamp < end_time:
        # Add an audit event
        level = random.choice(levels)
        category = random.choice(categories)
        action = random.choice(actions)
        user = f"user{random.randint(1, 5)}"
        resource = f"resource{random.randint(1, 10)}"
        
        event_id = audit_logger.log(
            level=level,
            category=category,
            action=action,
            user=user,
            resource_id=resource,
            resource_type="dataset",
            timestamp=datetime.datetime.fromtimestamp(timestamp).isoformat(),
            details={
                "ip_address": f"192.168.1.{random.randint(1, 255)}",
                "session_id": f"session-{random.randint(1000, 9999)}"
            }
        )
        
        # Add a query metric (less frequently than audit events)
        if random.random() < 0.3:  # 30% chance of adding a query
            query_params = {
                "query_text": f"Sample query {random.randint(1, 100)}",
                "max_results": random.randint(5, 20),
                "max_depth": random.randint(1, 3)
            }
            
            query_metrics.start_query_tracking(
                query_params=query_params,
                timestamp=timestamp
            )
            
            # Add phase timing
            with query_metrics.time_phase("vector_search"):
                # Simulate work by waiting
                time.sleep(0.01)
                
            with query_metrics.time_phase("graph_traversal"):
                # Simulate work by waiting
                time.sleep(0.01)
            
            # End query tracking
            query_metrics.end_query_tracking(
                results_count=random.randint(1, query_params["max_results"]),
                quality_score=random.random(),
                timestamp=timestamp + random.random() * 2  # 0-2 seconds for query execution
            )
        
        # Move forward in time
        timestamp += random.random() * 60  # 0-60 seconds between events
    
    print(f"Generated data spanning {duration_minutes} minutes")

# Generate test data
generate_test_data(audit_logger, query_metrics, duration_minutes=60)
```

## Using the Dashboard for Analysis

Once you have the dashboard set up, you can use it for several types of analysis:

### Identifying Performance Impacts of Security Events

The combined timeline visualization makes it easy to see how security events affect query performance:

1. Look for spikes in query duration that follow security events
2. Examine error-level security events and their correlation with performance drops
3. Filter the timeline by specific time periods to focus on incidents

### Detecting Anomalous Behavior

The dashboard can help identify anomalous behavior that may indicate security issues:

1. Look for unusual patterns in the event timeline
2. Check for spikes in error-level events
3. Monitor query performance degradation that doesn't correlate with expected patterns

### Compliance Reporting

Use the visualizations for compliance reporting:

1. Export the dashboard and visualizations for audit reports
2. Document security events and their impacts
3. Show the correlation between security measures and system performance

## Complete Example

Here's a complete example that sets up the visualization system, generates test data, and creates all the visualizations:

```python
from ipfs_datasets_py.audit.audit_logger import AuditLogger, AuditLevel, AuditCategory
from ipfs_datasets_py.audit.audit_visualization import (
    AuditMetricsAggregator, 
    AuditVisualizer,
    setup_audit_visualization,
    generate_integrated_dashboard,
    create_query_audit_timeline
)
from ipfs_datasets_py.rag_query_optimizer import QueryMetricsCollector
import time
import random
import datetime
import os

# Create output directory
output_dir = "security_visualization_demo"
os.makedirs(output_dir, exist_ok=True)

# Get the audit logger
audit_logger = AuditLogger.get_instance()

# Set up audit metrics aggregator and visualizer
metrics_aggregator, visualizer = setup_audit_visualization(audit_logger)

# Create a query metrics collector for tracking query performance
query_metrics = QueryMetricsCollector()

# Generate test data function
def generate_test_data(audit_logger, query_metrics, duration_minutes=10):
    """Generate test data for visualization demonstration."""
    print(f"Generating {duration_minutes} minutes of simulated data...")
    
    # Categories and levels for audit events
    categories = [
        AuditCategory.AUTHENTICATION, 
        AuditCategory.DATA_ACCESS,
        AuditCategory.DATA_MODIFICATION,
        AuditCategory.SECURITY
    ]
    
    levels = [
        AuditLevel.INFO,
        AuditLevel.WARNING,
        AuditLevel.ERROR
    ]
    
    actions = [
        "login", "read", "write", "update", "delete", "search", 
        "transform", "export", "verify", "scan"
    ]
    
    # Timespan for data generation
    start_time = time.time() - (duration_minutes * 60)
    end_time = time.time()
    
    # Generate audit events
    timestamp = start_time
    while timestamp < end_time:
        # Add an audit event
        level = random.choice(levels)
        category = random.choice(categories)
        action = random.choice(actions)
        user = f"user{random.randint(1, 5)}"
        resource = f"resource{random.randint(1, 10)}"
        
        event_id = audit_logger.log(
            level=level,
            category=category,
            action=action,
            user=user,
            resource_id=resource,
            resource_type="dataset",
            timestamp=datetime.datetime.fromtimestamp(timestamp).isoformat(),
            details={
                "ip_address": f"192.168.1.{random.randint(1, 255)}",
                "session_id": f"session-{random.randint(1000, 9999)}"
            }
        )
        
        # Add a query metric (less frequently than audit events)
        if random.random() < 0.3:  # 30% chance of adding a query
            query_params = {
                "query_text": f"Sample query {random.randint(1, 100)}",
                "max_results": random.randint(5, 20),
                "max_depth": random.randint(1, 3)
            }
            
            query_metrics.start_query_tracking(
                query_params=query_params,
                timestamp=timestamp
            )
            
            # Add phase timing
            with query_metrics.time_phase("vector_search"):
                # Simulate work by waiting
                time.sleep(0.01)
                
            with query_metrics.time_phase("graph_traversal"):
                # Simulate work by waiting
                time.sleep(0.01)
            
            # End query tracking
            query_metrics.end_query_tracking(
                results_count=random.randint(1, query_params["max_results"]),
                quality_score=random.random(),
                timestamp=timestamp + random.random() * 2  # 0-2 seconds for query execution
            )
        
        # Move forward in time
        timestamp += random.random() * 60  # 0-60 seconds between events
    
    print(f"Generated data spanning {duration_minutes} minutes")

# Generate test data for 60 minutes
generate_test_data(audit_logger, query_metrics, duration_minutes=60)

# Generate basic visualizations
visualizer.plot_events_by_category(output_file=f"{output_dir}/events_by_category.png")
visualizer.plot_events_by_level(output_file=f"{output_dir}/events_by_level.png")
visualizer.plot_event_timeline(output_file=f"{output_dir}/event_timeline.png")
visualizer.plot_top_actions(output_file=f"{output_dir}/top_actions.png")
visualizer.plot_error_trends(output_file=f"{output_dir}/error_trends.png")

# Generate the integrated dashboard
dashboard_path = generate_integrated_dashboard(
    output_file=f"{output_dir}/integrated_dashboard.html",
    audit_logger=audit_logger,
    metrics=metrics_aggregator,
    query_metrics_collector=query_metrics,
    title="Security and Performance Dashboard",
    include_performance=True,
    include_security=True,
    theme="light"
)

# Generate the combined timeline visualization
timeline_fig = create_query_audit_timeline(
    query_metrics_collector=query_metrics,
    audit_metrics=metrics_aggregator,
    output_file=f"{output_dir}/combined_timeline.png",
    hours_back=1,
    theme="light",
    figsize=(12, 8)
)

print(f"All visualizations and dashboard created in {output_dir}/")
print(f"View the integrated dashboard at: {dashboard_path}")
```

## Advanced Techniques

### Customizing the Timeline Visualization

You can customize the timeline visualization for specific needs:

```python
from matplotlib.colors import LinearSegmentedColormap

# Create the base timeline
timeline_fig = create_query_audit_timeline(
    query_metrics_collector=query_metrics,
    audit_metrics=metrics_aggregator,
    output_file=None,  # Don't save yet
    hours_back=24
)

# Customize the figure
if timeline_fig:
    # Access the axes (the function creates 2 Y-axes)
    axes = timeline_fig.get_axes()
    primary_ax = axes[0]  # Query duration axis
    secondary_ax = axes[1]  # Audit events axis
    
    # Customize titles and labels
    timeline_fig.suptitle("Custom Security and Performance Timeline", fontsize=16)
    primary_ax.set_title("Query Performance Impact Analysis", fontsize=14)
    primary_ax.set_ylabel("Query Duration (seconds)", color='#1f77b4', fontsize=12)
    secondary_ax.set_ylabel("Security Events", color='#d62728', fontsize=12)
    
    # Add a grid
    primary_ax.grid(True, alpha=0.3)
    
    # Add annotations for important events
    highest_point_idx = max(range(len(primary_ax.lines[0].get_ydata())), 
                          key=lambda i: primary_ax.lines[0].get_ydata()[i])
    x_data = primary_ax.lines[0].get_xdata()
    y_data = primary_ax.lines[0].get_ydata()
    
    if len(x_data) > highest_point_idx:
        primary_ax.annotate('Performance spike',
                         xy=(x_data[highest_point_idx], y_data[highest_point_idx]),
                         xytext=(x_data[highest_point_idx], y_data[highest_point_idx] + 0.5),
                         arrowprops=dict(facecolor='black', shrink=0.05, width=1.5, headwidth=8),
                         ha='center')
    
    # Save the customized figure
    timeline_fig.savefig("customized_timeline.png", dpi=300, bbox_inches='tight')
    print("Customized timeline saved to customized_timeline.png")
```

### Generating Reports Programmatically

You can generate reports programmatically for automation:

```python
import datetime
import os

def generate_security_report(start_date, end_date, output_dir="security_reports"):
    """Generate a comprehensive security report for the specified time period."""
    os.makedirs(output_dir, exist_ok=True)
    
    # Format dates for filenames
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")
    report_name = f"security_report_{start_str}_to_{end_str}"
    
    # Create visualizer with time period filter
    report_aggregator = AuditMetricsAggregator()
    report_visualizer = AuditVisualizer(report_aggregator)
    
    # Get events for the time period
    all_events = audit_logger.get_events(
        start_time=start_date.isoformat(),
        end_time=end_date.isoformat()
    )
    
    # Process events for this report
    for event in all_events:
        report_aggregator.process_event(event)
    
    # Generate visualizations
    report_visualizer.plot_events_by_category(output_file=f"{output_dir}/{report_name}_categories.png")
    report_visualizer.plot_events_by_level(output_file=f"{output_dir}/{report_name}_levels.png")
    report_visualizer.plot_event_timeline(output_file=f"{output_dir}/{report_name}_timeline.png")
    
    # Generate dashboard
    dashboard_path = generate_integrated_dashboard(
        output_file=f"{output_dir}/{report_name}_dashboard.html",
        audit_logger=audit_logger,
        metrics=report_aggregator,
        query_metrics_collector=query_metrics,
        title=f"Security Report {start_str} to {end_str}",
        include_performance=True,
        include_security=True
    )
    
    print(f"Security report generated at {output_dir}/{report_name}_dashboard.html")
    return dashboard_path

# Generate a report for the last 30 days
end_date = datetime.datetime.now()
start_date = end_date - datetime.timedelta(days=30)
report_path = generate_security_report(start_date, end_date)
```

## Best Practices

1. **Regular Monitoring**: Set up a scheduled job to generate and review visualizations daily
2. **Correlation Analysis**: Always analyze security events in correlation with performance metrics
3. **Threshold Alerting**: Implement alerts based on thresholds visible in the visualizations
4. **Historical Comparison**: Compare current visualizations with historical baselines
5. **Documentation**: Document insights gained from visualizations for future reference
6. **Incremental Implementation**: Start with basic visualizations and add complexity as needed
7. **Custom Dashboards**: Create role-specific dashboards (security team, operations team, etc.)
8. **Integrated Monitoring System**: For production environments, consider using the `IntegratedMonitoringSystem` class from our comprehensive example in `examples/rag_audit_integration_example.py`, which provides a complete solution for monitoring both performance and security aspects

### Comprehensive Production Example

For a complete implementation of an integrated monitoring system with advanced features, see the example script in `examples/rag_audit_integration_example.py`. It provides:

- A production-ready `IntegratedMonitoringSystem` class
- Security incident simulation with performance impact analysis
- Comprehensive HTML report generation with anomaly detection
- Multiple visualization types, including heatmaps, timelines, and interactive dashboards
- Command-line interface for customization
- Support for both light and dark themes

You can run the comprehensive example with:

```bash
python -m ipfs_datasets_py.examples.rag_audit_integration_example --output-dir ./monitoring_dashboard --run-time 120 --theme dark
```

## Summary

In this tutorial, you learned how to:
- Set up audit logging and metrics collection
- Generate basic security event visualizations
- Create integrated dashboards that combine security and performance data
- Build a timeline visualization showing the relationship between audit events and query performance
- Launch a real-time monitoring dashboard
- Generate and analyze test data
- Customize visualizations for specific needs
- Generate reports programmatically

These visualization tools provide valuable insights into the relationship between security events and system performance, helping you maintain a secure, high-performance IPFS Datasets Python application.