#!/usr/bin/env python3
"""
Test script to verify the integration of the enhanced RAG query audit visualization.
This test checks that the visualization components are properly integrated and can 
generate audit-query timeline visualizations.
"""

import os
import time
import tempfile
import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

try:
    # Import the main components
    from ipfs_datasets_py.rag_query_visualization import (
        RAGQueryDashboard, EnhancedQueryVisualizer, ENHANCED_VIS_AVAILABLE
    )
    from ipfs_datasets_py.enhanced_rag_visualization import EnhancedQueryAuditVisualizer
    from ipfs_datasets_py.rag_query_optimizer import QueryMetricsCollector
    
    # Try to import audit components if available
    try:
        from ipfs_datasets_py.audit.audit_visualization import AuditMetricsAggregator
        from ipfs_datasets_py.audit.audit_logger import AuditEvent, AuditLevel, AuditCategory
        AUDIT_COMPONENTS_AVAILABLE = True
    except ImportError:
        logging.warning("Audit components not available. Creating mock objects for testing.")
        AUDIT_COMPONENTS_AVAILABLE = False
        
    # Check for visualization libraries
    try:
        import matplotlib
        import seaborn
        VIS_COMPONENTS_AVAILABLE = True
    except ImportError:
        logging.warning("Visualization libraries not available. Test will be limited.")
        VIS_COMPONENTS_AVAILABLE = False
        
except ImportError as e:
    logging.error(f"Missing required components: {e}")
    raise

def create_mock_audit_metrics():
    """Create a mock audit metrics object if the real one is not available."""
    class MockAuditMetricsAggregator:
        def get_recent_events(self, hours_back=24, include_details=False):
            # Generate some test events
            events = []
            now = time.time()
            
            for i in range(20):
                # Create event from the past 24 hours
                event_time = now - (hours_back * 3600 * i / 20)
                
                # Determine level
                if i % 8 == 0:
                    level = "ERROR"
                elif i % 4 == 0:
                    level = "WARNING"
                else:
                    level = "INFO"
                
                # Determine category
                if i % 3 == 0:
                    category = "SECURITY"
                elif i % 3 == 1:
                    category = "DATA_ACCESS"
                else:
                    category = "SYSTEM"
                
                # Create event
                events.append({
                    "event_id": f"test-event-{i}",
                    "timestamp": event_time,
                    "level": level,
                    "category": category,
                    "action": f"action-{i % 5}",
                    "status": "success" if i % 5 != 0 else "failure",
                    "user": f"user-{i % 3}",
                    "resource_id": f"resource-{i % 4}",
                    "resource_type": f"type-{i % 2}",
                    "message": f"Test event {i} with {level} level"
                })
            
            return events
    
    return MockAuditMetricsAggregator()

def create_test_query_metrics():
    """Create test query metrics for visualization."""
    # Create metrics collector
    metrics = QueryMetricsCollector()
    
    # Add some test query metrics
    now = time.time()
    for i in range(10):
        # Add query metric from the past 24 hours
        query_time = now - (24 * 3600 * i / 10)
        
        # Start tracking a query
        metrics.start_query_tracking(
            query_id=f"test-query-{i}",
            query_params={"max_depth": 2, "max_results": 10}
        )
        
        # Set the start time explicitly for testing
        metrics.query_metrics[-1]["start_time"] = query_time
        
        # Add some phase timings
        metrics.query_metrics[-1]["phases"] = {
            "vector_search": {"duration": 0.1 + (i * 0.01)},
            "graph_traversal": {"duration": 0.2 + (i * 0.02)},
            "ranking": {"duration": 0.05 + (i * 0.005)}
        }
        
        # Set the duration
        metrics.query_metrics[-1]["duration"] = 0.35 + (i * 0.035)
        
        # Add results
        metrics.query_metrics[-1]["results"] = {
            "count": 5 + i, 
            "quality_score": 0.7 + (i * 0.02)
        }
    
    return metrics

def test_enhanced_visualization_integration():
    """Test the integration of the enhanced visualization components."""
    logging.info("Testing enhanced visualization integration")
    
    # Create temporary directory for test outputs
    temp_dir = tempfile.mkdtemp()
    logging.info(f"Created temporary directory for test outputs: {temp_dir}")
    
    # Create test components
    query_metrics = create_test_query_metrics()
    
    if AUDIT_COMPONENTS_AVAILABLE:
        logging.info("Using real audit components")
        audit_metrics = AuditMetricsAggregator()
        
        # Add some test events
        now = time.time()
        for i in range(20):
            # Create event
            event = AuditEvent(
                event_id=f"test-event-{i}",
                timestamp=datetime.datetime.fromtimestamp(now - 3600 * i / 20).isoformat(),
                level=AuditLevel.ERROR if i % 8 == 0 else 
                      AuditLevel.WARNING if i % 4 == 0 else AuditLevel.INFO,
                category=AuditCategory.SECURITY if i % 3 == 0 else 
                         AuditCategory.DATA_ACCESS if i % 3 == 1 else AuditCategory.SYSTEM,
                action=f"action-{i % 5}",
                status="success" if i % 5 != 0 else "failure",
                user=f"user-{i % 3}",
                resource_id=f"resource-{i % 4}",
                resource_type=f"type-{i % 2}",
                message=f"Test event {i}"
            )
            
            # Add event to metrics
            audit_metrics.process_event(event)
    else:
        logging.info("Using mock audit components")
        audit_metrics = create_mock_audit_metrics()
    
    # Test visualization components
    logging.info(f"Enhanced visualization available: {ENHANCED_VIS_AVAILABLE}")
    
    # Create dashboard
    dashboard = RAGQueryDashboard(
        metrics_collector=query_metrics,
        dashboard_dir=temp_dir,
        theme="light"
    )
    
    # Check the visualizer type
    if ENHANCED_VIS_AVAILABLE:
        logging.info(f"Dashboard visualizer type: {type(dashboard.visualizer).__name__}")
        assert isinstance(dashboard.visualizer, EnhancedQueryAuditVisualizer), "Dashboard not using enhanced visualizer"
    
    # Generate timeline visualization
    if VIS_COMPONENTS_AVAILABLE:
        timeline_path = os.path.join(temp_dir, "query_audit_timeline.png")
        logging.info(f"Generating timeline visualization to: {timeline_path}")
        
        fig = dashboard.visualize_query_audit_metrics(
            audit_metrics_aggregator=audit_metrics,
            output_file=timeline_path,
            time_window=24 * 3600,  # 24 hours
            show_plot=False
        )
        
        if fig is not None:
            logging.info("Successfully generated visualization")
        
        if os.path.exists(timeline_path):
            logging.info(f"Output file created: {timeline_path}")
            logging.info(f"File size: {os.path.getsize(timeline_path)} bytes")
        else:
            logging.error("Output file was not created!")
    
    # Generate integrated dashboard
    dashboard_path = os.path.join(temp_dir, "integrated_dashboard.html")
    logging.info(f"Generating integrated dashboard to: {dashboard_path}")
    
    try:
        dashboard.generate_integrated_dashboard(
            output_file=dashboard_path,
            audit_metrics_aggregator=audit_metrics,
            title="Test Integrated Dashboard",
            include_query_audit_timeline=True
        )
        
        if os.path.exists(dashboard_path):
            logging.info(f"Dashboard created: {dashboard_path}")
            logging.info(f"File size: {os.path.getsize(dashboard_path)} bytes")
            logging.info(f"Dashboard location: {dashboard_path}")
        else:
            logging.error("Dashboard file was not created!")
    except Exception as e:
        logging.error(f"Error generating dashboard: {e}")
    
    logging.info("Integration test completed")
    return temp_dir

if __name__ == "__main__":
    output_dir = test_enhanced_visualization_integration()
    print(f"\nTest outputs available in: {output_dir}")