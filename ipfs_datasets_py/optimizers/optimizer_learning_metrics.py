"""
RAG Query Optimizer Learning Metrics Collection Module

This module provides a dedicated class for collecting, analyzing, and visualizing metrics
related to the statistical learning process of the RAG query optimizer.
"""

import os
import json
import time
import logging
import datetime
import threading
from collections import defaultdict, namedtuple
from typing import Dict, List, Any, Optional, Tuple, Union, Set

# Setup logging
logger = logging.getLogger(__name__)

try:
    import numpy as np
    import pandas as pd
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import MaxNLocator
    import seaborn as sns
    from matplotlib.figure import Figure
    VISUALIZATION_AVAILABLE = True
except ImportError:
    logger.warning("Matplotlib/Seaborn not available. Visualization functions will not work.")
    VISUALIZATION_AVAILABLE = False

try:
    import plotly.graph_objects as go
    import plotly.express as px
    from plotly.subplots import make_subplots
    INTERACTIVE_VISUALIZATION_AVAILABLE = True
except ImportError:
    logger.warning("Plotly not available. Interactive visualization functions will not work.")
    INTERACTIVE_VISUALIZATION_AVAILABLE = False


class LearningMetrics:
    """Container for aggregated learning metrics."""

    def __init__(self, total_learning_cycles=0, total_analyzed_queries=0,
                total_patterns_identified=0, total_parameters_adjusted=0,
                average_cycle_time=0.0, total_optimizations=0):
        """Initialize with metrics values."""
        self.total_learning_cycles = total_learning_cycles
        self.total_analyzed_queries = total_analyzed_queries
        self.total_patterns_identified = total_patterns_identified
        self.total_parameters_adjusted = total_parameters_adjusted
        self.average_cycle_time = average_cycle_time
        self.total_optimizations = total_optimizations


class OptimizerLearningMetricsCollector:
    """
    Collects and aggregates metrics for statistical learning in the RAG query optimizer.

    This class tracks metrics related to the optimizer's learning process, including:
    - Learning cycles completion
    - Parameter adaptations over time
    - Strategy effectiveness
    - Query pattern recognition

    It provides visualization capabilities for these metrics to help understand
    the optimizer's learning behavior and performance improvements over time.
    """

    def __init__(self, metrics_dir=None, max_history_size=1000):
        """
        Initialize the learning metrics collector.

        Args:
            metrics_dir (str, optional): Directory to store metrics data
            max_history_size (int): Maximum number of learning events to keep in memory
        """
        self.metrics_dir = metrics_dir
        if metrics_dir and not os.path.exists(metrics_dir):
            os.makedirs(metrics_dir, exist_ok=True)

        self.max_history_size = max_history_size
        self._lock = threading.RLock()  # Thread safety for metrics updates

        # Learning metrics
        self.learning_cycles = {}
        self.parameter_adaptations = []
        self.strategy_effectiveness = []
        self.query_patterns = []
        self.learning_start_time = time.time()
        self.total_analyzed_queries = 0
        self.total_optimized_queries = 0
        self.optimization_improvements = []

    def _maybe_save_learning_metrics(self) -> None:
        """Persist metrics to disk when metrics_dir is configured."""
        if self.metrics_dir:
            self._save_learning_metrics()

    def _trim_learning_cycles_if_needed(self) -> None:
        """Enforce max_history_size for learning_cycles (dict has no maxlen)."""
        if len(self.learning_cycles) <= self.max_history_size:
            return

        # Keep the most recent cycles by timestamp.
        sorted_items = sorted(
            self.learning_cycles.items(),
            key=lambda item: item[1].get("timestamp", 0),
        )
        self.learning_cycles = dict(sorted_items[-self.max_history_size:])

    def record_learning_cycle(self, cycle_id, analyzed_queries, patterns_identified,
                             parameters_adjusted, execution_time, timestamp=None):
        """
        Record metrics from a completed learning cycle.

        Args:
            cycle_id (str): Unique identifier for the learning cycle
            analyzed_queries (int): Number of queries analyzed in this cycle
            patterns_identified (int): Number of patterns identified in this cycle
            parameters_adjusted (dict): Parameters adjusted as a result of learning
            execution_time (float): How long the cycle took to execute (seconds)
            timestamp (float, optional): Timestamp of the cycle completion
        """
        with self._lock:
            timestamp = time.time() if timestamp is None else timestamp

            self.learning_cycles[cycle_id] = {
                "timestamp": timestamp,
                "analyzed_queries": analyzed_queries,
                "patterns_identified": patterns_identified,
                "parameters_adjusted": parameters_adjusted,
                "execution_time": execution_time
            }

            self.total_analyzed_queries += analyzed_queries

            # Trim if necessary
            self._trim_learning_cycles_if_needed()

            # Save metrics if directory is specified
            self._maybe_save_learning_metrics()

            logger.info(f"Recorded learning cycle {cycle_id} with {analyzed_queries} queries analyzed")

    def record_parameter_adaptation(self, parameter_name, old_value, new_value,
                                   adaptation_reason, confidence, timestamp=None):
        """
        Record a parameter adaptation from the learning process.

        Args:
            parameter_name (str): Name of the parameter that was adapted
            old_value (Any): Previous value of the parameter
            new_value (Any): New value of the parameter
            adaptation_reason (str): Reason for the adaptation
            confidence (float): Confidence level for the adaptation (0.0-1.0)
            timestamp (float, optional): When the adaptation occurred
        """
        with self._lock:
            timestamp = time.time() if timestamp is None else timestamp

            # Handle numpy/pandas data types for JSON serialization
            if hasattr(old_value, 'tolist'):
                old_value = old_value.tolist()
            if hasattr(new_value, 'tolist'):
                new_value = new_value.tolist()

            adaptation = {
                "timestamp": timestamp,
                "parameter_name": parameter_name,
                "old_value": old_value,
                "new_value": new_value,
                "adaptation_reason": adaptation_reason,
                "confidence": confidence
            }

            self.parameter_adaptations.append(adaptation)

            # Trim if necessary
            if len(self.parameter_adaptations) > self.max_history_size:
                self.parameter_adaptations = self.parameter_adaptations[-self.max_history_size:]

            self._maybe_save_learning_metrics()

            logger.info(f"Recorded parameter adaptation: {parameter_name} changed from {old_value} to {new_value}")

    def record_strategy_effectiveness(self, strategy_name, query_type,
                                     effectiveness_score, execution_time, result_count,
                                     timestamp=None):
        """
        Record the effectiveness of a search strategy.

        Args:
            strategy_name (str): Name of the strategy (e.g., "depth_first", "breadth_first")
            query_type (str): Type of query the strategy was applied to
            effectiveness_score (float): Score indicating how effective the strategy was (0.0-1.0)
            execution_time (float): Time taken to execute the strategy (seconds)
            result_count (int): Number of results returned
            timestamp (float, optional): When the strategy was evaluated
        """
        with self._lock:
            timestamp = time.time() if timestamp is None else timestamp

            effectiveness = {
                "timestamp": timestamp,
                "strategy_name": strategy_name,
                "query_type": query_type,
                "effectiveness_score": effectiveness_score,
                "execution_time": execution_time,
                "result_count": result_count
            }

            self.strategy_effectiveness.append(effectiveness)

            # Trim if necessary
            if len(self.strategy_effectiveness) > self.max_history_size:
                self.strategy_effectiveness = self.strategy_effectiveness[-self.max_history_size:]

            self._maybe_save_learning_metrics()

            logger.info(f"Recorded strategy effectiveness: {strategy_name} for {query_type} with score {effectiveness_score:.2f}")

    def record_query_pattern(self, pattern_id, pattern_type, matching_queries,
                            average_performance, parameters, timestamp=None):
        """
        Record a query pattern identified by the optimizer.

        Args:
            pattern_id (str): Unique identifier for the pattern
            pattern_type (str): Type of pattern (e.g., "semantic", "lexical", "structural")
            matching_queries (int): Number of queries matching this pattern
            average_performance (float): Average performance metric for this pattern
            parameters (dict): Parameters associated with this pattern
            timestamp (float, optional): When the pattern was identified
        """
        with self._lock:
            timestamp = time.time() if timestamp is None else timestamp

            pattern = {
                "timestamp": timestamp,
                "pattern_id": pattern_id,
                "pattern_type": pattern_type,
                "matching_queries": matching_queries,
                "average_performance": average_performance,
                "parameters": parameters
            }

            self.query_patterns.append(pattern)

            # Trim if necessary
            if len(self.query_patterns) > self.max_history_size:
                self.query_patterns = self.query_patterns[-self.max_history_size:]

            self._maybe_save_learning_metrics()

            logger.info(f"Recorded query pattern: {pattern_id} of type {pattern_type} matching {matching_queries} queries")

    def get_learning_metrics(self) -> LearningMetrics:
        """
        Get aggregated learning metrics.

        Returns:
            LearningMetrics: Object containing aggregated metrics
        """
        with self._lock:
            cycle_count = len(self.learning_cycles)

            if cycle_count == 0:
                return LearningMetrics()

            total_analyzed_queries = sum(cycle["analyzed_queries"] for cycle in self.learning_cycles.values())
            total_patterns_identified = sum(cycle["patterns_identified"] for cycle in self.learning_cycles.values())

            # Count total parameter adjustments
            def _count_adjusted(value: Any) -> int:
                if value is None:
                    return 0
                if isinstance(value, dict):
                    return len(value)
                if isinstance(value, (list, tuple, set)):
                    return len(value)
                if isinstance(value, (int, float)):
                    return int(value)
                try:
                    return len(value)  # type: ignore[arg-type]
                except TypeError:
                    return 0

            total_parameters_adjusted = sum(
                _count_adjusted(cycle.get("parameters_adjusted"))
                for cycle in self.learning_cycles.values()
            )

            # Calculate average cycle time
            total_cycle_time = sum(cycle["execution_time"] for cycle in self.learning_cycles.values())
            avg_cycle_time = total_cycle_time / cycle_count if cycle_count > 0 else 0

            return LearningMetrics(
                total_learning_cycles=cycle_count,
                total_analyzed_queries=total_analyzed_queries,
                total_patterns_identified=total_patterns_identified,
                total_parameters_adjusted=total_parameters_adjusted,
                average_cycle_time=avg_cycle_time,
                total_optimizations=self.total_optimized_queries
            )

    def get_effectiveness_by_strategy(self) -> Dict[str, Dict[str, Any]]:
        """
        Get effectiveness metrics aggregated by strategy.

        Returns:
            Dict: Strategy metrics with counts, average scores, and execution times
        """
        with self._lock:
            if not self.strategy_effectiveness:
                return {}

            result = {}

            for item in self.strategy_effectiveness:
                strategy = item["strategy_name"]
                if strategy not in result:
                    result[strategy] = {
                        "count": 0,
                        "total_score": 0.0,
                        "total_time": 0.0,
                        "total_results": 0,
                        "avg_score": 0.0,
                        "avg_time": 0.0,
                        "avg_results": 0
                    }

                result[strategy]["count"] += 1
                result[strategy]["total_score"] += item["effectiveness_score"]
                result[strategy]["total_time"] += item["execution_time"]
                result[strategy]["total_results"] += item["result_count"]

            # Calculate averages
            for strategy, metrics in result.items():
                count = metrics["count"]
                if count > 0:
                    metrics["avg_score"] = metrics["total_score"] / count
                    metrics["avg_time"] = metrics["total_time"] / count
                    metrics["avg_results"] = metrics["total_results"] / count

            return result

    def get_effectiveness_by_query_type(self) -> Dict[str, Dict[str, Any]]:
        """
        Get effectiveness metrics aggregated by query type.

        Returns:
            Dict: Query type metrics with counts, average scores, and execution times
        """
        with self._lock:
            if not self.strategy_effectiveness:
                return {}

            result = {}

            for item in self.strategy_effectiveness:
                query_type = item["query_type"]
                if query_type not in result:
                    result[query_type] = {
                        "count": 0,
                        "total_score": 0.0,
                        "total_time": 0.0,
                        "avg_score": 0.0,
                        "avg_time": 0.0,
                        "strategies": set()
                    }

                result[query_type]["count"] += 1
                result[query_type]["total_score"] += item["effectiveness_score"]
                result[query_type]["total_time"] += item["execution_time"]
                result[query_type]["strategies"].add(item["strategy_name"])

            # Calculate averages
            for query_type, metrics in result.items():
                count = metrics["count"]
                if count > 0:
                    metrics["avg_score"] = metrics["total_score"] / count
                    metrics["avg_time"] = metrics["total_time"] / count

                # Convert set to list for easier serialization
                metrics["strategies"] = list(metrics["strategies"])

            return result

    def get_patterns_by_type(self) -> Dict[str, Dict[str, Any]]:
        """
        Get query patterns aggregated by pattern type.

        Returns:
            Dict: Pattern type metrics with counts and query matches
        """
        with self._lock:
            if not self.query_patterns:
                return {}

            result = {}

            for pattern in self.query_patterns:
                pattern_type = pattern["pattern_type"]
                if pattern_type not in result:
                    result[pattern_type] = {
                        "count": 0,
                        "total_queries": 0,
                        "avg_performance": 0.0,
                        "patterns": []
                    }

                result[pattern_type]["count"] += 1
                result[pattern_type]["total_queries"] += pattern["matching_queries"]
                result[pattern_type]["patterns"].append(pattern["pattern_id"])

                # Update average performance (weighted by matching queries)
                total_performance = result[pattern_type]["avg_performance"] * (result[pattern_type]["total_queries"] - pattern["matching_queries"])
                total_performance += pattern["average_performance"] * pattern["matching_queries"]
                result[pattern_type]["avg_performance"] = total_performance / result[pattern_type]["total_queries"]

            return result

    def visualize_learning_cycles(self, output_file=None, show_plot=False):
        """
        Visualize learning cycles over time.

        Args:
            output_file (str, optional): Path to save the visualization
            show_plot (bool): Whether to display the plot (not recommended for headless environments)

        Returns:
            matplotlib.figure.Figure: The generated figure
        """
        if not VISUALIZATION_AVAILABLE:
            logger.warning("Visualization libraries not available. Cannot generate visualization.")
            return None

        with self._lock:
            if not self.learning_cycles:
                logger.warning("No learning cycles recorded. Cannot generate visualization.")
                return None

            # Extract data for plotting
            timestamps = []
            analyzed_queries = []
            patterns_identified = []
            parameters_adjusted = []
            execution_times = []

            for cycle_id, cycle in sorted(self.learning_cycles.items(),
                                         key=lambda x: x[1]["timestamp"]):
                timestamps.append(datetime.datetime.fromtimestamp(cycle["timestamp"]))
                analyzed_queries.append(cycle["analyzed_queries"])
                patterns_identified.append(cycle["patterns_identified"])
                parameters_adjusted.append(len(cycle["parameters_adjusted"]))
                execution_times.append(cycle["execution_time"])

            # Create figure with multiple subplots
            fig, axes = plt.subplots(nrows=2, ncols=2, figsize=(14, 10), dpi=100)
            plt.subplots_adjust(hspace=0.3, wspace=0.3)

            # Plot 1: Analyzed queries per cycle
            ax1 = axes[0, 0]
            ax1.plot(timestamps, analyzed_queries, 'b-', marker='o')
            ax1.set_title('Queries Analyzed per Learning Cycle')
            ax1.set_xlabel('Time')
            ax1.set_ylabel('Number of Queries')
            ax1.grid(True, alpha=0.3)

            # Plot 2: Patterns identified per cycle
            ax2 = axes[0, 1]
            ax2.plot(timestamps, patterns_identified, 'g-', marker='o')
            ax2.set_title('Patterns Identified per Learning Cycle')
            ax2.set_xlabel('Time')
            ax2.set_ylabel('Number of Patterns')
            ax2.grid(True, alpha=0.3)

            # Plot 3: Parameters adjusted per cycle
            ax3 = axes[1, 0]
            ax3.plot(timestamps, parameters_adjusted, 'r-', marker='o')
            ax3.set_title('Parameters Adjusted per Learning Cycle')
            ax3.set_xlabel('Time')
            ax3.set_ylabel('Number of Parameters')
            ax3.grid(True, alpha=0.3)

            # Plot 4: Execution time per cycle
            ax4 = axes[1, 1]
            ax4.plot(timestamps, execution_times, 'm-', marker='o')
            ax4.set_title('Execution Time per Learning Cycle')
            ax4.set_xlabel('Time')
            ax4.set_ylabel('Time (seconds)')
            ax4.grid(True, alpha=0.3)

            # Format x-axis for all subplots
            for ax in axes.flat:
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
                plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)

            # Add overall title
            fig.suptitle('Learning Cycle Metrics Over Time', fontsize=16)

            # Adjust layout
            plt.tight_layout(rect=[0, 0, 1, 0.95])

            # Save or show the plot
            if output_file:
                plt.savefig(output_file)
                logger.info(f"Learning cycles visualization saved to {output_file}")

            if show_plot:
                plt.show()

            return fig

    def visualize_parameter_adaptations(self, output_file=None, show_plot=False):
        """
        Visualize parameter adaptations over time.

        Args:
            output_file (str, optional): Path to save the visualization
            show_plot (bool): Whether to display the plot

        Returns:
            matplotlib.figure.Figure: The generated figure
        """
        if not VISUALIZATION_AVAILABLE:
            logger.warning("Visualization libraries not available. Cannot generate visualization.")
            return None

        with self._lock:
            if not self.parameter_adaptations:
                logger.warning("No parameter adaptations recorded. Cannot generate visualization.")
                return None

            # Group adaptations by parameter
            parameters = {}
            for adaptation in sorted(self.parameter_adaptations, key=lambda x: x["timestamp"]):
                param_name = adaptation["parameter_name"]
                if param_name not in parameters:
                    parameters[param_name] = {
                        "timestamps": [],
                        "values": [],
                        "confidence": []
                    }

                parameters[param_name]["timestamps"].append(
                    datetime.datetime.fromtimestamp(adaptation["timestamp"])
                )
                parameters[param_name]["values"].append(adaptation["new_value"])
                parameters[param_name]["confidence"].append(adaptation["confidence"])

            # Create figure with two subplots per parameter
            num_params = len(parameters)
            if num_params == 0:
                return None

            fig, axes = plt.subplots(nrows=num_params, ncols=2, figsize=(14, 4 * num_params), dpi=100)

            # Handle single parameter case
            if num_params == 1:
                axes = [axes]

            plt.subplots_adjust(hspace=0.5, wspace=0.3)

            # Plot parameter values and confidence over time
            for i, (param_name, param_data) in enumerate(parameters.items()):
                # Plot parameter values
                ax1 = axes[i][0]
                ax1.plot(param_data["timestamps"], param_data["values"], 'b-', marker='o')
                ax1.set_title(f'Parameter: {param_name} Value Over Time')
                ax1.set_xlabel('Time')
                ax1.set_ylabel('Value')
                ax1.grid(True, alpha=0.3)

                # Format x-axis
                ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
                plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45)

                # Plot confidence levels
                ax2 = axes[i][1]
                ax2.plot(param_data["timestamps"], param_data["confidence"], 'g-', marker='o')
                ax2.set_title(f'Parameter: {param_name} Confidence Level')
                ax2.set_xlabel('Time')
                ax2.set_ylabel('Confidence')
                ax2.set_ylim(0, 1.05)
                ax2.grid(True, alpha=0.3)

                # Format x-axis
                ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
                plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45)

            # Add overall title
            fig.suptitle('Parameter Adaptation Metrics', fontsize=16)

            # Adjust layout
            plt.tight_layout(rect=[0, 0, 1, 0.97])

            # Save or show the plot
            if output_file:
                plt.savefig(output_file)
                logger.info(f"Parameter adaptations visualization saved to {output_file}")

            if show_plot:
                plt.show()

            return fig

    def visualize_strategy_effectiveness(self, output_file=None, show_plot=False):
        """
        Visualize the effectiveness of different search strategies.

        Args:
            output_file (str, optional): Path to save the visualization
            show_plot (bool): Whether to display the plot

        Returns:
            matplotlib.figure.Figure: The generated figure
        """
        if not VISUALIZATION_AVAILABLE:
            logger.warning("Visualization libraries not available. Cannot generate visualization.")
            return None

        with self._lock:
            if not self.strategy_effectiveness:
                logger.warning("No strategy effectiveness data recorded. Cannot generate visualization.")
                return None

            # Get strategy metrics
            strategy_metrics = self.get_effectiveness_by_strategy()
            query_type_metrics = self.get_effectiveness_by_query_type()

            if not strategy_metrics or not query_type_metrics:
                logger.warning("Insufficient strategy data for visualization.")
                return None

            # Create figure with subplots
            fig, axes = plt.subplots(nrows=2, ncols=2, figsize=(14, 10), dpi=100)
            plt.subplots_adjust(hspace=0.4, wspace=0.3)

            # Plot 1: Average effectiveness score by strategy
            ax1 = axes[0, 0]
            strategies = list(strategy_metrics.keys())
            avg_scores = [metrics["avg_score"] for metrics in strategy_metrics.values()]

            bars = ax1.bar(strategies, avg_scores, color='blue', alpha=0.7)
            ax1.set_title('Average Effectiveness Score by Strategy')
            ax1.set_xlabel('Strategy')
            ax1.set_ylabel('Effectiveness Score')
            ax1.set_ylim(0, 1.05)
            ax1.grid(True, alpha=0.3, axis='y')

            # Add value labels on bars
            for bar in bars:
                height = bar.get_height()
                ax1.text(bar.get_x() + bar.get_width()/2., height,
                        f'{height:.2f}',
                        ha='center', va='bottom')

            # Plot 2: Average execution time by strategy
            ax2 = axes[0, 1]
            avg_times = [metrics["avg_time"] for metrics in strategy_metrics.values()]

            bars = ax2.bar(strategies, avg_times, color='green', alpha=0.7)
            ax2.set_title('Average Execution Time by Strategy')
            ax2.set_xlabel('Strategy')
            ax2.set_ylabel('Time (seconds)')
            ax2.grid(True, alpha=0.3, axis='y')

            # Add value labels on bars
            for bar in bars:
                height = bar.get_height()
                ax2.text(bar.get_x() + bar.get_width()/2., height,
                        f'{height:.2f}s',
                        ha='center', va='bottom')

            # Plot 3: Average number of results by strategy
            ax3 = axes[1, 0]
            avg_results = [metrics["avg_results"] for metrics in strategy_metrics.values()]

            bars = ax3.bar(strategies, avg_results, color='red', alpha=0.7)
            ax3.set_title('Average Number of Results by Strategy')
            ax3.set_xlabel('Strategy')
            ax3.set_ylabel('Number of Results')
            ax3.grid(True, alpha=0.3, axis='y')

            # Add value labels on bars
            for bar in bars:
                height = bar.get_height()
                ax3.text(bar.get_x() + bar.get_width()/2., height,
                        f'{height:.1f}',
                        ha='center', va='bottom')

            # Plot 4: Effectiveness by query type
            ax4 = axes[1, 1]
            query_types = list(query_type_metrics.keys())
            query_type_scores = [metrics["avg_score"] for metrics in query_type_metrics.values()]

            bars = ax4.bar(query_types, query_type_scores, color='purple', alpha=0.7)
            ax4.set_title('Average Effectiveness by Query Type')
            ax4.set_xlabel('Query Type')
            ax4.set_ylabel('Effectiveness Score')
            ax4.set_ylim(0, 1.05)
            ax4.grid(True, alpha=0.3, axis='y')

            # Add value labels on bars
            for bar in bars:
                height = bar.get_height()
                ax4.text(bar.get_x() + bar.get_width()/2., height,
                        f'{height:.2f}',
                        ha='center', va='bottom')

            # Add overall title
            fig.suptitle('Strategy Effectiveness Metrics', fontsize=16)

            # Adjust layout
            plt.tight_layout(rect=[0, 0, 1, 0.95])

            # Save or show the plot
            if output_file:
                plt.savefig(output_file)
                logger.info(f"Strategy effectiveness visualization saved to {output_file}")

            if show_plot:
                plt.show()

            return fig

    def visualize_query_patterns(self, output_file=None, show_plot=False):
        """
        Visualize the query patterns identified by the optimizer.

        Args:
            output_file (str, optional): Path to save the visualization
            show_plot (bool): Whether to display the plot

        Returns:
            matplotlib.figure.Figure: The generated figure
        """
        if not VISUALIZATION_AVAILABLE:
            logger.warning("Visualization libraries not available. Cannot generate visualization.")
            return None

        with self._lock:
            if not self.query_patterns:
                logger.warning("No query patterns recorded. Cannot generate visualization.")
                return None

            # Get pattern metrics by type
            pattern_metrics = self.get_patterns_by_type()

            if not pattern_metrics:
                logger.warning("Insufficient pattern data for visualization.")
                return None

            # Create figure with subplots
            fig, axes = plt.subplots(nrows=2, ncols=1, figsize=(12, 10), dpi=100)
            plt.subplots_adjust(hspace=0.4)

            # Plot 1: Number of patterns by type
            ax1 = axes[0]
            pattern_types = list(pattern_metrics.keys())
            pattern_counts = [metrics["count"] for metrics in pattern_metrics.values()]

            bars = ax1.bar(pattern_types, pattern_counts, color='blue', alpha=0.7)
            ax1.set_title('Number of Patterns by Type')
            ax1.set_xlabel('Pattern Type')
            ax1.set_ylabel('Number of Patterns')
            ax1.grid(True, alpha=0.3, axis='y')

            # Add value labels on bars
            for bar in bars:
                height = bar.get_height()
                ax1.text(bar.get_x() + bar.get_width()/2., height,
                        f'{int(height)}',
                        ha='center', va='bottom')

            # Plot 2: Matching queries by pattern type
            ax2 = axes[1]
            matching_queries = [metrics["total_queries"] for metrics in pattern_metrics.values()]

            bars = ax2.bar(pattern_types, matching_queries, color='green', alpha=0.7)
            ax2.set_title('Total Queries Matching Each Pattern Type')
            ax2.set_xlabel('Pattern Type')
            ax2.set_ylabel('Number of Matching Queries')
            ax2.grid(True, alpha=0.3, axis='y')

            # Add value labels on bars
            for bar in bars:
                height = bar.get_height()
                ax2.text(bar.get_x() + bar.get_width()/2., height,
                        f'{int(height)}',
                        ha='center', va='bottom')

            # Add overall title
            fig.suptitle('Query Pattern Analysis', fontsize=16)

            # Adjust layout
            plt.tight_layout(rect=[0, 0, 1, 0.95])

            # Save or show the plot
            if output_file:
                plt.savefig(output_file)
                logger.info(f"Query patterns visualization saved to {output_file}")

            if show_plot:
                plt.show()

            return fig

    def visualize_learning_performance(self, output_file=None, show_plot=False):
        """
        Visualize the performance of the learning process over time.

        Args:
            output_file (str, optional): Path to save the visualization
            show_plot (bool): Whether to display the plot

        Returns:
            matplotlib.figure.Figure: The generated figure
        """
        if not VISUALIZATION_AVAILABLE:
            logger.warning("Visualization libraries not available. Cannot generate visualization.")
            return None

        with self._lock:
            if not self.learning_cycles:
                logger.warning("No learning cycles recorded. Cannot generate visualization.")
                return None

            # Extract data for plotting
            timestamps = []
            execution_times = []
            patterns_per_query = []
            parameters_per_pattern = []

            for cycle_id, cycle in sorted(self.learning_cycles.items(),
                                         key=lambda x: x[1]["timestamp"]):
                timestamp = datetime.datetime.fromtimestamp(cycle["timestamp"])
                timestamps.append(timestamp)
                execution_times.append(cycle["execution_time"])

                # Calculate patterns identified per query
                if cycle["analyzed_queries"] > 0:
                    patterns_per_query.append(cycle["patterns_identified"] / cycle["analyzed_queries"])
                else:
                    patterns_per_query.append(0)

                # Calculate parameters adjusted per pattern
                if cycle["patterns_identified"] > 0:
                    parameters_per_pattern.append(len(cycle["parameters_adjusted"]) / cycle["patterns_identified"])
                else:
                    parameters_per_pattern.append(0)

            # Create figure with subplots
            fig, axes = plt.subplots(nrows=2, ncols=2, figsize=(14, 10), dpi=100)
            plt.subplots_adjust(hspace=0.4, wspace=0.3)

            # Plot 1: Learning cycle execution time trend
            ax1 = axes[0, 0]
            ax1.plot(timestamps, execution_times, 'b-', marker='o')
            ax1.set_title('Learning Cycle Execution Time Trend')
            ax1.set_xlabel('Time')
            ax1.set_ylabel('Execution Time (seconds)')
            ax1.grid(True, alpha=0.3)

            # Add trendline using numpy's polyfit
            if len(timestamps) >= 2:
                timestamp_nums = mdates.date2num(timestamps)
                z = np.polyfit(timestamp_nums, execution_times, 1)
                p = np.poly1d(z)
                ax1.plot(timestamps, p(timestamp_nums), "r--", alpha=0.8,
                        label=f"Trend: {z[0]:.3f}x + {z[1]:.3f}")
                ax1.legend()

            # Format x-axis
            ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45)

            # Plot 2: Patterns identified per query
            ax2 = axes[0, 1]
            ax2.plot(timestamps, patterns_per_query, 'g-', marker='o')
            ax2.set_title('Patterns Identified Per Query')
            ax2.set_xlabel('Time')
            ax2.set_ylabel('Patterns per Query')
            ax2.grid(True, alpha=0.3)

            # Format x-axis
            ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45)

            # Plot 3: Parameters adjusted per pattern
            ax3 = axes[1, 0]
            ax3.plot(timestamps, parameters_per_pattern, 'r-', marker='o')
            ax3.set_title('Parameters Adjusted Per Pattern')
            ax3.set_xlabel('Time')
            ax3.set_ylabel('Parameters per Pattern')
            ax3.grid(True, alpha=0.3)

            # Format x-axis
            ax3.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            plt.setp(ax3.xaxis.get_majorticklabels(), rotation=45)

            # Plot 4: Cumulative patterns identified
            ax4 = axes[1, 1]
            cumulative_patterns = np.cumsum([cycle["patterns_identified"]
                                         for _, cycle in sorted(self.learning_cycles.items(),
                                                             key=lambda x: x[1]["timestamp"])])
            ax4.plot(timestamps, cumulative_patterns, 'm-', marker='o')
            ax4.set_title('Cumulative Patterns Identified')
            ax4.set_xlabel('Time')
            ax4.set_ylabel('Total Patterns')
            ax4.grid(True, alpha=0.3)

            # Format x-axis
            ax4.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            plt.setp(ax4.xaxis.get_majorticklabels(), rotation=45)

            # Add overall title
            fig.suptitle('Learning Performance Metrics', fontsize=16)

            # Adjust layout
            plt.tight_layout(rect=[0, 0, 1, 0.95])

            # Save or show the plot
            if output_file:
                plt.savefig(output_file)
                logger.info(f"Learning performance visualization saved to {output_file}")

            if show_plot:
                plt.show()

            return fig

    def create_interactive_learning_dashboard(self, output_file=None):
        """
        Create an interactive dashboard of learning metrics using Plotly.

        Args:
            output_file (str, optional): Path to save the HTML dashboard

        Returns:
            str: Path to the generated HTML file, or HTML string if no path provided
        """
        if not INTERACTIVE_VISUALIZATION_AVAILABLE:
            logger.warning("Interactive visualization libraries not available. Cannot generate dashboard.")
            return None

        with self._lock:
            if not self.learning_cycles:
                logger.warning("No learning cycles recorded. Cannot generate dashboard.")
                return None

            # Create figure with subplots
            fig = make_subplots(
                rows=3, cols=2,
                subplot_titles=(
                    'Learning Cycle Metrics',
                    'Parameter Adaptations Over Time',
                    'Strategy Effectiveness',
                    'Query Patterns by Type',
                    'Learning Performance Trends',
                    'Cumulative Learning Metrics'
                ),
                specs=[
                    [{"type": "scatter"}, {"type": "scatter"}],
                    [{"type": "bar"}, {"type": "bar"}],
                    [{"type": "scatter"}, {"type": "pie"}]
                ]
            )

            # Prepare data for plots

            # 1. Learning Cycle Metrics
            cycle_data = sorted(self.learning_cycles.items(), key=lambda x: x[1]["timestamp"])
            timestamps = [datetime.datetime.fromtimestamp(cycle["timestamp"]) for _, cycle in cycle_data]
            analyzed_queries = [cycle["analyzed_queries"] for _, cycle in cycle_data]
            patterns_identified = [cycle["patterns_identified"] for _, cycle in cycle_data]

            # Add traces for learning cycles
            fig.add_trace(
                go.Scatter(
                    x=timestamps,
                    y=analyzed_queries,
                    mode='lines+markers',
                    name='Queries Analyzed',
                    line=dict(color='blue')
                ),
                row=1, col=1
            )

            fig.add_trace(
                go.Scatter(
                    x=timestamps,
                    y=patterns_identified,
                    mode='lines+markers',
                    name='Patterns Identified',
                    line=dict(color='green')
                ),
                row=1, col=1
            )

            # 2. Parameter Adaptations
            if self.parameter_adaptations:
                param_data = sorted(self.parameter_adaptations, key=lambda x: x["timestamp"])
                param_timestamps = [datetime.datetime.fromtimestamp(adapt["timestamp"]) for adapt in param_data]
                param_names = [adapt["parameter_name"] for adapt in param_data]
                confidences = [adapt["confidence"] for adapt in param_data]

                # Create hover text with parameter details
                hover_texts = []
                for adapt in param_data:
                    hover_texts.append(
                        f"Parameter: {adapt['parameter_name']}<br>" +
                        f"Old value: {adapt['old_value']}<br>" +
                        f"New value: {adapt['new_value']}<br>" +
                        f"Reason: {adapt['adaptation_reason']}<br>" +
                        f"Confidence: {adapt['confidence']:.2f}"
                    )

                fig.add_trace(
                    go.Scatter(
                        x=param_timestamps,
                        y=confidences,
                        mode='markers',
                        marker=dict(
                            size=10,
                            color=confidences,
                            colorscale='Viridis',
                            showscale=True,
                            colorbar=dict(title="Confidence")
                        ),
                        text=hover_texts,
                        hoverinfo='text',
                        name='Parameter Adaptations'
                    ),
                    row=1, col=2
                )

            # 3. Strategy Effectiveness
            if self.strategy_effectiveness:
                strategy_metrics = self.get_effectiveness_by_strategy()
                strategies = list(strategy_metrics.keys())
                avg_scores = [metrics["avg_score"] for metrics in strategy_metrics.values()]

                fig.add_trace(
                    go.Bar(
                        x=strategies,
                        y=avg_scores,
                        name='Effectiveness Score',
                        marker_color='purple'
                    ),
                    row=2, col=1
                )

            # 4. Query Patterns
            if self.query_patterns:
                pattern_metrics = self.get_patterns_by_type()
                pattern_types = list(pattern_metrics.keys())
                pattern_counts = [metrics["count"] for metrics in pattern_metrics.values()]
                matching_queries = [metrics["total_queries"] for metrics in pattern_metrics.values()]

                fig.add_trace(
                    go.Bar(
                        x=pattern_types,
                        y=pattern_counts,
                        name='Pattern Count',
                        marker_color='blue'
                    ),
                    row=2, col=2
                )

                fig.add_trace(
                    go.Bar(
                        x=pattern_types,
                        y=matching_queries,
                        name='Matching Queries',
                        marker_color='green'
                    ),
                    row=2, col=2
                )

            # 5. Learning Performance Trends
            if len(timestamps) >= 2:
                execution_times = [cycle["execution_time"] for _, cycle in cycle_data]

                fig.add_trace(
                    go.Scatter(
                        x=timestamps,
                        y=execution_times,
                        mode='lines+markers',
                        name='Execution Time',
                        line=dict(color='red')
                    ),
                    row=3, col=1
                )

                # Add trendline
                import numpy as np
                timestamp_nums = [ts.timestamp() for ts in timestamps]
                z = np.polyfit(timestamp_nums, execution_times, 1)
                p = np.poly1d(z)
                trend_y = p(timestamp_nums)

                fig.add_trace(
                    go.Scatter(
                        x=timestamps,
                        y=trend_y,
                        mode='lines',
                        name='Trend',
                        line=dict(color='red', dash='dash')
                    ),
                    row=3, col=1
                )

            # 6. Cumulative Metrics as Pie Chart
            metrics = self.get_learning_metrics()

            fig.add_trace(
                go.Pie(
                    labels=['Learning Cycles', 'Parameters Adjusted', 'Patterns Identified'],
                    values=[metrics.total_learning_cycles,
                           metrics.total_parameters_adjusted,
                           metrics.total_patterns_identified],
                    hole=.3,
                    marker_colors=['#FFA15A', '#19D3F3', '#FF6692']
                ),
                row=3, col=2
            )

            # Update layout
            fig.update_layout(
                title_text="RAG Query Optimizer Learning Metrics Dashboard",
                height=900,
                width=1200,
                showlegend=True,
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1
                )
            )

            # Save or return HTML
            if output_file:
                fig.write_html(output_file)
                logger.info(f"Interactive learning dashboard saved to {output_file}")
                return output_file
            else:
                return fig.to_html()

    def _save_learning_metrics(self):
        """Save learning metrics to JSON file in metrics directory."""
        if not self.metrics_dir:
            return

        try:
            metrics_file = os.path.join(self.metrics_dir, "learning_metrics.json")
            with open(metrics_file, 'w') as f:
                f.write(self.to_json())

            logger.debug(f"Learning metrics saved to {metrics_file}")
        except Exception as e:
            logger.error(f"Error saving learning metrics: {str(e)}")

    def to_json(self):
        """
        Convert metrics data to JSON for serialization.

        Returns:
            str: JSON string representation of metrics data
        """
        with self._lock:
            # Create a copy of the data to avoid threading issues
            data = {
                "learning_cycles": self.learning_cycles,
                "parameter_adaptations": self.parameter_adaptations,
                "strategy_effectiveness": self.strategy_effectiveness,
                "query_patterns": self.query_patterns,
                "total_analyzed_queries": self.total_analyzed_queries,
                "total_optimized_queries": self.total_optimized_queries,
                "learning_start_time": self.learning_start_time,
            }

            # Handle numpy/pandas data types for JSON serialization
            class NumpyEncoder(json.JSONEncoder):
                def default(self, obj):
                    if hasattr(obj, 'tolist'):
                        return obj.tolist()
                    elif isinstance(obj, datetime.datetime):
                        return obj.isoformat()
                    return json.JSONEncoder.default(self, obj)

            try:
                return json.dumps(data, cls=NumpyEncoder)
            except TypeError as e:
                logger.error(f"Error serializing metrics data: {str(e)}")
                # Fallback to basic serialization
                return json.dumps({
                    "learning_cycles": len(self.learning_cycles),
                    "parameter_adaptations": len(self.parameter_adaptations),
                    "strategy_effectiveness": len(self.strategy_effectiveness),
                    "query_patterns": len(self.query_patterns),
                    "error": str(e)
                })

    @classmethod
    def from_json(cls, json_data):
        """
        Create a metrics collector from JSON data.

        Args:
            json_data (str): JSON string with metrics data

        Returns:
            OptimizerLearningMetricsCollector: Populated metrics collector
        """
        try:
            data = json.loads(json_data)
            collector = cls()

            # Load data into collector
            collector.learning_cycles = data.get("learning_cycles", {})
            collector.parameter_adaptations = data.get("parameter_adaptations", [])
            collector.strategy_effectiveness = data.get("strategy_effectiveness", [])
            collector.query_patterns = data.get("query_patterns", [])
            collector.total_analyzed_queries = data.get("total_analyzed_queries", 0)
            collector.total_optimized_queries = data.get("total_optimized_queries", 0)
            collector.learning_start_time = data.get("learning_start_time", time.time())

            return collector
        except Exception as e:
            logger.error(f"Error loading metrics from JSON: {str(e)}")
            return cls()
