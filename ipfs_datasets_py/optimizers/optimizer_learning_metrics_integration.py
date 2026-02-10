"""
Integration of OptimizerLearningMetricsCollector with GraphRAGQueryOptimizer.

This module provides the necessary code to integrate the OptimizerLearningMetricsCollector
with the GraphRAGQueryOptimizer to track, visualize, and analyze learning metrics.
"""

import time
import logging
import contextlib
from typing import Dict, List, Any, Optional, Generator

from ipfs_datasets_py.optimizers.optimizer_learning_metrics import OptimizerLearningMetricsCollector

# Setup logging
logger = logging.getLogger(__name__)

class MetricsCollectorAdapter:
    """
    Adapter that combines query metrics collection with learning metrics collection.

    This adapter ensures backward compatibility with existing code that expects
    specific methods on the metrics collector, while also providing access to
    learning metrics functionality.
    """

    def __init__(
        self,
        query_metrics_collector=None,
        learning_metrics_collector: Optional[OptimizerLearningMetricsCollector] = None,
        metrics_dir: Optional[str] = None
    ):
        """
        Initialize the metrics collector adapter.

        Args:
            query_metrics_collector: Existing metrics collector for query metrics
            learning_metrics_collector: Collector for learning metrics
            metrics_dir: Directory to store metrics data
        """
        self.query_metrics_collector = query_metrics_collector
        self.learning_metrics_collector = learning_metrics_collector or OptimizerLearningMetricsCollector(metrics_dir=metrics_dir)
        self.metrics_dir = metrics_dir

        # Initialize default properties to ensure backward compatibility
        self.query_metrics = {}
        self.current_query = None

    def start_query_tracking(self, query_params: Dict[str, Any]) -> str:
        """
        Start tracking a query execution.

        Args:
            query_params: Parameters of the query to track

        Returns:
            str: Unique identifier for the query
        """
        if self.query_metrics_collector and hasattr(self.query_metrics_collector, 'start_query_tracking'):
            return self.query_metrics_collector.start_query_tracking(query_params)

        # Basic implementation if real collector not available
        import uuid
        query_id = str(uuid.uuid4())
        self.query_metrics[query_id] = {
            'start_time': time.time(),
            'query_params': query_params,
            'status': 'running',
            'phases': {}
        }
        self.current_query = query_id
        return query_id

    def end_query_tracking(self, results_count: int = 0, quality_score: float = 0.0, error: str = None) -> None:
        """
        End tracking for the current query.

        Args:
            results_count: Number of results returned
            quality_score: Quality score for the results (0.0-1.0)
            error: Error message if the query failed
        """
        if self.query_metrics_collector and hasattr(self.query_metrics_collector, 'end_query_tracking'):
            self.query_metrics_collector.end_query_tracking(
                results_count=results_count,
                quality_score=quality_score,
                error=error
            )
            return

        # Basic implementation if real collector not available
        if self.current_query and self.current_query in self.query_metrics:
            self.query_metrics[self.current_query].update({
                'end_time': time.time(),
                'duration': time.time() - self.query_metrics[self.current_query]['start_time'],
                'results_count': results_count,
                'quality_score': quality_score,
                'status': 'error' if error else 'completed',
                'error': error
            })

    @contextlib.contextmanager
    def time_phase(self, phase_name: str, metadata: Dict[str, Any] = None) -> Generator[None, None, None]:
        """
        Context manager to time a phase of query execution.

        Args:
            phase_name: Name of the phase to time
            metadata: Additional metadata about the phase

        Yields:
            None
        """
        if self.query_metrics_collector and hasattr(self.query_metrics_collector, 'time_phase'):
            with self.query_metrics_collector.time_phase(phase_name, metadata):
                yield
            return

        # Basic implementation if real collector not available
        start_time = time.time()
        try:
            yield
        finally:
            duration = time.time() - start_time
            if self.current_query and self.current_query in self.query_metrics:
                phases = self.query_metrics[self.current_query].setdefault('phases', {})
                phases[phase_name] = {
                    'start_time': start_time,
                    'end_time': time.time(),
                    'duration': duration,
                    'metadata': metadata or {}
                }

    def record_additional_metric(self, name: str, value: Any, category: str = "custom") -> None:
        """
        Record an additional metric that is not tied to a specific query phase.

        Args:
            name: Name of the metric
            value: Value of the metric
            category: Category of the metric
        """
        if self.query_metrics_collector and hasattr(self.query_metrics_collector, 'record_additional_metric'):
            self.query_metrics_collector.record_additional_metric(name, value, category)

        # Record learning-related metrics in the learning metrics collector
        if category in ["learning", "statistical_learning"] and self.learning_metrics_collector:
            # Convert certain events to learning metrics
            if name == "learning_cycle_triggered" and isinstance(value, str):
                # Extract query count if available
                import re
                match = re.search(r"After (\d+) queries", value)
                if match:
                    analyzed_queries = int(match.group(1))
                else:
                    analyzed_queries = 0

                # Record a preliminary learning cycle that will be updated later
                self.learning_metrics_collector.record_learning_cycle(
                    cycle_id=f"cycle-{int(time.time())}",
                    analyzed_queries=analyzed_queries,
                    patterns_identified=0,
                    parameters_adjusted={},
                    execution_time=0.0
                )

    def get_query_metrics(self, query_id: str = None) -> Dict[str, Any]:
        """
        Get metrics for a specific query.

        Args:
            query_id: ID of the query to get metrics for, or None for current query

        Returns:
            Dict: Query metrics
        """
        if self.query_metrics_collector and hasattr(self.query_metrics_collector, 'get_query_metrics'):
            return self.query_metrics_collector.get_query_metrics(query_id)

        # Basic implementation if real collector not available
        query_id = query_id or self.current_query
        return self.query_metrics.get(query_id, {})

    def get_recent_metrics(self, count: int = 10) -> List[Dict[str, Any]]:
        """
        Get metrics for the most recent queries.

        Args:
            count: Number of recent queries to get metrics for

        Returns:
            List[Dict]: List of query metrics
        """
        if self.query_metrics_collector and hasattr(self.query_metrics_collector, 'get_recent_metrics'):
            return self.query_metrics_collector.get_recent_metrics(count)

        # Basic implementation if real collector not available
        sorted_metrics = sorted(
            self.query_metrics.values(),
            key=lambda x: x.get('start_time', 0),
            reverse=True
        )
        return sorted_metrics[:count]

    def get_phase_timing_summary(self, query_id: str = None) -> Dict[str, float]:
        """
        Get a summary of phase timings for a query.

        Args:
            query_id: ID of the query to get timings for, or None for current query

        Returns:
            Dict: Phase timing summary
        """
        if self.query_metrics_collector and hasattr(self.query_metrics_collector, 'get_phase_timing_summary'):
            return self.query_metrics_collector.get_phase_timing_summary(query_id)

        # Basic implementation if real collector not available
        query_metrics = self.get_query_metrics(query_id)
        phases = query_metrics.get('phases', {})
        return {
            phase: data.get('duration', 0.0)
            for phase, data in phases.items()
        }

    def export_metrics_csv(self, output_file: str = None) -> str:
        """
        Export metrics to a CSV file.

        Args:
            output_file: Path to output file, or None to use default

        Returns:
            str: Path to the exported file
        """
        if self.query_metrics_collector and hasattr(self.query_metrics_collector, 'export_metrics_csv'):
            return self.query_metrics_collector.export_metrics_csv(output_file)

        # Basic implementation if real collector not available
        import csv
        output_file = output_file or f"query_metrics_{int(time.time())}.csv"

        try:
            with open(output_file, 'w', newline='') as csvfile:
                fieldnames = ['query_id', 'start_time', 'duration', 'status', 'results_count', 'quality_score']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                writer.writeheader()
                for query_id, metrics in self.query_metrics.items():
                    writer.writerow({
                        'query_id': query_id,
                        'start_time': metrics.get('start_time', ''),
                        'duration': metrics.get('duration', ''),
                        'status': metrics.get('status', ''),
                        'results_count': metrics.get('results_count', ''),
                        'quality_score': metrics.get('quality_score', '')
                    })

            return output_file
        except Exception as e:
            logger.error(f"Error exporting metrics to CSV: {str(e)}")
            return None

    def generate_performance_report(self, output_file: str = None) -> str:
        """
        Generate a performance report.

        Args:
            output_file: Path to output file, or None to use default

        Returns:
            str: Path to the report file
        """
        if self.query_metrics_collector and hasattr(self.query_metrics_collector, 'generate_performance_report'):
            return self.query_metrics_collector.generate_performance_report(output_file)

        # Basic implementation if real collector not available
        output_file = output_file or f"performance_report_{int(time.time())}.txt"

        try:
            with open(output_file, 'w') as f:
                f.write("Performance Report\n")
                f.write("=================\n\n")

                f.write(f"Total Queries: {len(self.query_metrics)}\n")

                # Calculate statistics
                total_duration = sum(m.get('duration', 0) for m in self.query_metrics.values() if 'duration' in m)
                avg_duration = total_duration / len(self.query_metrics) if self.query_metrics else 0

                completed = sum(1 for m in self.query_metrics.values() if m.get('status') == 'completed')
                error = sum(1 for m in self.query_metrics.values() if m.get('status') == 'error')

                f.write(f"Average Duration: {avg_duration:.3f} seconds\n")
                f.write(f"Completed Queries: {completed}\n")
                f.write(f"Error Queries: {error}\n")

                # Phase timings
                phase_timings = {}
                for metrics in self.query_metrics.values():
                    for phase, data in metrics.get('phases', {}).items():
                        if phase not in phase_timings:
                            phase_timings[phase] = []
                        phase_timings[phase].append(data.get('duration', 0))

                if phase_timings:
                    f.write("\nPhase Timings:\n")
                    for phase, timings in phase_timings.items():
                        avg_timing = sum(timings) / len(timings)
                        f.write(f"  {phase}: {avg_timing:.3f} seconds (avg)\n")

            return output_file
        except Exception as e:
            logger.error(f"Error generating performance report: {str(e)}")
            return None

    def record_learning_cycle(self, cycle_id: str, analyzed_queries: int, patterns_identified: int,
                             parameters_adjusted: Dict[str, Any], execution_time: float) -> None:
        """
        Record metrics from a learning cycle.

        Args:
            cycle_id: Unique identifier for the learning cycle
            analyzed_queries: Number of queries analyzed in this cycle
            patterns_identified: Number of patterns identified in this cycle
            parameters_adjusted: Parameters that were adjusted
            execution_time: Time taken to execute the learning cycle
        """
        if self.learning_metrics_collector:
            self.learning_metrics_collector.record_learning_cycle(
                cycle_id=cycle_id,
                analyzed_queries=analyzed_queries,
                patterns_identified=patterns_identified,
                parameters_adjusted=parameters_adjusted,
                execution_time=execution_time
            )

    def record_parameter_adaptation(self, parameter_name: str, old_value: Any, new_value: Any,
                                  adaptation_reason: str, confidence: float) -> None:
        """
        Record a parameter adaptation.

        Args:
            parameter_name: Name of the parameter that was adapted
            old_value: Previous value of the parameter
            new_value: New value of the parameter
            adaptation_reason: Reason for the adaptation
            confidence: Confidence level for the adaptation
        """
        if self.learning_metrics_collector:
            self.learning_metrics_collector.record_parameter_adaptation(
                parameter_name=parameter_name,
                old_value=old_value,
                new_value=new_value,
                adaptation_reason=adaptation_reason,
                confidence=confidence
            )

    def record_strategy_effectiveness(self, strategy_name: str, query_type: str,
                                   effectiveness_score: float, execution_time: float,
                                   result_count: int) -> None:
        """
        Record the effectiveness of a search strategy.

        Args:
            strategy_name: Name of the strategy
            query_type: Type of query the strategy was applied to
            effectiveness_score: Score indicating how effective the strategy was
            execution_time: Time taken to execute the strategy
            result_count: Number of results returned
        """
        if self.learning_metrics_collector:
            self.learning_metrics_collector.record_strategy_effectiveness(
                strategy_name=strategy_name,
                query_type=query_type,
                effectiveness_score=effectiveness_score,
                execution_time=execution_time,
                result_count=result_count
            )

    def record_query_pattern(self, pattern_id: str, pattern_type: str, matching_queries: int,
                          average_performance: float, parameters: Dict[str, Any]) -> None:
        """
        Record a query pattern.

        Args:
            pattern_id: Unique identifier for the pattern
            pattern_type: Type of pattern
            matching_queries: Number of queries matching this pattern
            average_performance: Average performance metric for this pattern
            parameters: Parameters associated with this pattern
        """
        if self.learning_metrics_collector:
            self.learning_metrics_collector.record_query_pattern(
                pattern_id=pattern_id,
                pattern_type=pattern_type,
                matching_queries=matching_queries,
                average_performance=average_performance,
                parameters=parameters
            )

    def get_learning_metrics(self):
        """
        Get aggregated learning metrics.

        Returns:
            LearningMetrics: Object containing aggregated metrics
        """
        if self.learning_metrics_collector:
            return self.learning_metrics_collector.get_learning_metrics()
        return None

    def create_learning_dashboard(self, output_file=None, interactive=True):
        """
        Create a dashboard for learning metrics.

        Args:
            output_file: Path to save the dashboard HTML file
            interactive: Whether to create an interactive dashboard

        Returns:
            str: Path to the generated dashboard file
        """
        if self.learning_metrics_collector:
            if interactive:
                return self.learning_metrics_collector.create_interactive_learning_dashboard(output_file)
            else:
                # Generate individual visualizations
                import os

                output_dir = os.path.dirname(output_file) if output_file else ""
                base_name = os.path.splitext(os.path.basename(output_file))[0] if output_file else "learning_metrics"

                self.learning_metrics_collector.visualize_learning_cycles(
                    output_file=os.path.join(output_dir, f"{base_name}_cycles.png")
                )

                self.learning_metrics_collector.visualize_parameter_adaptations(
                    output_file=os.path.join(output_dir, f"{base_name}_params.png")
                )

                self.learning_metrics_collector.visualize_strategy_effectiveness(
                    output_file=os.path.join(output_dir, f"{base_name}_strategies.png")
                )

                self.learning_metrics_collector.visualize_learning_performance(
                    output_file=os.path.join(output_dir, f"{base_name}_performance.png")
                )

                return os.path.join(output_dir, f"{base_name}_cycles.png")

        return None


def enhance_optimizer_with_learning_metrics(optimizer, metrics_dir=None):
    """
    Enhance an existing GraphRAGQueryOptimizer with learning metrics collection.

    This function adds learning metrics collection capabilities to an existing
    optimizer without changing its interface, ensuring backward compatibility.

    Args:
        optimizer: The GraphRAGQueryOptimizer instance to enhance
        metrics_dir: Directory to store metrics data

    Returns:
        The enhanced optimizer
    """
    # Initialize learning metrics collector
    learning_metrics_collector = OptimizerLearningMetricsCollector(metrics_dir=metrics_dir)

    # Create adapter with existing metrics collector (if any) and learning metrics collector
    metrics_adapter = MetricsCollectorAdapter(
        query_metrics_collector=getattr(optimizer, 'metrics_collector', None),
        learning_metrics_collector=learning_metrics_collector,
        metrics_dir=metrics_dir
    )

    # Replace metrics collector with adapter
    optimizer.metrics_collector = metrics_adapter

    # Add reference to learning metrics collector directly
    optimizer.learning_metrics_collector = learning_metrics_collector

    # Instrument _learn_from_query_statistics method if it exists
    if hasattr(optimizer, '_learn_from_query_statistics'):
        original_learn = optimizer._learn_from_query_statistics

        def instrumented_learn_from_query_statistics(self, recent_queries_count=50):
            """Instrumented version of _learn_from_query_statistics."""
            # Record start time for performance tracking
            start_time = time.time()
            cycle_id = f"cycle-{int(start_time)}"

            # Call original method
            result = original_learn(self, recent_queries_count)

            # Record learning cycle metrics
            if hasattr(self, 'metrics_collector'):
                try:
                    # Extract data from result
                    analyzed_queries = result.get('analyzed_queries', 0)
                    patterns_identified = result.get('patterns_count', 0)
                    parameters_adjusted = result.get('parameter_changes', {})

                    # Record learning cycle
                    self.metrics_collector.record_learning_cycle(
                        cycle_id=cycle_id,
                        analyzed_queries=analyzed_queries,
                        patterns_identified=patterns_identified,
                        parameters_adjusted=parameters_adjusted,
                        execution_time=time.time() - start_time
                    )
                except Exception as e:
                    logger.error(f"Error recording learning cycle: {str(e)}")

            return result

        # Bind the new method to the optimizer instance
        import types
        optimizer._learn_from_query_statistics = types.MethodType(
            instrumented_learn_from_query_statistics, optimizer
        )

    # Return the enhanced optimizer
    return optimizer


def create_optimizer_with_learning_metrics(**kwargs):
    """
    Create a new GraphRAGQueryOptimizer with learning metrics collection.

    This function creates a new optimizer instance with learning metrics
    collection capabilities.

    Args:
        **kwargs: Arguments to pass to the GraphRAGQueryOptimizer constructor

    Returns:
        A new GraphRAGQueryOptimizer instance with learning metrics collection
    """
    # Import the real optimizer class
    try:
        from ipfs_datasets_py.optimizers.graphrag.query_optimizer import UnifiedGraphRAGQueryOptimizer
    except ImportError:
        logger.error("Failed to import GraphRAGQueryOptimizer. Make sure it's available.")
        return None

    # Extract metrics_dir from kwargs
    metrics_dir = kwargs.pop('metrics_dir', None)

    # Create the optimizer
    optimizer = UnifiedGraphRAGQueryOptimizer(**kwargs)

    # Enhance it with learning metrics collection
    return enhance_optimizer_with_learning_metrics(optimizer, metrics_dir)
