#!/usr/bin/env python3
"""
RAG Query and Audit Visualization Integration Example

This example demonstrates how to integrate RAG (Retrieval Augmented Generation) query
performance monitoring with security audit logging to create a comprehensive
visualization dashboard that shows correlations between security events and
query performance.

Key components demonstrated:
- RAG query metrics collection
- Audit logging and metrics aggregation
- Integrated visualization dashboard
- Security-performance correlation analysis
"""

import os
import time
import datetime
import logging
import tempfile
from typing import Dict, List, Any, Optional

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Import RAG query components
try:
    from ipfs_datasets_py.rag.rag_query_optimizer import QueryMetricsCollector
    from ipfs_datasets_py.rag.rag_query_visualization import RAGQueryDashboard
    RAG_COMPONENTS_AVAILABLE = True
except ImportError:
    logger.warning("RAG query components not available. Some features will be disabled.")
    RAG_COMPONENTS_AVAILABLE = False

# Import audit components
try:
    from ipfs_datasets_py.audit.audit_logger import (
        AuditLogger, AuditEvent, AuditLevel, AuditCategory
    )
    from ipfs_datasets_py.audit.audit_visualization import AuditMetricsAggregator
    AUDIT_COMPONENTS_AVAILABLE = True
except ImportError:
    logger.warning("Audit components not available. Some features will be disabled.")
    AUDIT_COMPONENTS_AVAILABLE = False

def setup_monitoring_system():
    """Initialize the monitoring and visualization system."""
    logger.info("Setting up visualization monitoring system")

    if not RAG_COMPONENTS_AVAILABLE:
        logger.error("RAG query components required for this example")
        return None

    if not AUDIT_COMPONENTS_AVAILABLE:
        logger.error("Audit components required for this example")
        return None

    # Create metrics collectors
    query_metrics = QueryMetricsCollector()

    # Set up audit logger
    audit_logger = AuditLogger.get_instance()
    audit_metrics = AuditMetricsAggregator()

    # Create visualization dashboard
    dashboard_dir = tempfile.mkdtemp(prefix="rag_audit_visualization_")
    dashboard = RAGQueryDashboard(
        metrics_collector=query_metrics,
        dashboard_dir=dashboard_dir,
        theme="light"
    )

    logger.info(f"Monitoring system set up with dashboard directory: {dashboard_dir}")

    return {
        "query_metrics": query_metrics,
        "audit_logger": audit_logger,
        "audit_metrics": audit_metrics,
        "dashboard": dashboard,
        "dashboard_dir": dashboard_dir
    }

def simulate_rag_queries(components, count=10, performance_degradation=None):
    """
    Simulate RAG queries with metrics collection.

    Args:
        components: Dictionary containing monitoring components
        count: Number of queries to simulate
        performance_degradation: None or tuple (start_index, factor) for simulating degradation
    """
    if not RAG_COMPONENTS_AVAILABLE:
        logger.error("RAG query components required for this example")
        return

    logger.info(f"Simulating {count} RAG queries")

    # Extract components
    query_metrics = components["query_metrics"]

    # Simulate queries
    for i in range(count):
        # Determine if this query should be degraded
        degradation_factor = 1.0
        if performance_degradation:
            start_index, factor = performance_degradation
            if i >= start_index:
                degradation_factor = factor

        # Simulate query
        query_id = f"query_{i}"
        query_params = {
            "max_depth": 2,
            "traversal": {"max_depth": 2, "relationship_types": ["related_to", "contains"]},
            "max_vector_results": 5 + (i % 5),  # Varies from 5 to 9
            "min_similarity": 0.6 + (i % 5) * 0.05  # Varies from 0.6 to 0.8
        }

        # Start tracking query
        query_metrics.start_query_tracking(query_id=query_id, query_params=query_params)

        # Simulate vector search phase
        query_metrics.start_phase(query_id, "vector_search")
        time.sleep(0.02 * degradation_factor)  # Sleep longer if degraded
        query_metrics.end_phase(query_id, "vector_search")

        # Simulate graph traversal phase
        query_metrics.start_phase(query_id, "graph_traversal")
        time.sleep(0.05 * degradation_factor)  # Sleep longer if degraded
        query_metrics.end_phase(query_id, "graph_traversal")

        # Simulate result ranking phase
        query_metrics.start_phase(query_id, "ranking")
        time.sleep(0.01 * degradation_factor)  # Sleep longer if degraded
        query_metrics.end_phase(query_id, "ranking")

        # Complete query tracking
        results_count = 10 - (i % 3) if degradation_factor == 1.0 else max(2, 10 - (i % 5))
        quality_score = 0.8 - (i % 5) * 0.05 if degradation_factor == 1.0 else 0.7 - (i % 5) * 0.08

        query_metrics.end_query_tracking(
            query_id=query_id,
            results={
                "count": results_count,
                "quality_score": quality_score,
                "sources": [f"doc_{j}" for j in range(results_count)]
            }
        )

        # Add a small delay between queries
        time.sleep(0.1)

    logger.info("Completed simulating RAG queries")

def simulate_audit_events(components, count=20, error_burst=None):
    """
    Simulate audit events with varying severity.

    Args:
        components: Dictionary containing monitoring components
        count: Number of events to simulate
        error_burst: None or tuple (start_index, count) for simulating a burst of errors
    """
    if not AUDIT_COMPONENTS_AVAILABLE:
        logger.error("Audit components required for this example")
        return

    logger.info(f"Simulating {count} audit events")

    # Extract components
    audit_logger = components["audit_logger"]

    # Define event categories and actions
    categories = [
        AuditCategory.DATA_ACCESS,
        AuditCategory.SECURITY,
        AuditCategory.SYSTEM
    ]

    actions = {
        AuditCategory.DATA_ACCESS: ["read", "write", "modify", "delete"],
        AuditCategory.SECURITY: ["login", "logout", "permission_change", "credential_refresh"],
        AuditCategory.SYSTEM: ["startup", "shutdown", "config_change", "health_check"]
    }

    resources = ["dataset_1", "dataset_2", "user_db", "system_config", "auth_service"]

    # Simulate events
    for i in range(count):
        # Determine if this should be an error event (part of a burst)
        is_error = False
        if error_burst:
            start_index, error_count = error_burst
            if start_index <= i < start_index + error_count:
                is_error = True

        # Choose category and action based on index or error state
        if is_error:
            category = AuditCategory.SECURITY
            action = "unauthorized_access" if i % 2 == 0 else "suspicious_activity"
            level = AuditLevel.ERROR if i % 3 != 0 else AuditLevel.CRITICAL
            status = "failure"
            resource = resources[i % len(resources)]
        else:
            category = categories[i % len(categories)]
            action = actions[category][i % len(actions[category])]
            level = AuditLevel.INFO if i % 5 != 0 else AuditLevel.WARNING
            status = "success" if i % 7 != 0 else "partial"
            resource = resources[i % len(resources)]

        # Create and log the event
        event = AuditEvent(
            event_id=f"event_{i}",
            timestamp=datetime.datetime.now().isoformat(),
            level=level,
            category=category,
            action=action,
            status=status,
            user=f"user_{i % 3}",
            resource_id=resource,
            resource_type="dataset" if "dataset" in resource else "service",
            message=f"Simulated {level.name} event for {action} on {resource}",
            details={
                "simulation_id": i,
                "is_error_burst": is_error,
                "timestamp_seconds": time.time()
            }
        )

        audit_logger.log_event_obj(event)

        # Add a small delay between events
        time.sleep(0.05)

    logger.info("Completed simulating audit events")

def create_visualizations(components):
    """
    Create visualization dashboards for the simulated data.

    Args:
        components: Dictionary containing monitoring components

    Returns:
        Dictionary of output file paths
    """
    if not RAG_COMPONENTS_AVAILABLE or not AUDIT_COMPONENTS_AVAILABLE:
        logger.error("Both RAG and audit components required for visualizations")
        return {}

    logger.info("Creating visualizations")

    # Extract components
    dashboard = components["dashboard"]
    dashboard_dir = components["dashboard_dir"]
    audit_metrics = components["audit_metrics"]

    # Create visualization directory
    vis_dir = os.path.join(dashboard_dir, "visualizations")
    os.makedirs(vis_dir, exist_ok=True)

    # Generate output files
    output_files = {}

    # 1. Create the integrated query-audit timeline
    timeline_path = os.path.join(vis_dir, "query_audit_timeline.png")
    logger.info(f"Generating query-audit timeline visualization to: {timeline_path}")

    dashboard.visualize_query_audit_metrics(
        audit_metrics_aggregator=audit_metrics,
        output_file=timeline_path,
        title="Query Performance & Audit Events Timeline",
        show_plot=False
    )
    output_files["timeline"] = timeline_path

    # 2. Create interactive timeline if possible
    try:
        interactive_timeline_path = os.path.join(vis_dir, "interactive_timeline.html")
        dashboard.visualize_query_audit_metrics(
            audit_metrics_aggregator=audit_metrics,
            output_file=interactive_timeline_path,
            interactive=True,
            title="Interactive Query & Audit Timeline",
            show_plot=False
        )
        output_files["interactive_timeline"] = interactive_timeline_path
    except Exception as e:
        logger.warning(f"Could not create interactive timeline: {e}")

    # 3. Create the complete integrated dashboard
    dashboard_path = os.path.join(dashboard_dir, "integrated_dashboard.html")
    logger.info(f"Generating integrated dashboard to: {dashboard_path}")

    dashboard.generate_integrated_dashboard(
        output_file=dashboard_path,
        audit_metrics_aggregator=audit_metrics,
        title="Integrated Query Performance & Security Dashboard",
        include_performance=True,
        include_security=True,
        include_query_audit_timeline=True
    )
    output_files["dashboard"] = dashboard_path

    logger.info(f"Visualizations created in: {vis_dir}")
    return output_files

def run_example():
    """
    Run the complete example with RAG queries and audit events.

    Returns:
        Dictionary of output file paths
    """
    logger.info("Starting RAG query and audit visualization example")

    # Set up monitoring system
    components = setup_monitoring_system()
    if not components:
        logger.error("Failed to set up monitoring system")
        return {}

    # Run simulations

    # First simulate some normal queries
    simulate_rag_queries(components, count=10)

    # Simulate some normal audit events
    simulate_audit_events(components, count=10)

    # Simulate security incident with degraded performance
    logger.info("Simulating security incident with performance impact")
    simulate_audit_events(components, count=5, error_burst=(0, 5))
    simulate_rag_queries(components, count=5, performance_degradation=(0, 2.5))

    # Simulate recovery
    logger.info("Simulating recovery")
    simulate_audit_events(components, count=5)
    simulate_rag_queries(components, count=5)

    # Create visualizations
    output_files = create_visualizations(components)

    logger.info("Example completed successfully")
    return output_files

if __name__ == "__main__":
    try:
        # Run the example
        output_files = run_example()

        # Display results
        if output_files:
            print("\nExample completed successfully!")
            print("\nOutput files:")
            for name, path in output_files.items():
                print(f"- {name}: {path}")

            print("\nTip: Open the dashboard HTML file in a web browser to explore the visualization")
        else:
            print("\nExample failed. Please check the logs for more information.")
    except Exception as e:
        logger.error(f"Example failed with error: {str(e)}", exc_info=True)
