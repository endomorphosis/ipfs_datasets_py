"""
Query Metrics Collection and Analysis Module.

This module provides comprehensive metrics collection and analysis capabilities
for GraphRAG query execution. It captures fine-grained timing information, resource
utilization, and effectiveness metrics for each query phase.

Key features:
- Phase-by-phase timing measurements with nested timing support
- Resource utilization tracking (memory, CPU)
- Query plan effectiveness scoring
- Metrics persistence and export capabilities
- Historical trend analysis
- Integration with monitoring systems
"""

from __future__ import annotations

import logging
import time
import json
import os
import csv
import uuid
import datetime
import copy
import math
from io import StringIO
from typing import Dict, List, Any, Optional, Tuple, Iterator
from collections import defaultdict, deque
from contextlib import contextmanager

# Optional dependencies with graceful fallbacks
try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False
    # Provide minimal numpy-like functionality for basic operations
    class MockNumpy:
        @staticmethod
        def array(x):
            return list(x) if hasattr(x, '__iter__') else [x]
        @staticmethod
        def mean(x):
            return sum(x) / len(x) if x else 0
        @staticmethod
        def std(x):
            if not x:
                return 0
            mean_val = sum(x) / len(x)
            variance = sum((val - mean_val) ** 2 for val in x) / len(x)
            return variance ** 0.5
    np = MockNumpy()

try:
    import psutil
    HAVE_PSUTIL = True
except ImportError:
    HAVE_PSUTIL = False
    # Mock psutil for basic functionality
    class MockPsutil:
        @staticmethod
        def virtual_memory():
            return type('Memory', (), {'percent': 50, 'available': 1000000000})()
        @staticmethod
        def cpu_percent():
            return 25.0

        class Process:
            def memory_info(self):
                return type('MemInfo', (), {'rss': 0, 'vms': 0})()

            def cpu_percent(self):
                return 0.0

    psutil = MockPsutil()


class QueryMetricsCollector:
    """
    Collects and analyzes detailed metrics for GraphRAG query execution.
    
    This class provides comprehensive metrics collection and analysis capabilities
    beyond the basic statistics tracked by GraphRAGQueryStats. It captures fine-grained
    timing information, resource utilization, and effectiveness metrics for each query phase.
    
    Key features:
    - Phase-by-phase timing measurements with nested timing support
    - Resource utilization tracking (memory, CPU)
    - Query plan effectiveness scoring
    - Metrics persistence and export capabilities
    - Historical trend analysis
    - Integration with monitoring systems
    """
    
    def __init__(
        self, 
        max_history_size: int = 1000,
        metrics_dir: Optional[str] = None,
        track_resources: bool = True,
        logger: Optional[Any] = None,
    ):
        """
        Initialize the metrics collector.
        
        Args:
            max_history_size (int): Maximum number of query metrics to retain in memory
            metrics_dir (str, optional): Directory to store persisted metrics
            track_resources (bool): Whether to track system resource usage during query execution
            logger: Optional :class:`logging.Logger` to use instead of the
                module-level logger. Useful for dependency injection in tests.
        """
        import logging as _logging
        self._log = logger or _logging.getLogger(__name__)
        
        self.max_history_size = max_history_size
        self.metrics_dir = metrics_dir
        self.track_resources = track_resources
        
        # Initialize metrics storage
        self.query_metrics: deque = deque(maxlen=max_history_size)
        self.current_query: Optional[Dict[str, Any]] = None
        self.active_timers: Dict[str, Tuple[float, int]] = {}  # (start_time, depth)
        self.current_depth = 0
        
        # Resource tracking
        self.track_resource_usage = bool(track_resources and HAVE_PSUTIL and hasattr(psutil, "Process"))
        
        # Ensure metrics directory exists if provided
        if metrics_dir and not os.path.exists(metrics_dir):
            os.makedirs(metrics_dir)
            
    def start_query_tracking(self, query_id: Optional[str] = None, query_params: Optional[Dict[str, Any]] = None) -> str:
        """
        Start tracking a new query execution.
        
        Args:
            query_id (str, optional): Unique identifier for the query
            query_params (Dict, optional): Query parameters
            
        Returns:
            str: The query ID
        """
        # Generate query ID if not provided
        if query_id is None:
            query_id = str(uuid.uuid4())
            
        # Initialize metrics record for this query
        self.current_query = {
            "query_id": query_id,
            "start_time": time.time(),
            "end_time": None,
            "params": query_params or {},
            "phases": {},
            "resources": {
                "initial_memory": psutil.Process().memory_info().rss if self.track_resource_usage else 0,
                "peak_memory": 0,
                "memory_samples": [],
                "cpu_samples": []
            },
            "results": {
                "count": 0,
                "quality_score": 0.0
            },
            "metadata": {}
        }
        
        # Start resource sampling if enabled
        if self.track_resource_usage:
            self._start_resource_sampling()
            
        return query_id
    
    def end_query_tracking(
        self,
        results_count: int = 0,
        quality_score: float = 0.0,
        error_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        End tracking for the current query and record results.
        
        Args:
            results_count (int): Number of results returned
            quality_score (float): Score indicating quality of results (0.0-1.0)
            error_message (str, optional): Error text if execution failed
            
        Returns:
            Dict: The completed metrics record
        """
        if self.current_query is None:
            raise ValueError("No active query to end tracking for. Call start_query_tracking first.")
            
        # Record end time and duration
        self.current_query["end_time"] = time.time()
        self.current_query["duration"] = self.current_query["end_time"] - self.current_query["start_time"]
        
        # Record results info
        self.current_query["results"]["count"] = results_count
        self.current_query["results"]["quality_score"] = quality_score
        
        # Record execution status
        self.current_query["success"] = error_message is None
        self.current_query["error_message"] = error_message

        # Stop resource sampling
        if self.track_resource_usage:
            self._stop_resource_sampling()
            
        # Add metrics to history
        metrics_record = self.current_query.copy()
        self.query_metrics.append(metrics_record)
        
        # Persist metrics if directory is configured
        if self.metrics_dir:
            self._persist_metrics(metrics_record)
            
        # Reset current query state
        completed_metrics = self.current_query
        self.current_query = None
        self.active_timers = {}
        self.current_depth = 0
        
        return completed_metrics

    def get_health_check(self, window_size: int = 100) -> Dict[str, Any]:
        """Return a lightweight health snapshot for optimizer monitoring.

        The snapshot is intentionally endpoint-friendly and includes:
        - current process memory usage (bytes)
        - last session duration (seconds)
        - error rate across the most recent ``window_size`` sessions

        Args:
            window_size (int): Number of most recent sessions to evaluate.

        Returns:
            Dict[str, Any]: Health status payload.
        """
        window = max(1, int(window_size))
        recent_metrics = list(self.query_metrics)[-window:]

        # Last session duration
        last_session_duration = None
        if recent_metrics:
            last_session_duration = recent_metrics[-1].get("duration")

        # Failure/error rate over the recent window
        failures = sum(
            1
            for metric in recent_metrics
            if (not metric.get("success", True)) or bool(metric.get("error_message"))
        )
        error_rate = (failures / len(recent_metrics)) if recent_metrics else 0.0

        # Current process memory usage (best effort)
        memory_usage_bytes = 0
        if HAVE_PSUTIL and hasattr(psutil, "Process"):
            try:
                memory_usage_bytes = int(psutil.Process().memory_info().rss)
            except Exception:
                memory_usage_bytes = 0

        status = "ok"
        if error_rate >= 0.20:
            status = "degraded"

        return {
            "status": status,
            "memory_usage_bytes": memory_usage_bytes,
            "last_session_duration_seconds": last_session_duration,
            "error_rate_last_100": error_rate,
            "evaluated_sessions": len(recent_metrics),
            "window_size": window,
            "timestamp": datetime.datetime.now().isoformat(),
        }
    
    @contextmanager
    def time_phase(self, phase_name: str, metadata: Optional[Dict[str, Any]] = None) -> Iterator[None]:
        """
        Context manager for timing a specific query phase.
        
        Args:
            phase_name (str): Name of the phase to time
            metadata (Dict, optional): Additional metadata for this phase
            
        Yields:
            None
        """
        if self.current_query is None:
            raise ValueError("No active query. Call start_query_tracking first.")
            
        self.start_phase_timer(phase_name, metadata)
        try:
            yield
        finally:
            self.end_phase_timer(phase_name)
            
    def start_phase_timer(self, phase_name: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        Start timing a query execution phase.
        
        Args:
            phase_name (str): Name of the phase to time
            metadata (Dict, optional): Additional metadata for this phase
        """
        if self.current_query is None:
            raise ValueError("No active query. Call start_query_tracking first.")
            
        # Record parent phases to support hierarchical timing
        parent_path = ""
        if self.current_depth > 0:
            active_phases = sorted(
                [(p, d) for p, (_, d) in self.active_timers.items()],
                key=lambda x: x[1]
            )
            if active_phases:
                # Take the phase with the highest depth as parent
                parent_path = active_phases[-1][0]
                
        # Create full phase path
        full_phase_path = f"{parent_path}.{phase_name}" if parent_path else phase_name
        
        # Start the timer
        self.active_timers[full_phase_path] = (time.time(), self.current_depth)
        self.current_depth += 1
        
        # Initialize phase data
        if full_phase_path not in self.current_query["phases"]:
            self.current_query["phases"][full_phase_path] = {
                "start_time": time.time(),
                "end_time": None,
                "duration": 0.0,
                "metadata": metadata or {},
                "count": 0  # For phases that may be called multiple times
            }
        else:
            # Update for repeated phases
            self.current_query["phases"][full_phase_path]["count"] += 1
            if metadata:
                # Merge metadata for repeated phases
                self.current_query["phases"][full_phase_path]["metadata"].update(metadata)
                
    def end_phase_timer(self, phase_name: str) -> float:
        """
        End timing for a query execution phase.
        
        Args:
            phase_name (str): Name of the phase to end
            
        Returns:
            float: Duration of the phase in seconds
        """
        if self.current_query is None:
            raise ValueError("No active query. Call start_query_tracking first.")
            
        # Find the matching active timer
        found_path = None
        for path, (start_time, depth) in self.active_timers.items():
            if path.endswith(phase_name) and depth == self.current_depth - 1:
                found_path = path
                break
                
        if found_path is None:
            raise ValueError(f"No active timer found for phase '{phase_name}'")
            
        # Calculate duration
        end_time = time.time()
        start_time = self.active_timers[found_path][0]
        duration = end_time - start_time
        
        # Update phase data
        self.current_query["phases"][found_path]["end_time"] = end_time
        self.current_query["phases"][found_path]["duration"] += duration  # Accumulate for repeated phases
        
        # Remove from active timers and decrement depth
        del self.active_timers[found_path]
        self.current_depth -= 1
        
        return duration
        
    def record_resource_usage(self) -> Dict[str, float]:
        """
        Record current resource usage for the active query.
        
        Returns:
            Dict: Current resource usage metrics
        """
        if not self.track_resource_usage or self.current_query is None:
            return {}
            
        # Get process stats
        process = psutil.Process()
        memory_info = process.memory_info()
        cpu_percent = process.cpu_percent()
        
        # Record metrics
        metrics = {
            "timestamp": time.time(),
            "memory_rss": memory_info.rss,
            "memory_vms": memory_info.vms,
            "cpu_percent": cpu_percent
        }
        
        # Update peak memory
        if metrics["memory_rss"] > self.current_query["resources"]["peak_memory"]:
            self.current_query["resources"]["peak_memory"] = metrics["memory_rss"]
            
        # Add to samples
        self.current_query["resources"]["memory_samples"].append(
            (metrics["timestamp"], metrics["memory_rss"])
        )
        self.current_query["resources"]["cpu_samples"].append(
            (metrics["timestamp"], metrics["cpu_percent"])
        )
        
        return metrics
        
    def record_additional_metric(self, name: str, value: Any, category: str = "custom") -> None:
        """
        Record an additional custom metric for the current query.
        
        Args:
            name (str): Metric name
            value (Any): Metric value
            category (str): Metric category for organization
        """
        if self.current_query is None:
            raise ValueError("No active query. Call start_query_tracking first.")
            
        # Ensure category exists in metadata
        if category not in self.current_query["metadata"]:
            self.current_query["metadata"][category] = {}
            
        # Record the metric
        self.current_query["metadata"][category][name] = value
        
    def get_query_metrics(self, query_id: str) -> Optional[Dict[str, Any]]:
        """
        Get metrics for a specific query by ID.
        
        Args:
            query_id (str): The query ID
            
        Returns:
            Dict or None: The metrics record if found
        """
        for metrics in self.query_metrics:
            if metrics["query_id"] == query_id:
                return metrics
        return None
        
    def get_recent_metrics(self, count: int = 10) -> List[Dict[str, Any]]:
        """
        Get metrics for the most recent queries.
        
        Args:
            count (int): Maximum number of records to return
            
        Returns:
            List[Dict]: List of recent metrics records
        """
        return list(self.query_metrics)[-count:]
        
    def get_phase_timing_summary(self, query_id: Optional[str] = None) -> Dict[str, Dict[str, float]]:
        """
        Get a summary of phase timing statistics.
        
        Args:
            query_id (str, optional): Specific query ID, or None for all queries
            
        Returns:
            Dict: Phase timing statistics
        """
        # Collect phase stats across queries
        phase_stats: Dict[str, Dict[str, List[float]]] = defaultdict(
            lambda: {"durations": [], "counts": []}
        )
        
        if query_id is not None:
            # Process single query
            metrics = self.get_query_metrics(query_id)
            if metrics is None:
                return {}
            
            for phase, data in metrics["phases"].items():
                phase_stats[phase]["durations"].append(data["duration"])
                phase_stats[phase]["counts"].append(data.get("count", 1))
        else:
            # Process all queries
            for metrics in self.query_metrics:
                for phase, data in metrics["phases"].items():
                    phase_stats[phase]["durations"].append(data["duration"])
                    phase_stats[phase]["counts"].append(data.get("count", 1))
        
        # Calculate summary statistics
        summary = {}
        for phase, stats in phase_stats.items():
            durations = stats["durations"]
            counts = stats["counts"]
            
            if not durations:
                continue
                
            summary[phase] = {
                "avg_duration": sum(durations) / len(durations),
                "min_duration": min(durations),
                "max_duration": max(durations),
                "total_duration": sum(durations),
                "call_count": sum(counts),
                "avg_calls_per_query": sum(counts) / len(counts)
            }
            
        return summary
        
    def generate_performance_report(self, query_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate a comprehensive performance report.
        
        Args:
            query_id (str, optional): Specific query ID, or None for all queries
            
        Returns:
            Dict: Performance report
        """
        report = {
            "timestamp": datetime.datetime.now().isoformat(),
            "query_count": len(self.query_metrics),
            "timing_summary": {},
            "resource_usage": {},
            "phase_breakdown": {},
            "recommendations": []
        }
        
        # Get metrics to analyze
        metrics_to_analyze = []
        if query_id is not None:
            metrics = self.get_query_metrics(query_id)
            if metrics is not None:
                metrics_to_analyze = [metrics]
        else:
            metrics_to_analyze = list(self.query_metrics)
        
        if not metrics_to_analyze:
            return report
            
        # Calculate overall timing statistics
        durations = [m["duration"] for m in metrics_to_analyze if "duration" in m]
        if durations:
            report["timing_summary"] = {
                "avg_duration": sum(durations) / len(durations),
                "min_duration": min(durations),
                "max_duration": max(durations),
                "total_duration": sum(durations),
                "std_deviation": np.std(durations) if len(durations) > 1 else 0.0
            }
            
        # Calculate resource usage statistics
        peak_memories = [m["resources"]["peak_memory"] for m in metrics_to_analyze 
                         if "resources" in m and "peak_memory" in m["resources"]]
        if peak_memories:
            report["resource_usage"] = {
                "avg_peak_memory": sum(peak_memories) / len(peak_memories),
                "max_peak_memory": max(peak_memories),
                "min_peak_memory": min(peak_memories)
            }
            
        # Get phase breakdown
        report["phase_breakdown"] = self.get_phase_timing_summary(query_id)
        
        # Generate recommendations based on metrics
        if report["phase_breakdown"]:
            # Find the most time-consuming phases
            sorted_phases = sorted(
                [(p, d["avg_duration"]) for p, d in report["phase_breakdown"].items()],
                key=lambda x: x[1],
                reverse=True
            )
            
            if sorted_phases:
                # Recommend optimizing the most expensive phase
                most_expensive_phase = sorted_phases[0]
                if most_expensive_phase[1] > 0.5:  # If more than 500ms
                    report["recommendations"].append({
                        "type": "optimization",
                        "severity": "high" if most_expensive_phase[1] > 1.0 else "medium",
                        "message": f"Optimize the '{most_expensive_phase[0]}' phase which takes {most_expensive_phase[1]:.2f}s on average"
                    })
                    
                # Check for high deviation in timing
                if report["timing_summary"].get("std_deviation", 0) > report["timing_summary"].get("avg_duration", 0) * 0.5:
                    report["recommendations"].append({
                        "type": "consistency",
                        "severity": "medium",
                        "message": "High variability in query execution times detected. Consider implementing more predictable traversal strategies."
                    })
                    
                # Check for resource issues
                if report["resource_usage"].get("avg_peak_memory", 0) > 500 * 1024 * 1024:  # 500MB
                    report["recommendations"].append({
                        "type": "resource",
                        "severity": "high",
                        "message": "High memory usage detected. Consider implementing memory-efficient traversal or pagination."
                    })
        
        return report
        
    def export_metrics_csv(self, filepath: Optional[str] = None) -> Optional[str]:
        """
        Export collected metrics to CSV format.
        
        Args:
            filepath (str, optional): Path to save the CSV file, or None to return as string
            
        Returns:
            str or None: CSV content as string if filepath is None
        """
        if not self.query_metrics:
            return None
            
        # Prepare CSV content
        output = StringIO()
        fieldnames = [
            "query_id", "start_time", "end_time", "duration", 
            "results_count", "quality_score", "peak_memory"
        ]
        
        # Add phase names as columns
        for metrics in self.query_metrics:
            for phase in metrics["phases"].keys():
                if phase not in fieldnames:
                    fieldnames.append(f"phase_{phase}")
        
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        
        # Write each query metrics row
        for metrics in self.query_metrics:
            row = {
                "query_id": metrics["query_id"],
                "start_time": metrics["start_time"],
                "end_time": metrics["end_time"],
                "duration": metrics.get("duration", 0.0),
                "results_count": metrics["results"]["count"],
                "quality_score": metrics["results"]["quality_score"],
                "peak_memory": metrics["resources"].get("peak_memory", 0)
            }
            
            # Add phase durations
            for phase, data in metrics["phases"].items():
                row[f"phase_{phase}"] = data["duration"]
                
            writer.writerow(row)
            
        # Return CSV content or save to file
        if filepath:
            with open(filepath, 'w', newline='') as f:
                f.write(output.getvalue())
            return None
        return output.getvalue()
    
    def export_metrics_json(self, filepath: Optional[str] = None) -> Optional[str]:
        """
        Export collected metrics to JSON format, handling NumPy arrays properly.
        
        Args:
            filepath (str, optional): Path to save the JSON file, or None to return as string
            
        Returns:
            str or None: JSON content as string if filepath is None
        """
        if not self.query_metrics:
            return None
        
        try:    
            # Convert to JSON-serializable format, first apply numpy handling
            metrics_list = self._numpy_json_serializable(list(self.query_metrics))
            
            # Export to file or return as string
            if filepath:
                with open(filepath, 'w') as f:
                    # Use standard json.dump without custom encoder since data is already processed
                    json.dump(metrics_list, f, indent=2)
                return None
            
            # Return as string
            return json.dumps(metrics_list, indent=2)
        except Exception as e:
            # Handle serialization errors gracefully
            error_message = f"Error serializing metrics to JSON: {str(e)}"
            
            # Create a simplified version with just error information
            fallback_metrics = {
                "error": error_message,
                "metrics_count": len(self.query_metrics) if self.query_metrics else 0,
                "timestamp": datetime.datetime.now().isoformat()
            }
            
            if filepath:
                with open(filepath, 'w') as f:
                    json.dump(fallback_metrics, f, indent=2)
                return None
                
            return json.dumps(fallback_metrics, indent=2)
        
    def _start_resource_sampling(self) -> None:
        """Start periodic resource usage sampling."""
        # Initial sampling
        self.record_resource_usage()
    
    def _stop_resource_sampling(self) -> None:
        """Stop resource usage sampling and finalize metrics."""
        # Final sampling
        self.record_resource_usage()
        
    def _numpy_json_serializable(self, obj):
        """
        Convert numpy arrays and types to JSON serializable Python types.
        This enhanced version handles nested structures and all numpy types.
        
        Args:
            obj: Any object to make JSON serializable
            
        Returns:
            JSON serializable version of the object
        """
        # First try to import numpy, but don't fail if not available
        try:
            import numpy as np
            NUMPY_AVAILABLE = True
        except ImportError:
            NUMPY_AVAILABLE = False
        
        # Handle None type
        if obj is None:
            return None
            
        # Recursively process dictionaries
        if isinstance(obj, dict):
            try:
                return {str(k): self._numpy_json_serializable(v) for k, v in obj.items()}
            except Exception as e:
                # Handle any errors in dictionary processing
                return {"error_processing_dict": str(e)}
            
        # Recursively process lists and tuples
        if isinstance(obj, (list, tuple)):
            try:
                return [self._numpy_json_serializable(item) for item in obj]
            except Exception as e:
                # Fall back to string representation if iteration fails
                return str(obj)
            
        # Convert sets to lists
        if isinstance(obj, set):
            try:
                return [self._numpy_json_serializable(item) for item in obj]
            except Exception as e:
                return list(str(item) for item in obj)
        
        # Handle datetime objects
        if isinstance(obj, (datetime.datetime, datetime.date, datetime.time)):
            return obj.isoformat()
            
        # Handle more Python types that may cause issues
        if isinstance(obj, (bytes, bytearray)):
            try:
                return obj.decode('utf-8', errors='replace')
            except:
                return str(obj)
                
        # If numpy is available, handle numpy types
        if NUMPY_AVAILABLE:
            import numpy as np
            
            # Handle numpy array
            if isinstance(obj, np.ndarray):
                try:
                    if obj.size == 0:
                        # Handle empty arrays
                        return []
                    elif obj.ndim == 0:
                        # Handle scalar arrays
                        return self._numpy_json_serializable(obj.item())
                    elif obj.ndim == 1 and obj.size <= 1000:
                        # Handle 1D arrays (with size limit to prevent memory issues)
                        return [self._numpy_json_serializable(x) for x in obj.tolist()]
                    else:
                        # For larger arrays, include shape information but limit data
                        shape_str = 'x'.join(str(dim) for dim in obj.shape)
                        if obj.size <= 100:
                            # Still show small multi-dimensional arrays
                            return {
                                "type": "ndarray",
                                "shape": shape_str,
                                "dtype": str(obj.dtype),
                                "data": [self._numpy_json_serializable(x) for x in obj.flatten().tolist()[:100]]
                            }
                        else:
                            # Just show metadata for large arrays
                            return {
                                "type": "ndarray",
                                "shape": shape_str,
                                "dtype": str(obj.dtype),
                                "size": obj.size,
                                "summary": f"<NumPy array: {shape_str}, {str(obj.dtype)}>"
                            }
                except Exception as e:
                    # Fallback for any array processing errors
                    try:
                        return {
                            "type": "ndarray",
                            "error": str(e),
                            "summary": str(obj)[:1000] if hasattr(obj, "__str__") else "<unprintable array>"
                        }
                    except:
                        return {"type": "ndarray", "error": "Unprocessable array"}
            
            # Handle numpy scalar types
            if isinstance(obj, np.integer):
                return int(obj)
            elif isinstance(obj, np.floating):
                if np.isnan(obj) or np.isinf(obj):
                    return str(obj)  # Handle NaN and Inf values
                return float(obj)
            elif isinstance(obj, np.bool_):
                return bool(obj)
            elif isinstance(obj, np.str_):
                return str(obj)
            elif isinstance(obj, (np.bytes_, np.void)):
                try:
                    return obj.item().decode('utf-8', errors='replace')
                except:
                    return str(obj)
            elif isinstance(obj, (np.datetime64, np.timedelta64)):
                return str(obj)
            elif isinstance(obj, np.complex128):
                return {"real": float(obj.real), "imag": float(obj.imag)}
            
            # Handle other numpy types with item method
            elif hasattr(obj, 'item') and callable(obj.item):
                try:
                    item_val = obj.item()
                    # Handle potential nested numpy types from item()
                    return self._numpy_json_serializable(item_val)
                except:
                    return str(obj)
        
        # For other types that might cause problems, convert to string
        try:
            # Try normal serialization first
            json.dumps(obj)
            return obj
        except (TypeError, OverflowError, ValueError):
            # If normal serialization fails, convert to string
            try:
                return str(obj)
            except:
                return "<unserializable object>"
    
    def _persist_metrics(self, metrics: Dict[str, Any]) -> None:
        """
        Persist metrics record to the configured directory.
        
        Args:
            metrics (Dict): The metrics record to persist
        """
        if not self.metrics_dir:
            return
            
        # Create a filename with timestamp and query ID
        timestamp = datetime.datetime.fromtimestamp(metrics["start_time"]).strftime("%Y%m%d-%H%M%S")
        filename = f"query_{timestamp}_{metrics['query_id']}.json"
        filepath = os.path.join(self.metrics_dir, filename)
        
        try:
            # First apply numpy handling
            serializable_metrics = self._numpy_json_serializable(metrics)
            
            # Write metrics to file
            with open(filepath, 'w') as f:
                json.dump(serializable_metrics, f, indent=2)
        except Exception as e:
            # Handle serialization errors gracefully
            error_message = f"Error serializing metrics to JSON: {str(e)}"
            
            # Create a simplified version with just error information
            fallback_metrics = {
                "error": error_message,
                "query_id": metrics.get("query_id", "unknown"),
                "timestamp": datetime.datetime.now().isoformat()
            }
            
            # Try to save the fallback metrics
            try:
                with open(filepath, 'w') as f:
                    json.dump(fallback_metrics, f, indent=2)
            except:
                # Last resort: just log the error
                if hasattr(self, "_log") and self._log:
                    self._log.error(f"Failed to persist metrics: {error_message}")
