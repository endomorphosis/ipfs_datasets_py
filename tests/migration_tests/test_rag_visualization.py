#!/usr/bin/env python3
"""
Test script for RAG Query Visualization.

This script tests the RAG query audit visualization functionality.
"""

import os
import time
import datetime
import tempfile
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    """Run the main test function."""
    logger.info("Testing RAG Query Visualization functionality")

    # Create a temporary directory for output files
    temp_dir = tempfile.mkdtemp()
    logger.info(f"Using temporary directory: {temp_dir}")

    try:
        # First test if we can import the needed modules
        logger.info("Importing required modules...")

        # Import query metrics components
        from ipfs_datasets_py.rag.rag_query_optimizer import QueryMetricsCollector
        from ipfs_datasets_py.rag.rag_query_visualization import EnhancedQueryVisualizer
        logger.info("Successfully imported RAG query components")

        # Import audit components
        from ipfs_datasets_py.audit.audit_visualization import AuditMetricsAggregator
        from ipfs_datasets_py.audit.audit_logger import AuditEvent, AuditLevel, AuditCategory
        logger.info("Successfully imported audit components")

        # Create query metrics collector
        logger.info("Creating query metrics collector with sample data...")
        query_metrics = QueryMetricsCollector()

        # Add sample query metrics
        now = time.time()
        for i in range(10):
            # Create query metrics at different times
            query_time = now - (24 * 3600 * i / 10)

            # Add to collector
            query_id = f"test-query-{i}"

            # Create test metrics directly
            metrics = {
                "query_id": query_id,
                "start_time": query_time,
                "duration": 0.5 + (i * 0.05),
                "phases": {
                    "vector_search": {"duration": 0.2 + (i * 0.02)},
                    "graph_traversal": {"duration": 0.2 + (i * 0.02)},
                    "ranking": {"duration": 0.1 + (i * 0.01)}
                },
                "results": {
                    "count": 5 + i,
                    "quality_score": 0.7 + (i * 0.02)
                },
                "params": {
                    "max_depth": 2,
                    "max_results": 10
                }
            }

            # Add to query_metrics manually (this works around the deque access restriction)
            query_metrics.query_metrics.append(metrics)

        logger.info(f"Added {len(query_metrics.query_metrics)} test queries")

        # Create audit metrics aggregator
        logger.info("Creating audit metrics aggregator with sample data...")
        audit_metrics = AuditMetricsAggregator()

        # Add sample audit events
        for i in range(20):
            # Create events at different times
            event_time = now - (24 * 3600 * i / 20)

            # Determine level
            if i % 8 == 0:
                level = AuditLevel.ERROR
            elif i % 4 == 0:
                level = AuditLevel.WARNING
            else:
                level = AuditLevel.INFO

            # Determine category
            if i % 3 == 0:
                category = AuditCategory.SECURITY
            elif i % 3 == 1:
                category = AuditCategory.DATA_ACCESS
            else:
                category = AuditCategory.SYSTEM

            # Create event
            event = AuditEvent(
                event_id=f"test-event-{i}",
                timestamp=datetime.datetime.fromtimestamp(event_time).isoformat(),
                level=level,
                category=category,
                action=f"action-{i % 5}",
                status="success" if i % 5 != 0 else "failure",
                user=f"user-{i % 3}",
                resource_id=f"resource-{i % 4}",
                resource_type=f"type-{i % 2}"
            )

            # Add event to metrics
            audit_metrics.process_event(event)

        logger.info(f"Added audit events, total events: {audit_metrics.totals['total_events']}")

        # Create a visualizer
        logger.info("Creating the visualizer...")
        visualizer = EnhancedQueryVisualizer(
            metrics_collector=query_metrics,
            dashboard_dir=temp_dir
        )

        # Print the visualizer's methods
        methods = [method for method in dir(visualizer) if not method.startswith('_')]
        logger.info(f"Available visualizer methods: {methods}")

        # Check if our visualization method exists
        if hasattr(visualizer, 'visualize_query_audit_metrics'):
            logger.info("Found visualize_query_audit_metrics method!")

            # Use the method to create a visualization
            output_file = os.path.join(temp_dir, "query_audit_metrics.png")
            logger.info(f"Generating visualization to: {output_file}")

            result = visualizer.visualize_query_audit_metrics(
                audit_metrics_aggregator=audit_metrics,
                output_file=output_file,
                time_window=24 * 3600,  # 24 hours
                show_plot=False
            )

            if result is not None:
                logger.info(f"Visualization result: {type(result)}")

            if os.path.exists(output_file):
                logger.info(f"Visualization saved to: {output_file}")
                logger.info(f"File size: {os.path.getsize(output_file)} bytes")
            else:
                logger.error("Visualization file was not created")
        else:
            logger.error("visualize_query_audit_metrics method not found!")

            # Print the implementation to add
            logger.info("Here's the implementation you should add:")
            print("""
def visualize_query_audit_metrics(
    self,
    audit_metrics_aggregator,
    time_window: Optional[int] = None,  # in seconds
    title: str = "Query Performance and Audit Events Timeline",
    show_plot: bool = True,
    output_file: Optional[str] = None,
    interactive: bool = False,
    figsize: Tuple[int, int] = (14, 8)
) -> Optional[Union[Figure, Dict[str, Any]]]:
    # Implementation here
""")

    except Exception as e:
        logger.exception(f"Error during testing: {e}")
    finally:
        logger.info(f"Test script completed. Output directory: {temp_dir}")
        logger.info(f"To view the results, check the files in: {temp_dir}")

if __name__ == "__main__":
    main()
