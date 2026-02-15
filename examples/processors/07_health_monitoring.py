"""
Health Monitoring Examples
==========================

This example demonstrates health monitoring and status tracking
in UniversalProcessor.
"""

import asyncio
import json
from ipfs_datasets_py.processors import UniversalProcessor
from ipfs_datasets_py.processors.universal_processor import ProcessorConfig
from ipfs_datasets_py.processors.monitoring import HealthStatus


async def example_1_basic_health_check():
    """Example 1: Basic health check."""
    print("\n" + "=" * 70)
    print("Example 1: Basic Health Check")
    print("=" * 70)
    
    config = ProcessorConfig(enable_monitoring=True)
    processor = UniversalProcessor(config)
    
    print("Checking system health...")
    health = processor.check_health()
    
    if health:
        print(f"\n✓ System Status: {health.status.value.upper()}")
        print(f"  - Total processors: {health.processor_count}")
        print(f"  - Healthy: {health.healthy_count}")
        print(f"  - Degraded: {health.degraded_count}")
        print(f"  - Unhealthy: {health.unhealthy_count}")
        print(f"  - Overall success rate: {health.overall_success_rate:.1%}")


async def example_2_health_report_text():
    """Example 2: Text health report."""
    print("\n" + "=" * 70)
    print("Example 2: Health Report (Text Format)")
    print("=" * 70)
    
    config = ProcessorConfig(enable_monitoring=True)
    processor = UniversalProcessor(config)
    
    # Generate text report
    report = processor.get_health_report(format="text")
    print(report)


async def example_3_health_report_json():
    """Example 3: JSON health report."""
    print("\n" + "=" * 70)
    print("Example 3: Health Report (JSON Format)")
    print("=" * 70)
    
    config = ProcessorConfig(enable_monitoring=True)
    processor = UniversalProcessor(config)
    
    # Generate JSON report
    report_json = processor.get_health_report(format="json")
    
    print("JSON output (pretty-printed):")
    print(report_json)
    
    # Parse JSON for programmatic access
    data = json.loads(report_json)
    print(f"\nParsed data:")
    print(f"  System status: {data['status']}")
    print(f"  Processor count: {data['processor_count']}")


async def example_4_health_status_levels():
    """Example 4: Understanding health status levels."""
    print("\n" + "=" * 70)
    print("Example 4: Health Status Levels")
    print("=" * 70)
    
    statuses = [
        (HealthStatus.HEALTHY, "≥95%", "Operating normally"),
        (HealthStatus.DEGRADED, "80-95%", "Some issues, still functional"),
        (HealthStatus.UNHEALTHY, "<80%", "Significant problems"),
        (HealthStatus.UNKNOWN, "N/A", "No data available")
    ]
    
    print("Health status levels:")
    for status, success_rate, description in statuses:
        print(f"\n  {status.value.upper()}:")
        print(f"    Success rate: {success_rate}")
        print(f"    Description: {description}")


async def example_5_monitoring_individual_processors():
    """Example 5: Monitor individual processors."""
    print("\n" + "=" * 70)
    print("Example 5: Individual Processor Monitoring")
    print("=" * 70)
    
    config = ProcessorConfig(enable_monitoring=True)
    processor = UniversalProcessor(config)
    
    # Get system health (includes per-processor health)
    health = processor.check_health()
    
    if health:
        print("Per-processor health:")
        for name, proc_health in health.processor_health.items():
            status_symbol = {
                HealthStatus.HEALTHY: "✓",
                HealthStatus.DEGRADED: "⚠",
                HealthStatus.UNHEALTHY: "✗",
                HealthStatus.UNKNOWN: "?"
            }.get(proc_health.status, "?")
            
            print(f"\n  {status_symbol} {name}:")
            print(f"    Status: {proc_health.status.value}")
            print(f"    Success rate: {proc_health.success_rate:.1%}")
            print(f"    Total calls: {proc_health.total_calls}")
            print(f"    Avg time: {proc_health.avg_processing_time:.2f}s")


async def example_6_alerting_on_unhealthy():
    """Example 6: Alerting on unhealthy processors."""
    print("\n" + "=" * 70)
    print("Example 6: Alerting on Unhealthy Processors")
    print("=" * 70)
    
    config = ProcessorConfig(enable_monitoring=True)
    processor = UniversalProcessor(config)
    
    # Check health
    health = processor.check_health()
    
    if health:
        # Alert if system is unhealthy
        if health.status == HealthStatus.UNHEALTHY:
            print("🚨 ALERT: System is UNHEALTHY!")
            print(f"   {health.unhealthy_count} unhealthy processors detected")
            
            # Get list of unhealthy processors
            # unhealthy = processor._health_monitor.get_unhealthy_processors()
            # for proc in unhealthy:
            #     print(f"   - {proc.name}: {proc.success_rate:.1%} success rate")
        
        elif health.status == HealthStatus.DEGRADED:
            print("⚠ WARNING: System is DEGRADED")
            print(f"   {health.degraded_count} degraded processors")
        
        else:
            print("✓ System is HEALTHY")
    
    print("\nExample alert configuration:")
    print("  • UNHEALTHY: Send PagerDuty alert")
    print("  • DEGRADED: Send Slack notification")
    print("  • HEALTHY: Log only")


async def example_7_periodic_health_checks():
    """Example 7: Periodic health monitoring."""
    print("\n" + "=" * 70)
    print("Example 7: Periodic Health Monitoring")
    print("=" * 70)
    
    config = ProcessorConfig(enable_monitoring=True)
    processor = UniversalProcessor(config)
    
    print("Example: Monitoring health every 5 minutes")
    print("\nPseudo-code:")
    print("""
    async def monitor_health():
        while True:
            health = processor.check_health()
            
            if health.status == HealthStatus.UNHEALTHY:
                send_alert("System unhealthy!")
            
            log_health_metrics(health)
            
            await asyncio.sleep(300)  # 5 minutes
    
    # Run in background
    asyncio.create_task(monitor_health())
    """)
    
    print("Best practices:")
    print("  • Check health every 1-5 minutes in production")
    print("  • Log metrics for historical analysis")
    print("  • Alert on state changes (healthy → degraded)")
    print("  • Track trends over time")


async def example_8_health_dashboard_integration():
    """Example 8: Integrating with monitoring dashboards."""
    print("\n" + "=" * 70)
    print("Example 8: Dashboard Integration")
    print("=" * 70)
    
    print("Integration options:")
    
    print("\n1. Prometheus metrics:")
    print("""
    from prometheus_client import Gauge
    
    # Create metrics
    processor_health = Gauge('processor_health', 
                            'Processor health status',
                            ['processor_name'])
    
    # Update from health check
    health = processor.check_health()
    for name, proc_health in health.processor_health.items():
        status_value = {
            HealthStatus.HEALTHY: 1.0,
            HealthStatus.DEGRADED: 0.5,
            HealthStatus.UNHEALTHY: 0.0,
            HealthStatus.UNKNOWN: -1.0
        }[proc_health.status]
        
        processor_health.labels(processor_name=name).set(status_value)
    """)
    
    print("\n2. Grafana dashboard:")
    print("  • Visualize health status over time")
    print("  • Alert on status changes")
    print("  • Track success rates")
    print("  • Monitor processing times")
    
    print("\n3. Custom logging:")
    print("""
    import logging
    
    health = processor.check_health()
    logging.info('Health check', extra={
        'status': health.status.value,
        'processor_count': health.processor_count,
        'success_rate': health.overall_success_rate
    })
    """)


async def example_9_health_based_routing():
    """Example 9: Health-based routing decisions."""
    print("\n" + "=" * 70)
    print("Example 9: Health-Based Routing")
    print("=" * 70)
    
    print("Use health information for intelligent routing:")
    
    print("\nScenario 1: Skip unhealthy processors")
    print("""
    health = processor.check_health()
    
    # Get list of healthy processors
    healthy_processors = [
        name for name, proc_health in health.processor_health.items()
        if proc_health.is_healthy()
    ]
    
    # Route only to healthy processors
    config.preferred_processors = {
        '*': healthy_processors[0]  # Use first healthy processor
    }
    """)
    
    print("\nScenario 2: Load balancing based on performance")
    print("""
    # Choose processor with best performance
    fastest_processor = min(
        health.processor_health.items(),
        key=lambda x: x[1].avg_processing_time
    )[0]
    
    print(f"Routing to fastest processor: {fastest_processor}")
    """)


async def example_10_continuous_monitoring():
    """Example 10: Production monitoring setup."""
    print("\n" + "=" * 70)
    print("Example 10: Production Monitoring Setup")
    print("=" * 70)
    
    print("Complete monitoring setup:")
    print("""
    # 1. Configure with monitoring enabled
    config = ProcessorConfig(
        enable_monitoring=True,
        circuit_breaker_enabled=True,
        circuit_breaker_threshold=5
    )
    
    processor = UniversalProcessor(config)
    
    # 2. Health check endpoint for k8s/docker
    async def health_endpoint():
        health = processor.check_health()
        if health.status == HealthStatus.HEALTHY:
            return 200, "OK"
        elif health.status == HealthStatus.DEGRADED:
            return 200, "DEGRADED"
        else:
            return 503, "UNHEALTHY"
    
    # 3. Metrics endpoint
    async def metrics_endpoint():
        return processor.get_health_report(format="json")
    
    # 4. Background monitoring
    async def background_monitor():
        while True:
            health = processor.check_health()
            
            # Log to centralized logging
            logger.info("health_check", extra=health.to_dict())
            
            # Send to metrics system
            send_to_datadog(health)
            
            await asyncio.sleep(60)  # Every minute
    
    # 5. Start monitoring
    asyncio.create_task(background_monitor())
    """)
    
    print("\nProduction checklist:")
    print("  ✓ Health check endpoint exposed")
    print("  ✓ Metrics endpoint for monitoring systems")
    print("  ✓ Background health checks every 1-5 minutes")
    print("  ✓ Alerts configured for unhealthy status")
    print("  ✓ Dashboard showing trends")
    print("  ✓ Logging integrated with central logging")


async def main():
    """Run all examples."""
    print("\n")
    print("=" * 70)
    print("HEALTH MONITORING EXAMPLES")
    print("=" * 70)
    
    examples = [
        example_1_basic_health_check,
        example_2_health_report_text,
        example_3_health_report_json,
        example_4_health_status_levels,
        example_5_monitoring_individual_processors,
        example_6_alerting_on_unhealthy,
        example_7_periodic_health_checks,
        example_8_health_dashboard_integration,
        example_9_health_based_routing,
        example_10_continuous_monitoring
    ]
    
    for example in examples:
        await example()
        await asyncio.sleep(0.1)
    
    print("\n" + "=" * 70)
    print("Examples complete!")
    print("=" * 70)
    print("\nKey Takeaways:")
    print("  • Health monitoring is enabled by default")
    print("  • Text and JSON formats available")
    print("  • Three health levels: HEALTHY, DEGRADED, UNHEALTHY")
    print("  • Use for alerting, routing, and dashboards")
    print("  • Integrate with Prometheus, Grafana, Datadog")
    print("  • Essential for production systems")
    print()


if __name__ == "__main__":
    asyncio.run(main())
