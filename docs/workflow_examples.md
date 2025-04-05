# RAG Query Monitoring: Workflow Examples

This document provides practical workflow examples for implementing and using the RAG Query Monitoring system in various scenarios.

## Example 1: Basic Development Setup

This workflow demonstrates how to set up a basic monitoring environment for development and debugging.

### Step 1: Create Basic Components

```python
import os
from ipfs_datasets_py.rag_query_optimizer import QueryOptimizer
from ipfs_datasets_py.monitoring import MetricsCollector
from ipfs_datasets_py.audit.audit_visualization import OptimizerLearningMetricsVisualizer
from ipfs_datasets_py.optimizer_alert_system import setup_learning_alerts
from ipfs_datasets_py.unified_monitoring_dashboard import create_unified_dashboard

# Create directories
os.makedirs("./dev_monitoring/visualizations", exist_ok=True)
os.makedirs("./dev_monitoring/dashboard", exist_ok=True)

# Create optimizer with learning enabled
optimizer = QueryOptimizer(enable_learning=True)

# Create metrics collector
metrics_collector = MetricsCollector(window_size=1800)  # 30 minutes

# Register optimizer with metrics collector
metrics_collector.register_component("optimizer", optimizer)

# Start metrics collection
metrics_collector.start_collection()
```

### Step 2: Set Up Visualization and Alerts

```python
# Create learning metrics visualizer
visualizer = OptimizerLearningMetricsVisualizer(
    metrics_collector=metrics_collector,
    output_dir="./dev_monitoring/visualizations",
    update_interval=60  # Update every minute for development
)

# Initialize visualizations
visualizer.initialize()

# Set up alert system with development thresholds
alert_system = setup_learning_alerts(
    metrics_collector=metrics_collector,
    thresholds={
        "parameter_oscillation": {
            "window_size": 3,  # Lower threshold for development
            "direction_changes": 2,
            "severity": "info"  # Lower severity for development
        },
        "performance_decline": {
            "success_rate_drop": 0.10,  # 10% drop
            "latency_increase": 0.15,  # 15% increase
            "severity": "warning"
        }
    }
)

# Add console handler for immediate feedback
alert_system.add_handler("console", ConsoleAlertHandler())
```

### Step 3: Create and Use Dashboard

```python
# Create unified dashboard
dashboard = create_unified_dashboard(
    dashboard_dir="./dev_monitoring/dashboard",
    dashboard_title="Development RAG Dashboard",
    refresh_interval=60,  # 1 minute refresh for development
    auto_refresh=True
)

# Register all components
dashboard.register_metrics_collector(metrics_collector)
dashboard.register_learning_visualizer(visualizer)
dashboard.register_alert_system(alert_system)

# Initialize dashboard
dashboard.update_dashboard()

# Print dashboard location
print(f"Dashboard available at: file://{os.path.abspath('./dev_monitoring/dashboard/index.html')}")
```

### Step 4: Simulate Test Data

```python
import time
import random
from datetime import datetime

# Simulate some optimizer activity
def simulate_queries(count=10):
    """Simulate a batch of queries with varied parameters."""
    print(f"Simulating {count} queries...")
    for i in range(count):
        # Simulate query start
        query_id = f"query_{datetime.now().strftime('%Y%m%d%H%M%S')}_{i}"
        query_params = {
            "query_type": random.choice(["factual", "complex", "exploratory"]),
            "max_vector_results": random.randint(3, 10),
            "min_similarity": round(random.uniform(0.5, 0.9), 2),
            "traversal_depth": random.randint(1, 3)
        }
        
        # Record query start
        optimizer.metrics.record_query_start(query_id, query_params)
        
        # Simulate processing time
        time.sleep(random.uniform(0.1, 0.5))
        
        # Simulate results or error
        success = random.random() < 0.85  # 85% success rate
        if success:
            results = [{"id": f"result_{j}", "score": random.random()} for j in range(random.randint(1, 5))]
            optimizer.metrics.record_query_end(
                query_id, 
                results=results,
                metrics={
                    "vector_search_time": random.uniform(0.05, 0.2),
                    "graph_search_time": random.uniform(0.1, 0.3),
                    "strategy": random.choice(["vector_first", "graph_first", "balanced"])
                }
            )
        else:
            optimizer.metrics.record_query_end(
                query_id,
                error="Simulated query error"
            )
            
    # Simulate parameter adaptation
    if random.random() < 0.3:  # 30% chance of adaptation
        param_name = random.choice(["max_vector_results", "min_similarity", "traversal_depth"])
        old_value = optimizer.parameters.get(param_name, 0)
        new_value = old_value + random.choice([-1, 1]) * (0.1 if param_name == "min_similarity" else 1)
        optimizer.parameters[param_name] = new_value
        
        print(f"Adapted parameter {param_name}: {old_value} -> {new_value}")

# Run simulation for a few cycles
for cycle in range(5):
    simulate_queries(count=random.randint(5, 15))
    print(f"Cycle {cycle+1} complete. Waiting for dashboard update...")
    time.sleep(30)  # Wait for dashboard to update
    
print("Simulation complete. Check the dashboard for results.")
```

## Example 2: Production Environment with Slack Integration

This workflow demonstrates setting up monitoring in a production environment with Slack notifications.

### Step 1: Create Production Components

```python
import os
import logging
from ipfs_datasets_py.rag_query_optimizer import QueryOptimizer
from ipfs_datasets_py.monitoring import ProductionMetricsCollector
from ipfs_datasets_py.audit.audit_visualization import OptimizerLearningMetricsVisualizer
from ipfs_datasets_py.optimizer_alert_system import setup_learning_alerts
from ipfs_datasets_py.unified_monitoring_dashboard import create_unified_dashboard
from ipfs_datasets_py.alert_handlers import SlackAlertHandler

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='/var/log/rag_monitoring.log'
)

# Create directories
os.makedirs("/var/www/html/rag_monitoring/visualizations", exist_ok=True)
os.makedirs("/var/www/html/rag_monitoring/dashboard", exist_ok=True)

# Create production optimizer
optimizer = ProductionQueryOptimizer(
    enable_learning=True,
    learning_config={
        "learning_rate": 0.05,
        "exploration_rate": 0.1,
        "min_queries_before_adaptation": 100
    }
)

# Create production metrics collector
metrics_collector = ProductionMetricsCollector(
    window_size=86400,  # 24 hours
    collection_interval=30,  # 30 seconds
    storage_backend="redis",
    redis_config={
        "host": "redis.example.com",
        "port": 6379,
        "db": 0,
        "password": os.environ.get("REDIS_PASSWORD")
    }
)

# Register optimizer with metrics collector
metrics_collector.register_component("optimizer", optimizer)

# Start metrics collection
metrics_collector.start_collection()
```

### Step 2: Set Up Production Visualization and Alerts

```python
# Create learning metrics visualizer
visualizer = OptimizerLearningMetricsVisualizer(
    metrics_collector=metrics_collector,
    output_dir="/var/www/html/rag_monitoring/visualizations",
    update_interval=1800  # 30 minutes for production
)

# Initialize visualizations
visualizer.initialize()

# Set up alert system with production thresholds
alert_system = setup_learning_alerts(
    metrics_collector=metrics_collector,
    thresholds={
        "parameter_oscillation": {
            "window_size": 10,  # Higher for production
            "direction_changes": 5,
            "severity": "warning"
        },
        "performance_decline": {
            "success_rate_drop": 0.20,  # 20% drop for production
            "latency_increase": 0.30,  # 30% increase for production
            "severity": "critical"
        },
        "learning_stall": {
            "min_queries": 500,  # Higher for production
            "min_adaptations": 2,
            "severity": "warning"
        }
    }
)

# Add Slack handler for notifications
slack_handler = SlackAlertHandler(
    webhook_url=os.environ.get("SLACK_WEBHOOK_URL"),
    channel="#rag-alerts",
    username="RAG Monitoring",
    icon_emoji=":robot_face:",
    # Only send warnings and criticals to Slack
    min_severity="warning"
)
alert_system.add_handler("slack", slack_handler)

# Add log handler for all alerts
alert_system.add_handler("log", LoggingAlertHandler(
    logger=logging.getLogger("rag_alerts")
))
```

### Step 3: Create Production Dashboard

```python
# Create unified dashboard
dashboard = create_unified_dashboard(
    dashboard_dir="/var/www/html/rag_monitoring/dashboard",
    dashboard_title="Production RAG Monitoring",
    refresh_interval=1800,  # 30 minutes for production
    auto_refresh=True,
    max_alerts=1000
)

# Register all components
dashboard.register_metrics_collector(metrics_collector)
dashboard.register_learning_visualizer(visualizer)
dashboard.register_alert_system(alert_system)

# Initialize dashboard
dashboard.update_dashboard()

# Set up a cron job to update dashboard (alternative to auto-refresh)
with open("/etc/cron.d/rag_dashboard", "w") as f:
    f.write("*/30 * * * * www-data /usr/bin/python3 /path/to/update_dashboard.py\n")

# Create update script
with open("/path/to/update_dashboard.py", "w") as f:
    f.write("""#!/usr/bin/env python3
import sys
sys.path.append("/path/to/app")
from ipfs_datasets_py.unified_monitoring_dashboard import load_dashboard

# Load and update dashboard
dashboard = load_dashboard("/var/www/html/rag_monitoring/dashboard")
dashboard.update_dashboard()
""")

# Make script executable
os.chmod("/path/to/update_dashboard.py", 0o755)
```

## Example 3: Advanced Multi-Environment Monitoring

This workflow demonstrates how to set up monitoring across multiple environments (development, staging, production) with centralized reporting.

### Step 1: Create Configuration System

```python
import os
import yaml
import argparse

def load_config(env):
    """Load configuration for the specified environment."""
    config_path = f"./config/monitoring_{env}.yaml"
    with open(config_path, "r") as f:
        return yaml.safe_load(f)

def setup_monitoring(env):
    """Set up monitoring for the specified environment."""
    # Load configuration
    config = load_config(env)
    
    # Create directories
    os.makedirs(config["paths"]["visualizations"], exist_ok=True)
    os.makedirs(config["paths"]["dashboard"], exist_ok=True)
    
    # Create components based on configuration
    # (implementation details)
    
    return dashboard

# Parse command line arguments
parser = argparse.ArgumentParser(description="Set up RAG query monitoring")
parser.add_argument("--env", choices=["dev", "staging", "prod"], default="dev",
                   help="Environment to set up monitoring for")
args = parser.parse_args()

# Set up monitoring for specified environment
dashboard = setup_monitoring(args.env)
```

### Step 2: Create Environment-Specific Configurations

```yaml
# config/monitoring_dev.yaml
---
paths:
  visualizations: "./monitoring/dev/visualizations"
  dashboard: "./monitoring/dev/dashboard"
  logs: "./logs/rag_monitoring_dev.log"

metrics:
  window_size: 1800  # 30 minutes
  collection_interval: 10  # 10 seconds
  storage: "memory"

alerts:
  handlers:
    - type: "console"
    - type: "log"
      config:
        log_path: "./logs/rag_alerts_dev.log"
  thresholds:
    parameter_oscillation:
      window_size: 3
      direction_changes: 2
      severity: "info"
    performance_decline:
      success_rate_drop: 0.10
      latency_increase: 0.15
      severity: "warning"

dashboard:
  title: "DEV - RAG Query Dashboard"
  refresh_interval: 60  # 1 minute
  auto_refresh: true
  max_alerts: 50
```

```yaml
# config/monitoring_prod.yaml
---
paths:
  visualizations: "/var/www/html/rag_monitoring/visualizations"
  dashboard: "/var/www/html/rag_monitoring/dashboard"
  logs: "/var/log/rag_monitoring.log"

metrics:
  window_size: 86400  # 24 hours
  collection_interval: 30  # 30 seconds
  storage: "redis"
  redis:
    host: "redis.example.com"
    port: 6379
    db: 0
    password_env: "REDIS_PASSWORD"

alerts:
  handlers:
    - type: "slack"
      config:
        webhook_url_env: "SLACK_WEBHOOK_URL"
        channel: "#rag-alerts"
        username: "RAG Monitoring"
        icon_emoji: ":robot_face:"
        min_severity: "warning"
    - type: "log"
      config:
        log_path: "/var/log/rag_alerts.log"
    - type: "pagerduty"
      config:
        routing_key_env: "PAGERDUTY_ROUTING_KEY"
        min_severity: "critical"
  thresholds:
    parameter_oscillation:
      window_size: 10
      direction_changes: 5
      severity: "warning"
    performance_decline:
      success_rate_drop: 0.20
      latency_increase: 0.30
      severity: "critical"
    learning_stall:
      min_queries: 500
      min_adaptations: 2
      severity: "warning"

dashboard:
  title: "Production RAG Monitoring"
  refresh_interval: 1800  # 30 minutes
  auto_refresh: true
  max_alerts: 1000
  security:
    require_auth: true
    auth_config:
      type: "basic"
      users_file: "/etc/rag_monitoring/users.htpasswd"
```

### Step 3: Create Central Monitoring Aggregator

```python
from ipfs_datasets_py.monitoring import CentralMonitoringAggregator

# Create central aggregator
aggregator = CentralMonitoringAggregator(
    environments=[
        {"name": "development", "url": "http://dev-server:8080/api/metrics"},
        {"name": "staging", "url": "http://staging-server:8080/api/metrics"},
        {"name": "production", "url": "http://prod-server:8080/api/metrics"}
    ],
    authentication={
        "type": "api_key",
        "key_name": "X-API-Key",
        "key": os.environ.get("MONITORING_API_KEY")
    },
    sync_interval=300  # 5 minutes
)

# Create central dashboard
central_dashboard = create_unified_dashboard(
    dashboard_dir="/var/www/html/central_monitoring",
    dashboard_title="RAG Monitoring - All Environments",
    refresh_interval=300,
    auto_refresh=True,
    central_mode=True,
    aggregator=aggregator
)

# Start aggregation
aggregator.start()
```

## Example 4: Custom Alert and Visualization Integration

This workflow demonstrates how to create custom alert handlers and visualizations.

### Step 1: Create Custom Alert Handler

```python
from ipfs_datasets_py.optimizer_alert_system import BaseAlertHandler
import requests

class TeamsAlertHandler(BaseAlertHandler):
    """Custom alert handler for Microsoft Teams."""
    
    def __init__(self, webhook_url, min_severity="info"):
        """
        Initialize Teams alert handler.
        
        Args:
            webhook_url: MS Teams webhook URL
            min_severity: Minimum severity level to send
        """
        super().__init__(min_severity)
        self.webhook_url = webhook_url
        
    def handle_alert(self, anomaly):
        """
        Handle an alert by sending to Microsoft Teams.
        
        Args:
            anomaly: LearningAnomaly object
        """
        # Skip if below minimum severity
        if not self.should_handle(anomaly.severity):
            return
        
        # Create Teams card
        card = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": self._get_color_for_severity(anomaly.severity),
            "summary": f"RAG Optimizer Alert: {anomaly.anomaly_type}",
            "sections": [{
                "activityTitle": f"RAG Optimizer Alert: {anomaly.anomaly_type}",
                "activitySubtitle": f"Severity: {anomaly.severity.upper()}",
                "facts": [
                    {"name": "Description", "value": anomaly.description},
                    {"name": "Timestamp", "value": anomaly.timestamp.isoformat()},
                    {"name": "Affected Parameters", "value": ", ".join(anomaly.affected_parameters) or "None"}
                ]
            }]
        }
        
        # Send to Teams
        response = requests.post(
            self.webhook_url,
            json=card
        )
        
        # Check response
        if response.status_code != 200:
            logging.error(f"Failed to send Teams alert: {response.status_code} {response.text}")
        
    def _get_color_for_severity(self, severity):
        """Get color for severity level."""
        colors = {
            "critical": "FF0000",  # Red
            "warning": "FFA500",   # Orange
            "info": "0078D7"       # Blue
        }
        return colors.get(severity, "0078D7")
```

### Step 2: Create Custom Visualization

```python
from ipfs_datasets_py.audit.audit_visualization import BaseVisualizer
import matplotlib.pyplot as plt
import numpy as np
import os

class StrategyComparisonVisualizer(BaseVisualizer):
    """Custom visualizer for comparing strategy performance."""
    
    def __init__(self, metrics_collector, output_dir):
        """
        Initialize the visualizer.
        
        Args:
            metrics_collector: Metrics collector instance
            output_dir: Output directory for visualizations
        """
        super().__init__(metrics_collector, output_dir)
        
    def create_visualizations(self):
        """
        Create custom strategy comparison visualizations.
        
        Returns:
            dict: Mapping of visualization names to file paths
        """
        # Get metrics data
        metrics = self.metrics_collector.get_metrics_snapshot()
        learning_metrics = metrics.get('learning_metrics', {})
        
        # Check if we have strategy effectiveness data
        if 'strategy_effectiveness' not in learning_metrics:
            return {}
            
        strategy_data = learning_metrics['strategy_effectiveness']
        
        # Create visualization
        plt.figure(figsize=(12, 8))
        
        # Process data for plotting
        strategies = []
        success_rates = []
        latencies = []
        sample_sizes = []
        
        for strategy, query_types in strategy_data.items():
            for query_type, stats in query_types.items():
                strategies.append(f"{strategy}-{query_type}")
                success_rates.append(stats.get('success_rate', 0))
                latencies.append(stats.get('mean_latency', 0))
                sample_sizes.append(stats.get('sample_size', 0))
        
        # Create subplots
        plt.subplot(2, 1, 1)
        bars = plt.bar(strategies, success_rates)
        plt.title('Strategy Success Rates by Query Type')
        plt.ylabel('Success Rate')
        plt.xticks(rotation=45)
        
        # Add sample size as text on bars
        for i, bar in enumerate(bars):
            plt.text(
                bar.get_x() + bar.get_width()/2,
                bar.get_height() + 0.02,
                f"n={sample_sizes[i]}",
                ha='center',
                fontsize=8
            )
        
        plt.subplot(2, 1, 2)
        plt.bar(strategies, latencies)
        plt.title('Strategy Mean Latencies by Query Type')
        plt.ylabel('Latency (ms)')
        plt.xticks(rotation=45)
        
        plt.tight_layout()
        
        # Save visualization
        output_path = os.path.join(self.output_dir, 'strategy_comparison.png')
        plt.savefig(output_path)
        plt.close()
        
        return {'strategy_comparison': output_path}
```

### Step 3: Register Custom Components

```python
# Create and register custom alert handler
teams_handler = TeamsAlertHandler(
    webhook_url=os.environ.get("TEAMS_WEBHOOK_URL"),
    min_severity="warning"
)
alert_system.add_handler("teams", teams_handler)

# Create and register custom visualizer
custom_visualizer = StrategyComparisonVisualizer(
    metrics_collector=metrics_collector,
    output_dir="./monitoring/custom_visualizations"
)

# Register with dashboard
dashboard.register_custom_visualizer(custom_visualizer)
```

## Example 5: Automated Monitoring with CI/CD Pipeline

This workflow demonstrates how to integrate RAG query monitoring into a CI/CD pipeline.

### Step 1: Create Pipeline Configuration

```yaml
# .github/workflows/monitoring.yml
name: RAG Query Monitoring

on:
  schedule:
    - cron: '*/30 * * * *'  # Run every 30 minutes
  workflow_dispatch:  # Allow manual triggers

jobs:
  update-dashboard:
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout repository
        uses: actions/checkout@v2
        
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.9'
          
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          
      - name: Update monitoring dashboard
        run: python scripts/update_monitoring.py
        env:
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
          REDIS_PASSWORD: ${{ secrets.REDIS_PASSWORD }}
          
      - name: Deploy dashboard
        uses: peaceiris/actions-gh-pages@v3
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: ./monitoring/dashboard
          destination_dir: monitoring
```

### Step 2: Create Update Script

```python
#!/usr/bin/env python3
# scripts/update_monitoring.py

import os
import sys
import logging
from ipfs_datasets_py.unified_monitoring_dashboard import load_dashboard, create_unified_dashboard
from ipfs_datasets_py.monitoring import MetricsCollector
from ipfs_datasets_py.optimizer_alert_system import setup_learning_alerts
from ipfs_datasets_py.alert_handlers import SlackAlertHandler

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create directories
os.makedirs("./monitoring/dashboard", exist_ok=True)
os.makedirs("./monitoring/visualizations", exist_ok=True)

def main():
    # Try to load existing dashboard
    try:
        dashboard = load_dashboard("./monitoring/dashboard")
        logger.info("Loaded existing dashboard")
    except Exception as e:
        logger.warning(f"Could not load existing dashboard: {e}")
        logger.info("Creating new dashboard")
        
        # Create metrics collector
        metrics_collector = MetricsCollector()
        
        # Set up alert system
        alert_system = setup_learning_alerts(metrics_collector)
        
        # Add Slack handler if webhook URL is available
        slack_webhook = os.environ.get("SLACK_WEBHOOK_URL")
        if slack_webhook:
            slack_handler = SlackAlertHandler(webhook_url=slack_webhook)
            alert_system.add_handler("slack", slack_handler)
        
        # Create dashboard
        dashboard = create_unified_dashboard(
            dashboard_dir="./monitoring/dashboard",
            dashboard_title="RAG Optimizer Monitoring",
            auto_refresh=False  # No auto-refresh for CI/CD
        )
        
        # Register components
        dashboard.register_metrics_collector(metrics_collector)
        dashboard.register_alert_system(alert_system)
    
    # Update dashboard
    logger.info("Updating dashboard")
    dashboard.update_dashboard()
    logger.info("Dashboard updated successfully")

if __name__ == "__main__":
    main()
```

These examples demonstrate a variety of ways to implement and customize the RAG Query Monitoring system for different environments and use cases. You can adapt these examples to your specific needs and integrate them into your existing workflows.