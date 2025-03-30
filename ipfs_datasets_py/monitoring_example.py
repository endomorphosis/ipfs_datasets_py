"""
Example for the Monitoring and Metrics Collection System.

This example demonstrates the core functionality of the monitoring system including:
- Configuring the monitoring system
- Using structured logging with context
- Collecting and reporting various types of metrics
- Tracking operation performance
- Using decorators for timing functions
- Exporting metrics
"""

import os
import time
import random
import asyncio
import tempfile
from typing import Dict, List, Optional
from pathlib import Path

from ipfs_datasets_py.monitoring import (
    configure_monitoring, 
    MonitoringConfig, 
    LoggerConfig, 
    LogLevel, 
    MetricsConfig,
    get_logger, 
    get_metrics_registry, 
    log_context, 
    monitor_context, 
    timed
)


class ExampleDataProcessor:
    """Example class demonstrating monitoring integration."""
    
    def __init__(self, name: str):
        """Initialize with a name."""
        self.name = name
        self.logger = get_logger(name)
        self.metrics = get_metrics_registry()
        self.processed_count = 0
    
    @timed
    def process_batch(self, batch_id: str, items: List[Dict]) -> int:
        """Process a batch of items."""
        self.logger.info(f"Processing batch {batch_id} with {len(items)} items")
        
        # Start batch operation
        with monitor_context(operation_name="batch_processing", 
                            batch_id=batch_id, 
                            item_count=len(items)):
            
            # Record batch size
            self.metrics.gauge("batch_size", len(items), 
                              labels={"processor": self.name, "batch_id": batch_id})
            
            # Process each item
            processed = 0
            errors = 0
            
            for i, item in enumerate(items):
                try:
                    # Simulate processing time
                    time.sleep(random.uniform(0.01, 0.05))
                    
                    # Simulate occasional errors
                    if random.random() < 0.1:
                        raise ValueError(f"Error processing item {i}")
                    
                    # Process succeeded
                    processed += 1
                    
                    # Record item processing
                    with log_context(item_id=item.get("id", i)):
                        self.logger.debug(f"Processed item {i} successfully")
                
                except Exception as e:
                    errors += 1
                    self.logger.warning(f"Failed to process item {i}: {str(e)}")
                    # Record error metric
                    self.metrics.increment("processing_errors", 
                                         labels={"processor": self.name, "batch_id": batch_id})
            
            # Update processed count
            self.processed_count += processed
            
            # Record processing metrics
            self.metrics.increment("items_processed", processed, 
                                  labels={"processor": self.name, "batch_id": batch_id})
            
            # Record batch completion
            self.logger.info(f"Completed batch {batch_id}: {processed} processed, {errors} errors")
            
            return processed
    
    @timed
    async def async_process_batch(self, batch_id: str, items: List[Dict]) -> int:
        """Process a batch of items asynchronously."""
        self.logger.info(f"Async processing batch {batch_id} with {len(items)} items")
        
        # Record batch size
        self.metrics.gauge("async_batch_size", len(items), 
                         labels={"processor": self.name, "batch_id": batch_id})
        
        # Process items concurrently in chunks
        processed = 0
        chunk_size = max(1, len(items) // 5)
        
        for i in range(0, len(items), chunk_size):
            chunk = items[i:i+chunk_size]
            chunk_id = f"{batch_id}_{i//chunk_size}"
            
            with log_context(chunk_id=chunk_id):
                self.logger.debug(f"Processing chunk {chunk_id} with {len(chunk)} items")
                
                # Simulate concurrent processing
                tasks = []
                for j, item in enumerate(chunk):
                    # Create task for each item
                    tasks.append(self._process_item_async(item, f"{chunk_id}_{j}"))
                
                # Wait for all tasks to complete
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Count successful results
                for result in results:
                    if isinstance(result, Exception):
                        self.metrics.increment("async_processing_errors", 
                                             labels={"processor": self.name, "batch_id": batch_id})
                    else:
                        processed += 1
        
        # Record completion metrics
        self.metrics.increment("async_items_processed", processed, 
                             labels={"processor": self.name, "batch_id": batch_id})
        
        self.logger.info(f"Completed async batch {batch_id}: {processed} processed")
        return processed
    
    async def _process_item_async(self, item: Dict, item_id: str) -> bool:
        """Process a single item asynchronously."""
        try:
            # Simulate processing time
            await asyncio.sleep(random.uniform(0.05, 0.2))
            
            # Simulate occasional errors
            if random.random() < 0.1:
                raise ValueError(f"Error processing async item {item_id}")
            
            return True
        except Exception as e:
            self.logger.warning(f"Failed to process async item {item_id}: {str(e)}")
            raise
    
    def generate_report(self) -> Dict:
        """Generate a report of processing metrics."""
        self.logger.info(f"Generating report for {self.name}")
        
        # Record report generation as an event
        self.metrics.event("report_generated", 
                         data={"processor": self.name, "timestamp": time.time()})
        
        return {
            "processor": self.name,
            "processed_count": self.processed_count,
            "timestamp": time.time()
        }


def configure_example_monitoring() -> str:
    """Configure monitoring with example settings."""
    # Create temporary directory for monitoring files
    temp_dir = tempfile.mkdtemp(prefix="ipfs_datasets_monitoring_")
    
    # Create log and metrics file paths
    log_file = os.path.join(temp_dir, "example.log")
    metrics_file = os.path.join(temp_dir, "example_metrics.json")
    
    # Configure monitoring
    config = MonitoringConfig(
        enabled=True,
        component_name="ipfs_datasets_example",
        environment="demo",
        version="0.1.0",
        logger=LoggerConfig(
            name="ipfs_datasets.example",
            level=LogLevel.DEBUG,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            file_path=log_file,
            console=True,
            rotate_logs=True,
            max_file_size=1_048_576,  # 1MB
            backup_count=3,
            include_context=True
        ),
        metrics=MetricsConfig(
            enabled=True,
            collect_interval=10,  # Collect system metrics every 10 seconds
            output_file=metrics_file,
            system_metrics=True,
            memory_metrics=True,
            network_metrics=True,
            global_labels={
                "application": "monitoring_example"
            }
        )
    )
    
    # Initialize the monitoring system
    configure_monitoring(config)
    
    # Return the temp directory for cleanup later
    return temp_dir


async def run_async_example():
    """Run an asynchronous example."""
    processor = ExampleDataProcessor("async_processor")
    
    # Generate sample data
    batches = []
    for i in range(3):
        items = [{"id": f"item_{i}_{j}", "value": random.random()} for j in range(20)]
        batches.append((f"batch_{i}", items))
    
    # Process batches
    for batch_id, items in batches:
        await processor.async_process_batch(batch_id, items)
    
    # Generate report
    return processor.generate_report()


@timed(metric_name="monitoring_example")
def monitoring_example():
    """
    Example demonstrating the monitoring system functionality.
    
    This function shows:
    1. Configuring the monitoring system
    2. Using structured logging with context
    3. Recording various types of metrics
    4. Tracking operations
    5. Timing function execution
    6. Exporting metrics
    """
    # Configure monitoring
    temp_dir = configure_example_monitoring()
    logger = get_logger()
    metrics = get_metrics_registry()
    
    try:
        logger.info("Starting monitoring example")
        
        # Record application start
        metrics.event("application_start", data={"timestamp": time.time()})
        
        # Create processor
        processor = ExampleDataProcessor("example_processor")
        
        # Generate sample data
        batches = []
        for i in range(5):
            batch_size = random.randint(10, 50)
            items = [{"id": f"item_{i}_{j}", "value": random.random()} for j in range(batch_size)]
            batches.append((f"batch_{i}", items))
        
        # Process batches
        total_processed = 0
        
        with monitor_context(operation_name="full_processing", batch_count=len(batches)):
            for batch_id, items in batches:
                processed = processor.process_batch(batch_id, items)
                total_processed += processed
                
                # Add some random extra metrics
                metrics.gauge("processing_progress", 
                            total_processed / sum(len(items) for _, items in batches) * 100,
                            labels={"stage": "batch_processing"})
                
                # Simulate thinking
                time.sleep(0.1)
        
        # Run async example
        logger.info("Starting async processing example")
        asyncio.run(run_async_example())
        
        # Generate report
        report = processor.generate_report()
        logger.info(f"Processing report: {report}")
        
        # Write metrics to file
        metrics.write_metrics()
        
        # Log files generated
        log_path = os.path.join(temp_dir, "example.log")
        metrics_path = os.path.join(temp_dir, "example_metrics.json")
        
        logger.info(f"Example completed. Files created:")
        logger.info(f" - Log file: {log_path}")
        logger.info(f" - Metrics file: {metrics_path}")
        
        print(f"\nMonitoring example completed successfully!")
        print(f"Log file: {log_path}")
        print(f"Metrics file: {metrics_path}")
        
        return {
            "temp_dir": temp_dir,
            "log_file": log_path,
            "metrics_file": metrics_path,
            "processed_count": total_processed
        }
    
    except Exception as e:
        logger.error(f"Error in monitoring example: {str(e)}", exc_info=True)
        raise
    finally:
        # Keep files for inspection, but print a cleanup message
        print(f"\nTo clean up temporary files, run: rm -rf {temp_dir}")


if __name__ == "__main__":
    # Run the example
    monitoring_example()