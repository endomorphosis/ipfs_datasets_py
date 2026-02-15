"""
Performance Profiling Tools for Processors

Provides utilities for profiling processor performance:
- Context managers for profiling
- Performance metrics collection
- Resource usage tracking
- Bottleneck identification
"""

import time
import psutil
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any
import logging


@dataclass
class ProfileMetrics:
    """Performance metrics for a processing operation."""
    operation_name: str
    start_time: float
    end_time: Optional[float] = None
    duration: Optional[float] = None
    
    # CPU metrics
    cpu_percent_start: Optional[float] = None
    cpu_percent_end: Optional[float] = None
    cpu_percent_avg: Optional[float] = None
    
    # Memory metrics  
    memory_mb_start: Optional[float] = None
    memory_mb_end: Optional[float] = None
    memory_mb_peak: Optional[float] = None
    memory_mb_diff: Optional[float] = None
    
    # I/O metrics
    io_read_bytes: Optional[int] = None
    io_write_bytes: Optional[int] = None
    
    # Custom metrics
    custom_metrics: Dict[str, Any] = field(default_factory=dict)
    
    def finish(self) -> None:
        """Finalize metrics calculation."""
        if self.end_time:
            self.duration = self.end_time - self.start_time
            
            if self.memory_mb_start and self.memory_mb_end:
                self.memory_mb_diff = self.memory_mb_end - self.memory_mb_start
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'operation_name': self.operation_name,
            'duration_seconds': self.duration,
            'cpu_percent_avg': self.cpu_percent_avg,
            'memory_mb_start': self.memory_mb_start,
            'memory_mb_end': self.memory_mb_end,
            'memory_mb_peak': self.memory_mb_peak,
            'memory_mb_diff': self.memory_mb_diff,
            'io_read_mb': self.io_read_bytes / (1024 * 1024) if self.io_read_bytes else None,
            'io_write_mb': self.io_write_bytes / (1024 * 1024) if self.io_write_bytes else None,
            'custom_metrics': self.custom_metrics
        }
    
    def summary(self) -> str:
        """Get human-readable summary."""
        lines = [
            f"Operation: {self.operation_name}",
            f"Duration: {self.duration:.3f}s" if self.duration else "Duration: N/A",
        ]
        
        if self.cpu_percent_avg is not None:
            lines.append(f"CPU Usage: {self.cpu_percent_avg:.1f}%")
        
        if self.memory_mb_diff is not None:
            lines.append(f"Memory Change: {self.memory_mb_diff:+.2f} MB")
        
        if self.memory_mb_peak is not None:
            lines.append(f"Peak Memory: {self.memory_mb_peak:.2f} MB")
        
        return "\n".join(lines)


class ProcessorProfiler:
    """Profiler for processor operations."""
    
    def __init__(self):
        """Initialize profiler."""
        self.process = psutil.Process()
        self.metrics_history: List[ProfileMetrics] = []
        self.logger = logging.getLogger(__name__)
    
    @asynccontextmanager
    async def profile(self, operation_name: str = "processing"):
        """
        Context manager for profiling an operation.
        
        Args:
            operation_name: Name of the operation being profiled
            
        Yields:
            ProfileMetrics object that will be populated
            
        Example:
            ```python
            import anyio
            from ipfs_datasets_py.processors.profiling import ProcessorProfiler
            from ipfs_datasets_py.processors.core import UniversalProcessor
            
            profiler = ProcessorProfiler()
            processor = UniversalProcessor()
            
            async def main():
                async with profiler.profile("pdf_processing") as metrics:
                    result = await processor.process("document.pdf")
                    metrics.custom_metrics['success'] = result.success
                
                print(metrics.summary())
            
            anyio.run(main)
            ```
        """
        # Create metrics object
        metrics = ProfileMetrics(
            operation_name=operation_name,
            start_time=time.time()
        )
        
        # Collect start metrics
        try:
            metrics.cpu_percent_start = self.process.cpu_percent()
            mem_info = self.process.memory_info()
            metrics.memory_mb_start = mem_info.rss / (1024 * 1024)
            
            io_counters = self.process.io_counters()
            io_read_start = io_counters.read_bytes
            io_write_start = io_counters.write_bytes
        except Exception as e:
            self.logger.warning(f"Failed to collect start metrics: {e}")
        
        try:
            # Yield to operation
            yield metrics
        finally:
            # Collect end metrics
            metrics.end_time = time.time()
            
            try:
                metrics.cpu_percent_end = self.process.cpu_percent()
                mem_info = self.process.memory_info()
                metrics.memory_mb_end = mem_info.rss / (1024 * 1024)
                metrics.memory_mb_peak = mem_info.rss / (1024 * 1024)  # Approximate
                
                io_counters = self.process.io_counters()
                metrics.io_read_bytes = io_counters.read_bytes - io_read_start
                metrics.io_write_bytes = io_counters.write_bytes - io_write_start
                
                # Calculate averages
                if metrics.cpu_percent_start is not None and metrics.cpu_percent_end is not None:
                    metrics.cpu_percent_avg = (metrics.cpu_percent_start + metrics.cpu_percent_end) / 2
            except Exception as e:
                self.logger.warning(f"Failed to collect end metrics: {e}")
            
            # Finalize
            metrics.finish()
            
            # Store in history
            self.metrics_history.append(metrics)
            
            # Log summary
            self.logger.info(f"Profile: {metrics.summary()}")
    
    def get_metrics_history(self) -> List[ProfileMetrics]:
        """Get all collected metrics."""
        return self.metrics_history.copy()
    
    def get_average_metrics(self) -> Optional[Dict[str, float]]:
        """
        Get average metrics across all operations.
        
        Returns:
            Dictionary with average metrics or None if no metrics
        """
        if not self.metrics_history:
            return None
        
        # Calculate averages
        total_duration = sum(m.duration for m in self.metrics_history if m.duration)
        avg_duration = total_duration / len(self.metrics_history) if self.metrics_history else 0
        
        cpu_values = [m.cpu_percent_avg for m in self.metrics_history if m.cpu_percent_avg is not None]
        avg_cpu = sum(cpu_values) / len(cpu_values) if cpu_values else 0
        
        memory_diffs = [m.memory_mb_diff for m in self.metrics_history if m.memory_mb_diff is not None]
        avg_memory_diff = sum(memory_diffs) / len(memory_diffs) if memory_diffs else 0
        
        return {
            'count': len(self.metrics_history),
            'avg_duration_seconds': avg_duration,
            'avg_cpu_percent': avg_cpu,
            'avg_memory_diff_mb': avg_memory_diff,
            'total_duration_seconds': total_duration
        }
    
    def clear_history(self) -> None:
        """Clear metrics history."""
        self.metrics_history.clear()
    
    def export_metrics(self, filepath: str) -> None:
        """
        Export metrics to JSON file.
        
        Args:
            filepath: Path to export file
        """
        import json
        
        data = {
            'metrics': [m.to_dict() for m in self.metrics_history],
            'summary': self.get_average_metrics()
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        self.logger.info(f"Exported {len(self.metrics_history)} metrics to {filepath}")


@asynccontextmanager
async def profile_processing(operation_name: str = "processing"):
    """
    Convenience context manager for profiling.
    
    Args:
        operation_name: Name of the operation
        
    Yields:
        ProfileMetrics object
        
    Example:
        ```python
        import anyio
        from ipfs_datasets_py.processors.profiling import profile_processing
        from ipfs_datasets_py.processors.core import UniversalProcessor
        
        async def main():
            processor = UniversalProcessor()
            
            async with profile_processing("batch_processing") as metrics:
                results = await processor.process_batch([
                    "doc1.pdf", "doc2.pdf", "doc3.pdf"
                ], parallel=True)
                metrics.custom_metrics['total_files'] = len(results)
            
            print(metrics.summary())
        
        anyio.run(main)
        ```
    """
    profiler = ProcessorProfiler()
    async with profiler.profile(operation_name) as metrics:
        yield metrics


__all__ = [
    'ProfileMetrics',
    'ProcessorProfiler',
    'profile_processing',
]
