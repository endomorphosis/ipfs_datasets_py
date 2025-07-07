"""
Unified Dashboard with Real-Time Monitoring Example

This example demonstrates how to create a comprehensive dashboard that integrates
RAG query metrics and audit data with real-time monitoring capabilities.
"""

import os
import sys
import time
import random
import datetime
import logging
import threading
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO,
                  format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Add parent directory to import path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import components
from ipfs_datasets_py.rag_query_dashboard import UnifiedDashboard
from ipfs_datasets_py.rag.rag_query_optimizer import QueryMetricsCollector

# Try to import audit components
try:
    from ipfs_datasets_py.audit.audit_logger import (
        AuditLogger, AuditEvent, AuditLevel, AuditCategory
    )
    from ipfs_datasets_py.audit.audit_visualization import AuditMetricsAggregator
    AUDIT_COMPONENTS_AVAILABLE = True
except ImportError:
    AUDIT_COMPONENTS_AVAILABLE = False
    logging.warning("Audit components not available. Some features will be disabled.")


def generate_sample_metrics():
    """Generate sample metrics for demonstration."""
    # Create query metrics collector
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

    # Create sample audit metrics if available
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

    return query_metrics, audit_metrics


def generate_continuous_data(query_metrics, audit_metrics, interval=5, runtime=300):
    """
    Generate continuous sample data for real-time updates.

    Args:
        query_metrics: QueryMetricsCollector to update
        audit_metrics: AuditMetricsAggregator to update (or None)
        interval: Update interval in seconds
        runtime: How long to run in seconds (None for indefinite)
    """
    start_time = time.time()
    iteration = 0

    try:
        while runtime is None or (time.time() - start_time) < runtime:
            iteration += 1
            logging.info(f"Generating new data (iteration {iteration})...")

            # Add new query metrics
            for i in range(random.randint(1, 5)):
                query_type = random.choice(["vector", "hybrid", "graph", "keyword"])
                duration = random.uniform(50, 500)
                status = random.choices(["success", "failure"], weights=[0.9, 0.1])[0]

                query_metrics.record_query(
                    query_id=f"rt_query_{iteration}_{i}",
                    query_type=query_type,
                    duration_ms=duration,
                    result_count=random.randint(1, 20),
                    status=status
                )

            # Add new audit events if available
            if AUDIT_COMPONENTS_AVAILABLE and audit_metrics:
                for i in range(random.randint(1, 10)):
                    category = random.choice([c.name for c in AuditCategory])
                    level = random.choice([l.name for l in AuditLevel])
                    action = random.choice(["login", "logout", "create", "read", "update", "delete", "query"])
                    user = random.choice(["user1", "user2", "admin1", "admin2"])

                    # Create the event
                    audit_event = AuditEvent(
                        category=category,
                        level=level,
                        action=action,
                        status=random.choices(["success", "failure"], weights=[0.9, 0.1])[0],
                        user=user,
                        timestamp=datetime.datetime.now().isoformat()
                    )

                    # Add security event spike occasionally
                    if iteration % 10 == 0 and i == 0:
                        for j in range(random.randint(5, 15)):
                            security_event = AuditEvent(
                                category="SECURITY",
                                level="WARNING",
                                action="permission_change",
                                status="success",
                                user="admin2",
                                resource_id=f"resource_{j}",
                                timestamp=datetime.datetime.now().isoformat()
                            )
                            audit_metrics.process_event(security_event)

                    # Process regular event
                    audit_metrics.process_event(audit_event)

            # Sleep until next update
            time.sleep(interval)

    except KeyboardInterrupt:
        logging.info("Data generation stopped by user")


def main():
    """Run the dashboard example."""
    print("=" * 80)
    print("Unified Dashboard with Real-Time Monitoring Example")
    print("=" * 80)

    # Create output directory
    dashboard_dir = os.path.join(os.getcwd(), "dashboard_example")
    os.makedirs(dashboard_dir, exist_ok=True)

    # Generate sample metrics
    print("\nGenerating sample metrics...")
    query_metrics, audit_metrics = generate_sample_metrics()

    # Create dashboard
    print("\nCreating unified dashboard...")
    dashboard = UnifiedDashboard(
        dashboard_dir=dashboard_dir,
        enable_realtime=True,
        port=8888
    )

    # Register metrics with dashboard
    dashboard.register_metrics_collector(query_metrics)
    if audit_metrics:
        dashboard.register_metrics_collector(audit_metrics)

    # Create a thread to generate continuous data
    if audit_metrics:
        data_thread = threading.Thread(
            target=generate_continuous_data,
            args=(query_metrics, audit_metrics, 5, None)
        )
        data_thread.daemon = True

    # Generate dashboard
    dashboard_path = dashboard.generate_dashboard(
        query_metrics_collector=query_metrics,
        audit_metrics_aggregator=audit_metrics,
        title="Unified RAG & Audit Dashboard Demo",
        theme="light",
        include_interactive=True
    )

    print("\nDashboard generated!")
    print(f"Dashboard file: {dashboard_path}")
    print(f"Real-time dashboard URL: http://localhost:8888")

    # Start continuous data generation
    if audit_metrics:
        print("\nStarting continuous data generation...")
        data_thread.start()

    # Display instructions
    print("\nInstructions:")
    print("1. Open a web browser and navigate to: http://localhost:8888")
    print("2. The dashboard will update automatically with new data")
    print("3. Press Ctrl+C to stop the server")

    try:
        print("\nServer running. Press Ctrl+C to stop...")
        # Keep main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping server...")
        if dashboard.server:
            dashboard.server.stop()

    print("\nExample complete. Dashboard files are available in the dashboard_example directory.")


if __name__ == "__main__":
    main()
