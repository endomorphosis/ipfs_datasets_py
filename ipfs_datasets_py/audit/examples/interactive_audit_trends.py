"""
Interactive Audit Visualization Example

This example demonstrates how to use the interactive visualization capabilities
to create dynamic, interactive charts for audit event analysis. It shows how to
aggregate data by different time periods and filter by various attributes.
"""

import time
import datetime
import random
import os
from ipfs_datasets_py.audit.audit_logger import (
    AuditLogger, AuditEvent, AuditLevel, AuditCategory
)
from ipfs_datasets_py.audit.audit_visualization import (
    AuditMetricsAggregator, create_interactive_audit_trends
)

def generate_sample_audit_events(logger, count=1000, days=30):
    """Generate sample audit events for visualization."""
    categories = [c.name for c in AuditCategory]
    levels = [l.name for l in AuditLevel]
    actions = [
        "login", "logout", "create", "read", "update", "delete", 
        "upload", "download", "search", "query", "configure", "access"
    ]
    users = ["user1", "user2", "user3", "admin1", "admin2", "service_account"]
    statuses = ["success", "failure", "error", "denied", "timeout"]
    resource_types = ["file", "database", "api", "service", "network", "user"]
    
    # Generate events over the past number of days
    now = time.time()
    start_time = now - (days * 86400)
    
    for _ in range(count):
        # Create random timestamp within the specified time period
        event_time = start_time + random.random() * (now - start_time)
        event_datetime = datetime.datetime.fromtimestamp(event_time)
        
        # Generate random event properties
        category = random.choice(categories)
        level = random.choice(levels)
        action = random.choice(actions)
        user = random.choice(users)
        status = random.choice(statuses)
        resource_type = random.choice(resource_types)
        resource_id = f"{resource_type}-{random.randint(1000, 9999)}"
        
        # Add special cases for analysis
        # Create login failures for certain users
        if action == "login" and random.random() < 0.3:
            status = "failure"
            level = "WARNING"
        
        # Make certain resource types have higher error rates
        if resource_type == "api" and random.random() < 0.2:
            status = "error"
            level = "ERROR"
        
        # Create some compliance violations
        compliance_violation = False
        if random.random() < 0.05:
            compliance_violation = True
            requirement_id = f"REQ-{random.randint(100, 999)}"
        
        # Create some performance patterns
        duration_ms = None
        if action in ["query", "search", "download"]:
            base_duration = {"query": 50, "search": 100, "download": 200}[action]
            # Add some variance and occasional spikes
            duration_ms = base_duration * (0.5 + random.random())
            if random.random() < 0.05:  # Occasional performance spike
                duration_ms *= 5
        
        # Create event details
        details = {
            "client_ip": f"192.168.1.{random.randint(1, 255)}",
            "endpoint": f"/{action}/{resource_type}" if random.random() > 0.5 else "/api/v1/data",
            "duration_ms": duration_ms
        }
        
        # Add compliance details if applicable
        if compliance_violation:
            details["compliance_violation"] = True
            details["requirement_id"] = requirement_id
            details["severity"] = random.choice(["low", "medium", "high", "critical"])
        
        # Add some error details for failed events
        if status in ["failure", "error"]:
            details["error"] = random.choice([
                "Permission denied", 
                "Resource not found",
                "Invalid input",
                "Service unavailable",
                "Connection timeout",
                "Authentication failed"
            ])
        
        # Create special patterns: Generate spikes in certain time periods
        hour_of_day = event_datetime.hour
        day_of_week = event_datetime.weekday()
        
        # Business hours have more activity
        if 9 <= hour_of_day <= 17 and 0 <= day_of_week <= 4:
            # Skip this event sometimes to reduce business hours events
            if random.random() < 0.2:
                continue
        
        # Create the event
        event = AuditEvent(
            category=category,
            level=level,
            action=action,
            status=status,
            user=user,
            resource_type=resource_type,
            resource_id=resource_id,
            timestamp=event_datetime.isoformat(),
            details=details
        )
        
        # Log the event
        logger.log_event(event)
    
    return count

def main():
    """Run the interactive audit visualization example."""
    # Create output directory
    output_dir = "audit_visuals"
    os.makedirs(output_dir, exist_ok=True)
    
    # Initialize audit logger and metrics aggregator
    # Use a large window size to keep all events for visualization
    logger = AuditLogger()
    metrics = AuditMetricsAggregator(
        window_size=30 * 86400,  # 30 days
        bucket_size=3600  # 1 hour buckets
    )
    
    # Register metrics collector with logger
    logger.add_handler(lambda event: metrics.process_event(event))
    
    # Generate sample audit events (1000 events over 30 days)
    print("Generating sample audit events...")
    events_count = generate_sample_audit_events(logger, count=1000, days=30)
    print(f"Generated {events_count} sample audit events")
    
    # Create interactive visualizations
    print("Creating interactive visualizations...")
    
    # Create daily trend visualization
    daily_vis = create_interactive_audit_trends(
        metrics_aggregator=metrics,
        period='daily',
        lookback_days=30,
        output_file=os.path.join(output_dir, "audit_trends_daily.html")
    )
    
    # Create hourly trend visualization for the last 7 days
    hourly_vis = create_interactive_audit_trends(
        metrics_aggregator=metrics,
        period='hourly',
        lookback_days=7,
        output_file=os.path.join(output_dir, "audit_trends_hourly.html")
    )
    
    # Create visualization focused on security-related categories
    security_vis = create_interactive_audit_trends(
        metrics_aggregator=metrics,
        period='daily',
        lookback_days=30,
        categories=["AUTHENTICATION", "AUTHORIZATION", "SECURITY"],
        output_file=os.path.join(output_dir, "security_trends.html")
    )
    
    # Create visualization focused on error and critical levels
    error_vis = create_interactive_audit_trends(
        metrics_aggregator=metrics,
        period='daily',
        lookback_days=30,
        levels=["ERROR", "CRITICAL", "EMERGENCY"],
        output_file=os.path.join(output_dir, "error_trends.html")
    )
    
    print(f"Interactive visualizations created in {output_dir}/")
    print("Files generated:")
    print(f"  - {output_dir}/audit_trends_daily.html (Daily audit trends)")
    print(f"  - {output_dir}/audit_trends_hourly.html (Hourly audit trends for last 7 days)")
    print(f"  - {output_dir}/security_trends.html (Security-related events)")
    print(f"  - {output_dir}/error_trends.html (Error-level events)")
    print("\nThese HTML files contain interactive visualizations that can be opened in any web browser.")
    print("They feature time-based filtering, zooming, tooltips, and other interactive elements.")

if __name__ == "__main__":
    main()