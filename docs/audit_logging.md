# Audit Logging and Adaptive Security System

The IPFS Datasets Python library includes a comprehensive audit logging and adaptive security system that provides detailed tracking of all operations performed on datasets, with particular emphasis on security, compliance, and data lineage, along with automated responses to detected security threats.

## Overview

The audit logging and adaptive security system is designed to:

1. Record all significant operations on datasets and system components
2. Provide detailed context for each operation, including who, what, when, and how
3. Enable compliance with regulations and internal policies
4. Integrate with data provenance tracking for complete lineage information
5. Support security monitoring and intrusion detection
6. Enable cryptographic verification of audit records
7. Automatically respond to detected security threats with configurable actions
8. Enforce security policies through automated responses
9. Provide comprehensive security response lifecycle management
10. Support visualization and integration with RAG query performance metrics

## Core Components

### AuditLogger

The central component that records and manages audit events:

```python
from ipfs_datasets_py.audit.audit_logger import AuditLogger, AuditLevel, AuditCategory

# Get the singleton instance
audit_logger = AuditLogger.get_instance()

# Log an audit event
event_id = audit_logger.log(
    level=AuditLevel.INFO,
    category=AuditCategory.DATA_MODIFICATION,
    action="dataset_transform",
    resource_id="example_dataset",
    resource_type="dataset",
    details={
        "transformation": "normalization",
        "parameters": {"method": "z-score"}
    }
)
```

### AuditEvent

A comprehensive data structure capturing all relevant information about an operation:

```python
from ipfs_datasets_py.audit.audit_logger import AuditEvent

# Create an audit event
event = AuditEvent(
    event_id="evt_123456",
    timestamp="2023-06-01T12:34:56.789Z",
    level=AuditLevel.WARNING,
    category=AuditCategory.SECURITY,
    action="excessive_access_attempts",
    status="detected",
    user="user_123",
    resource_id="dataset_456",
    resource_type="dataset",
    source_ip="192.168.1.100",
    message="Detected multiple failed access attempts",
    details={
        "attempts": 5,
        "time_window": "5m",
        "access_type": "read"
    }
)

# Log the event
audit_logger.log_event_obj(event)
```

### AuditMetricsAggregator

Collects and aggregates audit events for analysis and visualization:

```python
from ipfs_datasets_py.audit.audit_visualization import AuditMetricsAggregator

# Create metrics aggregator
metrics = AuditMetricsAggregator()

# Register with logger
audit_logger.add_handler(metrics.process_event)

# Get metrics after some events have been processed
summary = metrics.get_metrics_summary()
print(f"Total events: {summary['total_events']}")
print(f"Events by level: {summary['by_level']}")
print(f"Events by category: {summary['by_category']}")
```

### AuditVisualizer

Creates visualizations of audit metrics for monitoring and analysis:

```python
from ipfs_datasets_py.audit.audit_visualization import AuditVisualizer

# Create visualizer
visualizer = AuditVisualizer(metrics)

# Generate timeline visualization
visualizer.create_timeline_visualization(
    hours_back=24,
    output_file="audit_timeline.png"
)

# Generate category breakdown
visualizer.create_category_visualization(
    output_file="audit_categories.png"
)

# Generate event level breakdown 
visualizer.create_level_visualization(
    output_file="audit_levels.png"
)
```

### AdaptiveSecurity

Implements automated security responses based on detected events:

```python
from ipfs_datasets_py.audit.adaptive_security import AdaptiveSecurity

# Initialize adaptive security system
security = AdaptiveSecurity()

# Register with logger
audit_logger.add_handler(security.process_event)

# Configure response rules
security.add_rule(
    category=AuditCategory.SECURITY,
    action="unauthorized_access",
    min_level=AuditLevel.WARNING,
    response="block_ip",
    parameters={"duration": "1h"}
)

security.add_rule(
    category=AuditCategory.AUTHENTICATION,
    action="login_failed",
    min_level=AuditLevel.INFO,
    min_count=5,
    time_window="10m",
    response="escalate_event",
    parameters={"new_level": AuditLevel.WARNING}
)
```

### AuditEnhancedCompliance

Manages compliance with regulations and standards, generating reports and enforcing rules:

```python
from ipfs_datasets_py.audit.compliance import AuditEnhancedCompliance

# Initialize compliance system
compliance = AuditEnhancedCompliance()

# Register with logger
audit_logger.add_handler(compliance.process_event)

# Configure compliance frameworks
compliance.add_framework(
    name="GDPR",
    requirements={
        "data_access": {
            "require_logging": True,
            "retention_period": "30d"
        },
        "data_modification": {
            "require_approval": True,
            "require_logging": True
        }
    }
)

# Generate compliance report
report = compliance.generate_report(
    framework="GDPR",
    time_period="last_30d"
)
```

## Audit Integration with RAG Query Metrics

The audit system integrates with RAG (Retrieval Augmented Generation) query metrics to provide comprehensive monitoring of both security events and performance metrics.

### Integrated Visualization

Create combined visualizations showing both audit events and query performance:

```python
from ipfs_datasets_py.audit.audit_visualization import create_query_audit_timeline
from ipfs_datasets_py.rag.rag_query_visualization import QueryMetricsCollector

# Initialize metrics collectors
query_metrics = QueryMetricsCollector()
audit_metrics = AuditMetricsAggregator()

# Register audit metrics collector with logger
audit_logger.add_handler(audit_metrics.process_event)

# After collecting some data...

# Create combined timeline visualization
create_query_audit_timeline(
    query_metrics_collector=query_metrics,
    audit_metrics=audit_metrics,
    hours_back=24,
    output_file="query_audit_timeline.png"
)
```

### Comprehensive Dashboard

Generate interactive dashboards with both security and performance metrics:

```python
from ipfs_datasets_py.rag.rag_query_visualization import RAGQueryDashboard

# Create dashboard
dashboard = RAGQueryDashboard(
    metrics_collector=query_metrics,
    audit_metrics=audit_metrics
)

# Generate comprehensive dashboard
dashboard.generate_integrated_dashboard(
    output_file="integrated_dashboard.html",
    title="System Performance & Security Dashboard",
    include_performance=True,
    include_security=True,
    include_query_audit_timeline=True,
    interactive=True,
    theme='light'
)
```

## Security Event Detection and Analysis

The system provides tools for detecting and analyzing security anomalies:

```python
from ipfs_datasets_py.audit.intrusion import AuditIntrusionDetection

# Initialize intrusion detection
intrusion = AuditIntrusionDetection()

# Register with logger
audit_logger.add_handler(intrusion.process_event)

# Configure detection rules
intrusion.add_detection_rule(
    name="brute_force_attempt",
    pattern={
        "category": AuditCategory.AUTHENTICATION,
        "action": "login_failed",
        "min_count": 5,
        "time_window": "5m",
        "group_by": ["source_ip", "user"]
    },
    severity=AuditLevel.WARNING
)

# Get detected anomalies
anomalies = intrusion.get_detected_anomalies(time_period="last_hour")
```

## Additional Features

### Audit Data Persistence

Store audit data for long-term retention and analysis:

```python
from ipfs_datasets_py.audit.audit_logger import FileAuditHandler, IPFSAuditHandler

# Add file storage handler
audit_logger.add_handler(
    FileAuditHandler(
        directory="/path/to/audit/logs",
        rotation="daily"
    )
)

# Add IPFS storage handler for immutable, tamper-resistant storage
audit_logger.add_handler(
    IPFSAuditHandler(
        ipfs_client=ipfs_client,
        enable_encryption=True,
        encryption_key=encryption_key
    )
)
```

### Integration with Data Provenance

Link audit events with data provenance information:

```python
from ipfs_datasets_py.audit.integration import AuditProvenanceIntegrator
from ipfs_datasets_py.data_provenance import ProvenanceManager

# Initialize provenance manager
provenance = ProvenanceManager()

# Create integrator
integrator = AuditProvenanceIntegrator(
    audit_logger=audit_logger,
    provenance_manager=provenance
)

# Enable automatic linking of audit events to provenance records
integrator.enable_auto_linking()

# Manually link an audit event to a provenance record
integrator.link_event_to_provenance(
    audit_event_id="evt_123456",
    provenance_record_id="prov_789012"
)
```

### Cryptographic Verification

Ensure the integrity of audit records with cryptographic signing:

```python
from ipfs_datasets_py.audit.audit_logger import AuditCryptoHandler

# Add cryptographic handler
crypto_handler = AuditCryptoHandler(
    private_key_path="/path/to/private_key.pem"
)
audit_logger.add_handler(crypto_handler)

# Verify the integrity of an audit event
is_valid = crypto_handler.verify_event(event)
```

### Contextual Logging

Include rich context with audit events:

```python
# Create a context manager for audit operations
with audit_logger.context(
    operation="data_export",
    resource_id="dataset_456",
    resource_type="dataset"
) as ctx:
    # All audit events within this context will include the operation and resource information
    audit_logger.log(
        level=AuditLevel.INFO,
        category=AuditCategory.DATA_ACCESS,
        action="export_started"
    )
    
    # Perform export operation
    export_data()
    
    # Add more audit events with the same context
    audit_logger.log(
        level=AuditLevel.INFO,
        category=AuditCategory.DATA_ACCESS,
        action="export_completed",
        details={
            "records_exported": 1000,
            "format": "parquet"
        }
    )
```

## Best Practices

1. **Consistent Event Structure**: Use consistent event categories, actions, and levels to simplify analysis and visualization.

2. **Contextual Information**: Always include sufficient context with each event to understand what happened and why.

3. **Real-time Monitoring**: Set up handlers to process events in real-time for immediate detection of security issues.

4. **Compliance Mapping**: Map your audit events to compliance requirements to simplify reporting.

5. **Retention Policy**: Establish a retention policy for audit data based on regulatory requirements and operational needs.

6. **Integration**: Integrate audit logging with data provenance, security systems, and performance monitoring for a comprehensive view of system operation.

7. **Dashboard Monitoring**: Use the integrated dashboards to monitor both performance and security metrics in a unified view.

## Example Workflows

### Basic Integration Workflow

Below is a simple example showing integration of audit logging, performance metrics, and visualization:

```python
from ipfs_datasets_py.audit.audit_logger import AuditLogger, AuditLevel, AuditCategory
from ipfs_datasets_py.audit.audit_visualization import AuditMetricsAggregator, AuditVisualizer
from ipfs_datasets_py.rag.rag_query_visualization import QueryMetricsCollector, RAGQueryDashboard
from ipfs_datasets_py.rag.rag_query_optimizer import UnifiedGraphRAGQueryOptimizer

# Initialize components
audit_logger = AuditLogger.get_instance()
audit_metrics = AuditMetricsAggregator()
query_metrics = QueryMetricsCollector()
query_optimizer = UnifiedGraphRAGQueryOptimizer(metrics_collector=query_metrics)
dashboard = RAGQueryDashboard(metrics_collector=query_metrics, audit_metrics=audit_metrics)

# Register audit metrics collector with logger
audit_logger.add_handler(audit_metrics.process_event)

# Enable integration between query metrics and audit system
from ipfs_datasets_py.rag.rag_query_visualization import integrate_with_audit_system
integrate_with_audit_system(
    query_metrics=query_metrics,
    audit_alert_manager=None,  # Optional alert manager
    audit_logger=audit_logger
)

# Example query operation with audit logging
with audit_logger.context(
    operation="knowledge_graph_query",
    resource_id="wikipedia_dataset",
    resource_type="knowledge_graph"
):
    # Log query start
    audit_logger.log(
        level=AuditLevel.INFO,
        category=AuditCategory.DATA_ACCESS,
        action="graph_query_started",
        details={
            "query_text": "What is the relationship between IPFS and libp2p?",
            "query_type": "relationship"
        }
    )
    
    # Execute query (simulated)
    query_id = "q123456"
    query_params = {
        "query_text": "What is the relationship between IPFS and libp2p?",
        "max_depth": 2,
        "max_results": 10
    }
    
    # Record query metrics
    query_metrics.record_query_start(query_id, query_params)
    
    # Simulate query execution
    import time
    time.sleep(0.5)  # Simulate processing time
    
    # Record query completion
    query_metrics.record_query_end(
        query_id=query_id,
        results=[{"text": "IPFS uses libp2p for all network communications", "score": 0.95}],
        metrics={
            "vector_search_time": 0.2,
            "graph_traversal_time": 0.25,
            "result_count": 5
        }
    )
    
    # Log query completion
    audit_logger.log(
        level=AuditLevel.INFO,
        category=AuditCategory.DATA_ACCESS,
        action="graph_query_completed",
        status="success",
        details={
            "results_count": 5,
            "execution_time": 0.5
        }
    )

# Generate visualizations
dashboard.generate_integrated_dashboard(
    output_file="knowledge_graph_dashboard.html",
    title="Knowledge Graph Query Performance & Security",
    include_performance=True,
    include_security=True,
    include_query_audit_timeline=True,
    interactive=True
)

print("Dashboard generated: knowledge_graph_dashboard.html")
```

### Comprehensive Monitoring System

For production environments, we recommend using the `IntegratedMonitoringSystem` class, which provides a complete solution for monitoring both performance and security aspects of RAG systems. See the following example:

```python
from ipfs_datasets_py.audit.audit_logger import AuditLogger, AuditEvent, AuditLevel, AuditCategory
from ipfs_datasets_py.audit.audit_visualization import AuditMetricsAggregator, AuditVisualizer
from ipfs_datasets_py.rag.rag_query_optimizer import QueryMetricsCollector, UnifiedGraphRAGQueryOptimizer
from ipfs_datasets_py.rag.rag_query_visualization import RAGQueryDashboard, EnhancedQueryVisualizer

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
        self.query_metrics = QueryMetricsCollector()
        self.query_optimizer = UnifiedGraphRAGQueryOptimizer()
        self.audit_logger = AuditLogger.get_instance()
        self.audit_metrics = AuditMetricsAggregator()
        
        # Set up visualization components
        self.query_visualizer = EnhancedQueryVisualizer(
            metrics_collector=self.query_metrics,
            theme=theme
        )
        
        self.audit_visualizer = AuditVisualizer(
            theme=theme
        )
        
        self.dashboard = RAGQueryDashboard(
            metrics_collector=self.query_metrics,
            dashboard_dir=self.dashboard_dir,
            theme=theme
        )
        
        # Set up handlers
        self.audit_logger.add_handler(self.audit_metrics.process_event)
        
        # Log system initialization
        self._log_audit_event(
            level=AuditLevel.INFO,
            category=AuditCategory.SYSTEM,
            action="system_initialization",
            status="success",
            resource_id="monitoring_system",
            message="Integrated monitoring system initialized successfully"
        )
    
    def process_rag_query(self, query_text, query_params=None):
        """
        Process a RAG query with comprehensive monitoring.
        
        Args:
            query_text: The query text to process
            query_params: Optional parameters for the query
            
        Returns:
            Query results
        """
        # Generate query ID
        query_id = f"query_{uuid.uuid4()}"
        
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
        
        # Process the query (real implementation would go here)
        # For now, just simulate the processing
        
        # Simulate vector search phase
        self.query_metrics.start_phase(query_id, "vector_search")
        time.sleep(0.1)  # Simulate processing
        self.query_metrics.end_phase(query_id, "vector_search")
        
        # Simulate graph traversal phase
        self.query_metrics.start_phase(query_id, "graph_traversal")
        time.sleep(0.2)  # Simulate processing
        self.query_metrics.end_phase(query_id, "graph_traversal")
        
        # Simulate result ranking
        self.query_metrics.start_phase(query_id, "ranking")
        time.sleep(0.05)  # Simulate processing
        self.query_metrics.end_phase(query_id, "ranking")
        
        # Simulate results
        results = {
            "count": 5,
            "quality_score": 0.85,
            "sources": [f"doc_{i}" for i in range(5)]
        }
        
        # End query tracking
        self.query_metrics.end_query_tracking(
            query_id=query_id,
            results=results
        )
        
        # Log query completion
        self._log_audit_event(
            level=AuditLevel.INFO,
            category=AuditCategory.DATA_ACCESS,
            action="rag_query_complete",
            status="success",
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
    
    def _log_audit_event(self, level, category, action, status, resource_id, message, details=None):
        """Helper method to log audit events with consistent formatting."""
        event_id = str(uuid.uuid4())
        
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
    
    def generate_dashboard(self):
        """
        Generate a comprehensive dashboard with all visualizations.
        
        Returns:
            Path to the generated dashboard HTML file
        """
        dashboard_path = os.path.join(self.dashboard_dir, "comprehensive_dashboard.html")
        
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
        
        return dashboard_path
```

For a complete implementation of the Integrated Monitoring System with advanced features like security incident simulation, report generation, and visualization, see the example script in `examples/rag_audit_integration_example.py`.

This example demonstrates:
- Setting up a comprehensive monitoring system for both performance and security
- Processing RAG queries with detailed metrics collection
- Security incident simulation with performance impact analysis
- Generating interactive dashboards and reports
- Best practices for production deployments