#!/usr/bin/env python3
"""
Comprehensive RAG Query and Audit Visualization Integration Example

This example demonstrates the full capabilities of the integrated RAG (Retrieval Augmented Generation)
query performance monitoring and security audit visualization system. It shows how to:

1. Set up both systems together
2. Collect performance metrics during RAG query processing
3. Generate audit events during system operation
4. Visualize correlations between performance and security
5. Create interactive dashboards for monitoring
6. Generate reports for analysis

This comprehensive example is designed to show real-world usage patterns and best practices
for integrated monitoring of both performance and security aspects of RAG systems.
"""

import os
import time
import random
import datetime
import logging
import tempfile
import argparse
import webbrowser
from typing import Dict, List, Any, Optional, Tuple

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Import RAG query components
try:
    from ipfs_datasets_py.rag_query_optimizer import QueryMetricsCollector, UnifiedGraphRAGQueryOptimizer
    from ipfs_datasets_py.rag_query_visualization import (
        RAGQueryDashboard, 
        EnhancedQueryVisualizer,
        create_query_performance_heatmap
    )
    RAG_COMPONENTS_AVAILABLE = True
except ImportError:
    logger.warning("RAG query components not available. Some features will be disabled.")
    RAG_COMPONENTS_AVAILABLE = False

# Import audit components
try:
    from ipfs_datasets_py.audit.audit_logger import (
        AuditLogger, AuditEvent, AuditLevel, AuditCategory
    )
    from ipfs_datasets_py.audit.audit_visualization import (
        AuditMetricsAggregator,
        AuditVisualizer,
        create_query_audit_timeline
    )
    AUDIT_COMPONENTS_AVAILABLE = True
except ImportError:
    logger.warning("Audit components not available. Some features will be disabled.")
    AUDIT_COMPONENTS_AVAILABLE = False

class IntegratedMonitoringSystem:
    """
    Integrated system for monitoring both performance and security aspects of RAG queries.
    This class demonstrates best practices for setting up a comprehensive monitoring solution.
    """
    
    def __init__(self, output_dir=None, theme="light"):
        """
        Initialize the integrated monitoring system.
        
        Args:
            output_dir: Directory for storing dashboards and visualizations
            theme: Visual theme for dashboards ('light' or 'dark')
        """
        self.theme = theme
        self.dashboard_dir = output_dir or tempfile.mkdtemp(prefix="rag_audit_monitoring_")
        os.makedirs(self.dashboard_dir, exist_ok=True)
        
        # Initialize components
        self.query_metrics = QueryMetricsCollector() if RAG_COMPONENTS_AVAILABLE else None
        self.query_optimizer = UnifiedGraphRAGQueryOptimizer() if RAG_COMPONENTS_AVAILABLE else None
        self.audit_logger = AuditLogger.get_instance() if AUDIT_COMPONENTS_AVAILABLE else None
        self.audit_metrics = AuditMetricsAggregator() if AUDIT_COMPONENTS_AVAILABLE else None
        
        # Set up visualization components
        self.query_visualizer = EnhancedQueryVisualizer(
            metrics_collector=self.query_metrics,
            theme=theme
        ) if RAG_COMPONENTS_AVAILABLE else None
        
        self.audit_visualizer = AuditVisualizer(
            theme=theme
        ) if AUDIT_COMPONENTS_AVAILABLE else None
        
        self.dashboard = RAGQueryDashboard(
            metrics_collector=self.query_metrics,
            dashboard_dir=self.dashboard_dir,
            theme=theme
        ) if RAG_COMPONENTS_AVAILABLE else None
        
        # Track generated files
        self.output_files = {}
        self.event_count = 0
        self.query_count = 0
        
        # Verify components
        if not RAG_COMPONENTS_AVAILABLE or not AUDIT_COMPONENTS_AVAILABLE:
            logger.warning("Some components are not available. The example will have limited functionality.")
        else:
            logger.info(f"Integrated monitoring system initialized with dashboard directory: {self.dashboard_dir}")
            
            # Log system initialization
            self._log_audit_event(
                level=AuditLevel.INFO,
                category=AuditCategory.SYSTEM,
                action="system_initialization",
                status="success",
                resource_id="monitoring_system",
                message="Integrated monitoring system initialized successfully"
            )
    
    def _log_audit_event(self, level, category, action, status, resource_id, message, details=None):
        """Helper method to log audit events with consistent formatting."""
        if not self.audit_logger:
            return
            
        event_id = f"event_{self.event_count}"
        self.event_count += 1
        
        event = AuditEvent(
            event_id=event_id,
            timestamp=datetime.datetime.now().isoformat(),
            level=level,
            category=category,
            action=action,
            status=status,
            user="system",
            resource_id=resource_id,
            resource_type="system_component",
            message=message,
            details=details or {}
        )
        
        self.audit_logger.log_event_obj(event)
        return event_id
    
    def process_rag_query(self, query_text, query_params=None, simulate=True):
        """
        Process a RAG query with comprehensive monitoring.
        
        Args:
            query_text: The query text to process
            query_params: Optional parameters for the query
            simulate: If True, simulate processing instead of actual processing
            
        Returns:
            Query results (or simulated results)
        """
        if not RAG_COMPONENTS_AVAILABLE:
            logger.error("RAG components required but not available")
            return None
            
        # Generate query ID
        query_id = f"query_{self.query_count}"
        self.query_count += 1
        
        # Default parameters if none provided
        if not query_params:
            query_params = {
                "max_depth": 2,
                "traversal": {"max_depth": 2, "relationship_types": ["related_to", "contains"]},
                "max_vector_results": 5,
                "min_similarity": 0.6
            }
            
        # Start query monitoring
        self.query_metrics.start_query_tracking(query_id=query_id, query_params=query_params)
        
        # Log query start event
        self._log_audit_event(
            level=AuditLevel.INFO,
            category=AuditCategory.DATA_ACCESS,
            action="rag_query_start",
            status="in_progress",
            resource_id=f"query_{query_id}",
            message=f"RAG query started: {query_text[:50]}...",
            details={
                "query_id": query_id,
                "query_text": query_text,
                "query_params": query_params
            }
        )
        
        # Process query phases
        if simulate:
            # Simulate query processing with timing
            results = self._simulate_query_processing(query_id, query_params)
        else:
            # Actual query processing would go here
            results = self._process_real_query(query_id, query_text, query_params)
            
        # End query tracking
        self.query_metrics.end_query_tracking(
            query_id=query_id,
            results=results
        )
        
        # Log query completion
        status = "success" if results["quality_score"] > 0.6 else "partial"
        self._log_audit_event(
            level=AuditLevel.INFO,
            category=AuditCategory.DATA_ACCESS,
            action="rag_query_complete",
            status=status,
            resource_id=f"query_{query_id}",
            message=f"RAG query completed with {results['count']} results and quality score {results['quality_score']}",
            details={
                "query_id": query_id,
                "results_count": results["count"],
                "quality_score": results["quality_score"],
                "execution_time": self.query_metrics.get_query_metrics(query_id)["total_duration"]
            }
        )
        
        return results
        
    def _simulate_query_processing(self, query_id, query_params):
        """Simulate the phases of query processing for demonstration."""
        # Simulate vector search phase
        self.query_metrics.start_phase(query_id, "vector_search")
        time.sleep(0.05 + random.random() * 0.1)  # Random delay
        vector_results_count = query_params.get("max_vector_results", 5)
        self.query_metrics.end_phase(
            query_id, 
            "vector_search",
            phase_results={"vector_results": vector_results_count}
        )
        
        # Simulate graph traversal phase
        self.query_metrics.start_phase(query_id, "graph_traversal")
        time.sleep(0.1 + random.random() * 0.15)  # Random delay
        nodes_explored = random.randint(5, 20)
        self.query_metrics.end_phase(
            query_id, 
            "graph_traversal",
            phase_results={"nodes_explored": nodes_explored}
        )
        
        # Simulate result ranking phase
        self.query_metrics.start_phase(query_id, "ranking")
        time.sleep(0.03 + random.random() * 0.05)  # Random delay
        self.query_metrics.end_phase(query_id, "ranking")
        
        # Simulate final results
        results_count = random.randint(3, 10)
        quality_score = 0.5 + random.random() * 0.4
        
        return {
            "count": results_count,
            "quality_score": quality_score,
            "sources": [f"doc_{i}" for i in range(results_count)]
        }
        
    def _process_real_query(self, query_id, query_text, query_params):
        """Process an actual RAG query with the optimizer (if available)."""
        # This is where real query processing would be implemented
        # For now, we'll just delegate to the simulation
        return self._simulate_query_processing(query_id, query_params)
    
    def simulate_security_incident(self, severity="medium", duration_seconds=5):
        """
        Simulate a security incident with corresponding audit events and performance impact.
        
        Args:
            severity: The severity of the incident ("low", "medium", "high")
            duration_seconds: How long the incident lasts in seconds
        """
        if not AUDIT_COMPONENTS_AVAILABLE:
            logger.error("Audit components required but not available")
            return
            
        logger.info(f"Simulating {severity} security incident")
        
        # Map severity to audit level
        level_map = {
            "low": AuditLevel.WARNING,
            "medium": AuditLevel.ERROR,
            "high": AuditLevel.CRITICAL
        }
        audit_level = level_map.get(severity, AuditLevel.ERROR)
        
        # Log initial incident detection
        incident_id = self._log_audit_event(
            level=audit_level,
            category=AuditCategory.SECURITY,
            action="suspicious_activity",
            status="detected",
            resource_id="rag_system",
            message=f"{severity.title()} security incident detected",
            details={
                "severity": severity,
                "detection_time": datetime.datetime.now().isoformat(),
                "incident_type": "anomalous_query_pattern"
            }
        )
        
        # Simulate performance impact if incident is medium or high
        if severity in ["medium", "high"]:
            # Perform some degraded queries
            degradation_factor = 2.0 if severity == "medium" else 4.0
            logger.info(f"Security incident causing {degradation_factor}x query performance degradation")
            
            # Simulate a few degraded queries
            query_count = max(2, int(duration_seconds / 2))
            for i in range(query_count):
                # Start degraded query
                query_id = f"incident_query_{i}"
                self.query_metrics.start_query_tracking(query_id=query_id, query_params={
                    "max_depth": 2,
                    "traversal": {"max_depth": 2},
                    "max_vector_results": 5,
                    "min_similarity": 0.6
                })
                
                # Simulate slow phases
                self.query_metrics.start_phase(query_id, "vector_search")
                time.sleep(0.1 * degradation_factor)
                self.query_metrics.end_phase(query_id, "vector_search")
                
                self.query_metrics.start_phase(query_id, "graph_traversal")
                time.sleep(0.2 * degradation_factor)
                self.query_metrics.end_phase(query_id, "graph_traversal")
                
                # Log timeout or error if high severity
                if severity == "high" and i % 2 == 0:
                    self._log_audit_event(
                        level=AuditLevel.ERROR,
                        category=AuditCategory.SYSTEM,
                        action="query_timeout",
                        status="failure",
                        resource_id=query_id,
                        message=f"Query timed out during security incident",
                        details={
                            "incident_id": incident_id,
                            "query_id": query_id,
                            "timeout_phase": "graph_traversal"
                        }
                    )
                    # Don't end tracking - simulate abandoned query
                else:
                    # End with poor results
                    self.query_metrics.end_query_tracking(
                        query_id=query_id,
                        results={
                            "count": max(1, 5 - i),
                            "quality_score": 0.3 + (i * 0.05),
                            "sources": [f"doc_{j}" for j in range(max(1, 3 - i))]
                        }
                    )
                
                time.sleep(0.5)  # Gap between queries
        
        # Log incident response events
        if severity != "low":
            self._log_audit_event(
                level=AuditLevel.WARNING,
                category=AuditCategory.SECURITY,
                action="mitigation_deployed",
                status="active",
                resource_id="security_system",
                message="Automatic security mitigation deployed",
                details={
                    "incident_id": incident_id,
                    "mitigation_type": "query_rate_limiting",
                    "settings": {"max_queries_per_minute": 10}
                }
            )
        
        # Sleep for the specified duration to simulate the incident timeframe
        time.sleep(duration_seconds)
        
        # Log incident resolution
        self._log_audit_event(
            level=AuditLevel.INFO,
            category=AuditCategory.SECURITY,
            action="incident_resolved",
            status="completed",
            resource_id="rag_system",
            message=f"{severity.title()} security incident resolved",
            details={
                "incident_id": incident_id,
                "resolution_time": datetime.datetime.now().isoformat(),
                "duration_seconds": duration_seconds
            }
        )
        
        logger.info(f"Security incident simulation completed")
    
    def generate_comprehensive_visualizations(self):
        """
        Generate a comprehensive set of visualizations showing the integration
        between RAG query performance and security audit events.
        
        Returns:
            Dictionary of generated visualization file paths
        """
        if not RAG_COMPONENTS_AVAILABLE or not AUDIT_COMPONENTS_AVAILABLE:
            logger.error("Both RAG and audit components required for visualizations")
            return {}
            
        logger.info("Generating comprehensive visualizations")
        
        # Create visualization directory
        vis_dir = os.path.join(self.dashboard_dir, "visualizations")
        os.makedirs(vis_dir, exist_ok=True)
        
        # 1. Create the integrated timeline showing both query performance and audit events
        timeline_path = os.path.join(vis_dir, "integrated_timeline.png")
        self.output_files["static_timeline"] = timeline_path
        
        create_query_audit_timeline(
            query_metrics_collector=self.query_metrics,
            audit_metrics=self.audit_metrics,
            hours_back=1,  # Just look at recent events since this is a short example
            interval_minutes=1,
            theme=self.theme,
            output_file=timeline_path,
            show_plot=False
        )
        
        # 2. Create interactive timeline visualization
        interactive_timeline_path = os.path.join(vis_dir, "interactive_timeline.html")
        self.output_files["interactive_timeline"] = interactive_timeline_path
        
        self.query_visualizer.visualize_query_audit_metrics(
            audit_metrics_aggregator=self.audit_metrics,
            output_file=interactive_timeline_path,
            interactive=True,
            hours_back=1,
            title="Interactive Query Performance & Security Timeline",
            show_plot=False
        )
        
        # 3. Create query performance heatmap
        heatmap_path = os.path.join(vis_dir, "query_phases_heatmap.png")
        self.output_files["phases_heatmap"] = heatmap_path
        
        create_query_performance_heatmap(
            metrics_collector=self.query_metrics,
            output_file=heatmap_path,
            title="Query Phase Duration Heatmap",
            theme=self.theme,
            show_plot=False
        )
        
        # 4. Create security event distribution
        events_by_level_path = os.path.join(vis_dir, "events_by_level.png")
        self.output_files["events_by_level"] = events_by_level_path
        
        self.audit_visualizer.create_events_by_level_chart(
            metrics_aggregator=self.audit_metrics,
            hours_back=1,
            output_file=events_by_level_path,
            title="Security Events by Severity Level",
            show_plot=False
        )
        
        # 5. Create event timeline
        event_timeline_path = os.path.join(vis_dir, "event_timeline.png")
        self.output_files["event_timeline"] = event_timeline_path
        
        self.audit_visualizer.create_event_timeline(
            metrics_aggregator=self.audit_metrics,
            hours_back=1,
            interval_minutes=1,
            output_file=event_timeline_path,
            title="Security Event Timeline",
            show_plot=False
        )
        
        # 6. Generate the complete dashboard
        dashboard_path = os.path.join(self.dashboard_dir, "comprehensive_dashboard.html")
        self.output_files["dashboard"] = dashboard_path
        
        self.dashboard.generate_integrated_dashboard(
            output_file=dashboard_path,
            audit_metrics_aggregator=self.audit_metrics,
            title="Comprehensive RAG Query & Security Dashboard",
            include_performance=True,
            include_security=True,
            include_query_audit_timeline=True,
            interactive=True,
            theme=self.theme
        )
        
        # 7. Generate a summary report
        report_path = os.path.join(self.dashboard_dir, "monitoring_report.html")
        self.output_files["report"] = report_path
        
        self._generate_summary_report(report_path)
        
        logger.info(f"Generated {len(self.output_files)} visualization files")
        return self.output_files
    
    def _generate_summary_report(self, output_path):
        """Generate a summary report of monitoring findings."""
        # Get metrics summaries
        query_stats = self.query_metrics.get_summary_statistics()
        audit_stats = self.audit_metrics.get_event_stats(hours_back=1)
        
        # Detect anomalies
        slow_queries = [
            qid for qid, metrics in self.query_metrics.query_metrics.items()
            if metrics["total_duration"] > 1.0  # Queries taking more than 1 second
        ]
        
        high_severity_events = self.audit_metrics.get_events_by_level(
            hours_back=1,
            levels=[AuditLevel.ERROR, AuditLevel.CRITICAL]
        )
        
        # Create simple HTML report
        with open(output_path, 'w') as f:
            f.write(f"""<!DOCTYPE html>
<html>
<head>
    <title>Monitoring Summary Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; line-height: 1.6; color: #333; }}
        h1, h2, h3 {{ color: #2c3e50; }}
        .summary-box {{ 
            border: 1px solid #ddd; 
            border-radius: 5px; 
            padding: 15px; 
            margin-bottom: 20px; 
            background-color: #f9f9f9; 
        }}
        .warning {{ background-color: #fff3cd; border-color: #ffeeba; }}
        .critical {{ background-color: #f8d7da; border-color: #f5c6cb; }}
        .normal {{ background-color: #d4edda; border-color: #c3e6cb; }}
        table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
        .dashboard-link {{ 
            display: inline-block; 
            margin-top: 20px;
            padding: 10px 15px;
            background-color: #007bff;
            color: white;
            text-decoration: none;
            border-radius: 4px;
        }}
        .dashboard-link:hover {{ background-color: #0056b3; }}
    </style>
</head>
<body>
    <h1>RAG Query and Security Monitoring Report</h1>
    <p>Generated on: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    
    <div class="summary-box {('critical' if high_severity_events else 'normal')}">
        <h2>Executive Summary</h2>
        <p>This report provides an overview of the system's performance and security status.</p>
        <ul>
            <li><strong>Total Queries Processed:</strong> {len(self.query_metrics.query_metrics)}</li>
            <li><strong>Average Query Duration:</strong> {query_stats['average_duration']:.2f} seconds</li>
            <li><strong>Total Security Events:</strong> {len(self.audit_metrics.get_recent_events(hours_back=1))}</li>
            <li><strong>High Severity Events:</strong> {len(high_severity_events)}</li>
            <li><strong>System Status:</strong> {'Incident Detected' if high_severity_events else 'Normal Operation'}</li>
        </ul>
    </div>
    
    <h2>Performance Metrics</h2>
    <div class="summary-box {('warning' if slow_queries else 'normal')}">
        <h3>Query Performance</h3>
        <p>Summary of RAG query performance metrics:</p>
        <ul>
            <li><strong>Fastest Query:</strong> {query_stats['min_duration']:.3f} seconds</li>
            <li><strong>Slowest Query:</strong> {query_stats['max_duration']:.3f} seconds</li>
            <li><strong>Average Quality Score:</strong> {query_stats.get('average_quality_score', 'N/A')}</li>
            <li><strong>Slow Queries Detected:</strong> {len(slow_queries)}</li>
        </ul>
        
        <h4>Query Phase Analysis</h4>
        <table>
            <tr>
                <th>Phase</th>
                <th>Average Duration (sec)</th>
                <th>Max Duration (sec)</th>
            </tr>
            {''.join([f'<tr><td>{phase}</td><td>{stats["avg"]:.3f}</td><td>{stats["max"]:.3f}</td></tr>' 
                     for phase, stats in query_stats.get('phases', {}).items()])}
        </table>
    </div>
    
    <h2>Security Analysis</h2>
    <div class="summary-box {('critical' if high_severity_events else 'normal')}">
        <h3>Security Events</h3>
        <p>Summary of security audit events:</p>
        <ul>
            <li><strong>Total Events:</strong> {len(self.audit_metrics.get_recent_events(hours_back=1))}</li>
            <li><strong>Critical Events:</strong> {len([e for e in high_severity_events if e.level == AuditLevel.CRITICAL])}</li>
            <li><strong>Error Events:</strong> {len([e for e in high_severity_events if e.level == AuditLevel.ERROR])}</li>
            <li><strong>Warning Events:</strong> {len(self.audit_metrics.get_events_by_level(hours_back=1, levels=[AuditLevel.WARNING]))}</li>
        </ul>
        
        {f'''<h4>High Severity Events</h4>
        <table>
            <tr>
                <th>Timestamp</th>
                <th>Level</th>
                <th>Category</th>
                <th>Action</th>
                <th>Message</th>
            </tr>
            {''.join([f'<tr><td>{e.timestamp}</td><td>{e.level.name}</td><td>{e.category.name}</td><td>{e.action}</td><td>{e.message}</td></tr>' 
                     for e in high_severity_events])}
        </table>''' if high_severity_events else ''}
    </div>
    
    <h2>Visual Analysis</h2>
    <p>Explore the interactive dashboard for detailed visual analysis:</p>
    <a href="comprehensive_dashboard.html" class="dashboard-link">Open Interactive Dashboard</a>
    
    <h3>Static Visualizations</h3>
    <ul>
        {''.join([f'<li><a href="visualizations/{os.path.basename(path)}">{name.replace("_", " ").title()}</a></li>' 
                 for name, path in self.output_files.items() if name != 'dashboard' and name != 'report'])}
    </ul>
    
    <hr>
    <p>This report was automatically generated by the Integrated Monitoring System.</p>
</body>
</html>""")
        
        return output_path
        
    def open_dashboard(self):
        """Open the main dashboard in a web browser."""
        dashboard_path = self.output_files.get("dashboard")
        if dashboard_path and os.path.exists(dashboard_path):
            dashboard_url = f"file://{os.path.abspath(dashboard_path)}"
            logger.info(f"Opening dashboard: {dashboard_url}")
            webbrowser.open(dashboard_url)
        else:
            logger.error("Dashboard not found or not generated yet")

def run_comprehensive_example(output_dir=None, run_time=60, theme="light", open_browser=True):
    """
    Run the comprehensive example of integrated RAG query and audit visualization.
    
    Args:
        output_dir: Directory to store outputs (default: temporary directory)
        run_time: How long to run the simulation in seconds
        theme: Dashboard theme ('light' or 'dark')
        open_browser: Whether to open the dashboard in a browser when done
        
    Returns:
        Dictionary of output files
    """
    logger.info("Starting comprehensive RAG query and audit visualization example")
    
    # Initialize the integrated monitoring system
    system = IntegratedMonitoringSystem(output_dir=output_dir, theme=theme)
    
    # Generate some initial normal queries to establish a baseline
    logger.info("Generating baseline performance data")
    for i in range(10):
        system.process_rag_query(
            query_text=f"Baseline query {i}: How does IPFS handle content addressing?",
            simulate=True
        )
        time.sleep(0.5)
    
    # Simulate normal operation with a mix of events
    logger.info("Simulating normal system operation")
    start_time = time.time()
    normal_operation_time = min(20, run_time / 3)
    
    while time.time() - start_time < normal_operation_time:
        # Process a query
        system.process_rag_query(
            query_text=f"Normal operation query: What are the benefits of content addressing?",
            simulate=True
        )
        
        # Small delay between operations
        time.sleep(2)
    
    # Simulate a low-severity security incident
    if time.time() - start_time < run_time:
        logger.info("Simulating low-severity security incident")
        system.simulate_security_incident(severity="low", duration_seconds=5)
        
        # Continue normal operation
        for i in range(5):
            system.process_rag_query(
                query_text=f"Post-incident query {i}: How does IPFS handle network partitions?",
                simulate=True
            )
            time.sleep(1)
    
    # Simulate a medium-severity security incident with performance degradation
    if time.time() - start_time < run_time:
        logger.info("Simulating medium-severity security incident with performance impact")
        system.simulate_security_incident(severity="medium", duration_seconds=10)
        
        # Continue with recovery
        logger.info("Simulating recovery from incident")
        for i in range(5):
            system.process_rag_query(
                query_text=f"Recovery query {i}: Tell me about IPFS clustering",
                simulate=True
            )
            time.sleep(1)
    
    # Simulate a high-severity security incident if we have enough time
    remaining_time = run_time - (time.time() - start_time)
    if remaining_time > 20:
        logger.info("Simulating high-severity security incident")
        system.simulate_security_incident(severity="high", duration_seconds=15)
        
        # Recovery phase
        logger.info("Simulating recovery from major incident")
        for i in range(7):
            system.process_rag_query(
                query_text=f"Major recovery query {i}: Explain libp2p security",
                simulate=True
            )
            time.sleep(1)
    
    # Generate all visualizations
    logger.info("Generating comprehensive visualizations and reports")
    output_files = system.generate_comprehensive_visualizations()
    
    # Open dashboard in browser if requested
    if open_browser:
        system.open_dashboard()
    
    logger.info(f"Example completed successfully in {time.time() - start_time:.1f} seconds")
    return output_files

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run comprehensive RAG and audit visualization example")
    parser.add_argument("--output-dir", type=str, help="Directory to store outputs")
    parser.add_argument("--run-time", type=int, default=60, help="How long to run the simulation in seconds")
    parser.add_argument("--theme", type=str, default="light", choices=["light", "dark"], help="Dashboard theme")
    parser.add_argument("--no-browser", action="store_true", help="Don't open browser automatically")
    
    args = parser.parse_args()
    
    try:
        # Run the example
        output_files = run_comprehensive_example(
            output_dir=args.output_dir,
            run_time=args.run_time,
            theme=args.theme,
            open_browser=not args.no_browser
        )
        
        # Display results
        if output_files:
            print("\nExample completed successfully!")
            print("\nOutput files:")
            for name, path in output_files.items():
                print(f"- {name}: {path}")
            
            if not args.no_browser:
                print("\nOpened dashboard in your browser.")
            else:
                dashboard = output_files.get("dashboard")
                if dashboard:
                    print(f"\nTo view the dashboard manually, open: file://{os.path.abspath(dashboard)}")
        else:
            print("\nExample failed. Please check the logs for more information.")
    except Exception as e:
        logger.error(f"Example failed with error: {str(e)}", exc_info=True)