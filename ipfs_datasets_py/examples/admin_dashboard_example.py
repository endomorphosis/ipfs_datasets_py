"""
Example for the Admin Dashboard.

This example demonstrates how to:
- Configure and start the admin dashboard
- Generate sample metrics and logs
- Simulate operations and nodes
- Connect the dashboard to the monitoring system
"""

import os
import random
import tempfile
import threading
import time
from datetime import datetime

from ipfs_datasets_py.monitoring import (
    configure_monitoring,
    MonitoringConfig,
    LoggerConfig,
    MetricsConfig,
    LogLevel,
    get_logger,
    get_metrics_registry,
    monitor_context,
    timed
)

from ipfs_datasets_py.admin_dashboard import (
    start_dashboard,
    stop_dashboard,
    DashboardConfig
)


class SampleDataGenerator:
    """Generates sample data for the dashboard demonstration."""

    def __init__(self, logger, metrics_registry):
        """Initialize the generator."""
        self.logger = logger
        self.metrics = metrics_registry
        self.running = False
        self.thread = None

    def start(self, interval=1.0):
        """Start generating sample data."""
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(
            target=self._generate_data_loop,
            args=(interval,),
            daemon=True
        )
        self.thread.start()
        self.logger.info("Sample data generator started")

    def stop(self):
        """Stop generating sample data."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        self.logger.info("Sample data generator stopped")

    def _generate_data_loop(self, interval):
        """Generate data in a loop."""
        while self.running:
            try:
                # Generate logs
                self._generate_logs()

                # Generate metrics
                self._generate_metrics()

                # Simulate operations
                self._simulate_operations()

                # Wait for next iteration
                time.sleep(interval)
            except Exception as e:
                self.logger.error(f"Error generating sample data: {str(e)}")

    def _generate_logs(self):
        """Generate sample logs."""
        # Generate different log levels with different probabilities
        level_choices = [
            (self.logger.debug, "Debug message", 0.4),
            (self.logger.info, "Info message", 0.3),
            (self.logger.warning, "Warning message", 0.2),
            (self.logger.error, "Error message", 0.1)
        ]

        for log_fn, prefix, probability in level_choices:
            if random.random() < probability:
                log_fn(f"{prefix} {random.randint(1000, 9999)}: {datetime.now().isoformat()}")

    def _generate_metrics(self):
        """Generate sample metrics."""
        # Simulate CPU load oscillation (sine wave)
        timestamp = time.time()
        cpu_load = 50 + 30 * abs(round(1/0.1 * timestamp) % 20 - 10) / 10  # Oscillates between 20% and 80%
        memory_usage = 40 + 20 * abs(round(1/0.15 * timestamp) % 20 - 10) / 10  # Oscillates between 20% and 60%

        # Record system-like metrics
        self.metrics.gauge("sample_cpu_usage", cpu_load,
                        labels={"source": "sample_generator"})
        self.metrics.gauge("sample_memory_usage", memory_usage,
                         labels={"source": "sample_generator"})

        # Record counter metrics
        self.metrics.increment("sample_requests",
                             labels={"method": random.choice(["GET", "POST", "PUT", "DELETE"])})

        # Record histogram metrics
        self.metrics.histogram("sample_response_time",
                             random.uniform(10, 500),  # 10-500ms
                             labels={"endpoint": random.choice(["/api/data", "/api/user", "/api/auth"])})

        # Record timer metrics
        self.metrics.timer("sample_processing_time",
                         random.uniform(50, 200),  # 50-200ms
                         labels={"process": "data_processing"})

    def _simulate_operations(self):
        """Simulate operations."""
        # With 20% probability, start a new operation
        if random.random() < 0.2:
            # Choose a random operation type
            operation_type = random.choice([
                "data_indexing",
                "vector_search",
                "knowledge_graph_query",
                "dataset_loading",
                "graph_traversal"
            ])

            # Start operation
            with monitor_context(
                operation_name=operation_type,
                entity_count=random.randint(10, 1000),
                dataset_size=f"{random.randint(1, 100)}MB"
            ):
                # Simulate work
                time.sleep(random.uniform(0.1, 0.5))

                # 90% success rate
                if random.random() < 0.9:
                    pass  # Success
                else:
                    # Simulate error
                    error_types = ["TimeoutError", "ConnectionError", "ValidationError", "ResourceNotFound"]
                    raise Exception(f"{random.choice(error_types)}: Operation failed")


@timed
def admin_dashboard_example():
    """
    Example demonstrating the admin dashboard.

    This function:
    1. Configures monitoring with file and console output
    2. Starts the admin dashboard
    3. Generates sample data to populate the dashboard
    4. Waits for the user to close the dashboard
    """
    # Create temporary directory for log and metrics files
    temp_dir = tempfile.mkdtemp(prefix="ipfs_datasets_admin_")
    log_file = os.path.join(temp_dir, "dashboard_example.log")
    metrics_file = os.path.join(temp_dir, "dashboard_metrics.json")

    # Configure monitoring
    monitoring_config = MonitoringConfig(
        enabled=True,
        component_name="admin_dashboard_example",
        environment="demo",
        version="0.1.0",
        logger=LoggerConfig(
            name="ipfs_datasets.admin",
            level=LogLevel.DEBUG,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            file_path=log_file,
            console=True,
            rotate_logs=True,
            include_context=True
        ),
        metrics=MetricsConfig(
            enabled=True,
            collect_interval=5,
            output_file=metrics_file,
            system_metrics=True,
            memory_metrics=True,
            network_metrics=True
        )
    )

    # Initialize monitoring
    configure_monitoring(monitoring_config)
    logger = get_logger()
    metrics = get_metrics_registry()

    try:
        logger.info("Starting admin dashboard example")

        # Configure dashboard
        dashboard_config = DashboardConfig(
            enabled=True,
            host="127.0.0.1",
            port=8888,
            refresh_interval=5,
            open_browser=True,
            data_dir=temp_dir,
            monitoring_config=monitoring_config
        )

        # Start dashboard
        logger.info("Starting admin dashboard")
        dashboard = start_dashboard(dashboard_config)

        # Create and start sample data generator
        logger.info("Starting sample data generator")
        data_generator = SampleDataGenerator(logger, metrics)
        data_generator.start(interval=1.0)

        # Print a message to the console
        print(f"\nAdmin Dashboard Example running!")
        print(f"Dashboard URL: http://{dashboard_config.host}:{dashboard_config.port}")
        print(f"Log file: {log_file}")
        print(f"Metrics file: {metrics_file}")
        print("\nPress Ctrl+C to stop the example...")

        # Keep running until user interrupts
        try:
            # Keep the main thread running
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping example...")
        finally:
            # Stop data generator
            logger.info("Stopping sample data generator")
            data_generator.stop()

            # Stop dashboard
            logger.info("Stopping admin dashboard")
            stop_dashboard()

        print("\nExample completed successfully!")
        print(f"Generated files in: {temp_dir}")
        print(f"To clean up temporary files, run: rm -rf {temp_dir}")

        return {
            "temp_dir": temp_dir,
            "log_file": log_file,
            "metrics_file": metrics_file
        }

    except Exception as e:
        logger.error(f"Error in admin dashboard example: {str(e)}", exc_info=True)
        print(f"\nError: {str(e)}")
        return None


if __name__ == "__main__":
    # Run the example
    admin_dashboard_example()
