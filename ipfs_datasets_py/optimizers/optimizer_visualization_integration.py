"""
RAG Query Optimizer Visualization Integration

This module integrates the OptimizerLearningMetricsVisualizer with real optimizer data,
enabling live visualization of statistical learning metrics from the RAG query optimizer.
"""

import os
import time
import datetime
import logging
import threading
from typing import Dict, List, Any, Optional, Union, Set, Callable

# Import visualization components
from ipfs_datasets_py.audit.audit_visualization import OptimizerLearningMetricsVisualizer
from ipfs_datasets_py.optimizers.optimizer_learning_metrics import OptimizerLearningMetricsCollector
from ipfs_datasets_py.optimizers.optimizer_learning_metrics_integration import MetricsCollectorAdapter

# Setup logging
logger = logging.getLogger(__name__)

class LiveOptimizerVisualization:
    """
    Integrates metrics collection with real-time visualization for the RAG query optimizer.

    This class connects the learning metrics collector to the visualization system,
    enabling real-time monitoring and analysis of the optimizer's learning process.
    """

    def __init__(
        self,
        optimizer=None,
        metrics_dir: Optional[str] = None,
        visualization_dir: Optional[str] = None,
        visualization_interval: int = 3600,  # 1 hour by default
        dashboard_filename: str = "rag_optimizer_dashboard.html",
        metrics_source=None
    ):
        """
        Initialize the live visualization integration.

        Args:
            optimizer: The RAG query optimizer instance to monitor
            metrics_dir: Directory for storing metrics data
            visualization_dir: Directory for storing visualization outputs
            visualization_interval: Interval in seconds for automatic visualization updates
            dashboard_filename: Filename for the HTML dashboard
            metrics_source: Optional function that returns metrics directly (for simulation)
        """
        self.optimizer = optimizer
        self.metrics_dir = metrics_dir or os.path.join(os.getcwd(), "rag_metrics")
        self.metrics_source = metrics_source

        # Create metrics directory if it doesn't exist
        if not os.path.exists(self.metrics_dir):
            os.makedirs(self.metrics_dir, exist_ok=True)

        # Set visualization directory
        self.visualization_dir = visualization_dir or os.path.join(self.metrics_dir, "visualizations")
        if not os.path.exists(self.visualization_dir):
            os.makedirs(self.visualization_dir, exist_ok=True)

        self.visualization_interval = visualization_interval
        self.dashboard_filename = dashboard_filename
        self.dashboard_path = os.path.join(self.visualization_dir, self.dashboard_filename)

        # Create metrics collector if not present in optimizer
        self.setup_metrics_collector()

        # Create visualizer
        self.visualizer = OptimizerLearningMetricsVisualizer(
            metrics_collector=self.get_learning_metrics_collector(),
            output_dir=self.visualization_dir
        )

        # Setup auto-update thread for visualizations
        self._stop_auto_update = threading.Event()
        self._auto_update_thread = None
        self.last_update_time = time.time()

        # List to store alert markers
        self.alert_markers = []

    def setup_metrics_collector(self):
        """
        Set up the metrics collector integration with the optimizer.
        """
        if self.optimizer is None:
            # Create standalone metrics collector
            self.standalone_metrics_collector = OptimizerLearningMetricsCollector(
                metrics_dir=self.metrics_dir
            )
            return

        # Check if optimizer already has a metrics collector
        if hasattr(self.optimizer, 'metrics_collector'):
            existing_collector = self.optimizer.metrics_collector

            # If it's already an adapter, verify it has learning metrics
            if isinstance(existing_collector, MetricsCollectorAdapter):
                # Ensure it has a learning metrics collector
                if existing_collector.learning_metrics_collector is None:
                    existing_collector.learning_metrics_collector = OptimizerLearningMetricsCollector(
                        metrics_dir=self.metrics_dir
                    )
            else:
                # Wrap existing collector in an adapter
                self.optimizer.metrics_collector = MetricsCollectorAdapter(
                    query_metrics_collector=existing_collector,
                    metrics_dir=self.metrics_dir
                )
        else:
            # Create new metrics collector and adapter
            learning_metrics = OptimizerLearningMetricsCollector(metrics_dir=self.metrics_dir)
            self.optimizer.metrics_collector = MetricsCollectorAdapter(
                learning_metrics_collector=learning_metrics,
                metrics_dir=self.metrics_dir
            )

    def get_learning_metrics_collector(self) -> OptimizerLearningMetricsCollector:
        """
        Get the learning metrics collector instance.

        Returns:
            OptimizerLearningMetricsCollector: The metrics collector
        """
        if self.optimizer is None:
            return self.standalone_metrics_collector

        if hasattr(self.optimizer, 'metrics_collector'):
            if isinstance(self.optimizer.metrics_collector, MetricsCollectorAdapter):
                return self.optimizer.metrics_collector.learning_metrics_collector

        # If we got here, something is wrong with the setup
        logger.warning("Metrics collector not properly configured in optimizer. Creating standalone instance.")
        self.standalone_metrics_collector = OptimizerLearningMetricsCollector(
            metrics_dir=self.metrics_dir
        )
        return self.standalone_metrics_collector

    def start_auto_update(self):
        """
        Start automatic periodic updates of visualizations.
        """
        if self._auto_update_thread is not None and self._auto_update_thread.is_alive():
            logger.warning("Auto-update thread is already running")
            return

        self._stop_auto_update.clear()
        self._auto_update_thread = threading.Thread(
            target=self._auto_update_loop,
            daemon=True
        )
        self._auto_update_thread.start()
        logger.info(f"Started auto-update thread with interval {self.visualization_interval} seconds")

    def stop_auto_update(self):
        """
        Stop the automatic visualization updates.
        """
        if self._auto_update_thread is None or not self._auto_update_thread.is_alive():
            logger.warning("Auto-update thread is not running")
            return

        self._stop_auto_update.set()
        self._auto_update_thread.join(timeout=5.0)
        logger.info("Stopped auto-update thread")

    def _auto_update_loop(self):
        """
        Background thread that periodically updates visualizations.
        """
        while not self._stop_auto_update.is_set():
            # Wait for a short time and check stop flag
            for _ in range(60):  # Check every second
                if self._stop_auto_update.is_set():
                    return
                time.sleep(1)

            # Check if it's time to update
            current_time = time.time()
            if current_time - self.last_update_time >= self.visualization_interval:
                try:
                    logger.info("Auto-updating visualizations")
                    self.update_visualizations()
                    self.last_update_time = current_time
                except Exception as e:
                    logger.error(f"Error during auto-update: {e}")

    def update_visualizations(self, create_dashboard: bool = True) -> Dict[str, str]:
        """
        Update all visualizations based on current metrics.

        Args:
            create_dashboard: Whether to generate a comprehensive dashboard

        Returns:
            Dict[str, str]: Paths to generated visualization files
        """
        # Generate timestamp for filenames
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        results = {}

        # Generate static visualizations
        cycles_png = os.path.join(self.visualization_dir, f"learning_cycles_{timestamp}.png")
        cycles_result = self.visualizer.visualize_learning_cycles(
            output_file=cycles_png,
            interactive=False,
            alert_markers=self.alert_markers
        )
        if cycles_result:
            results['learning_cycles_static'] = cycles_png

        params_png = os.path.join(self.visualization_dir, f"parameter_adaptations_{timestamp}.png")
        params_result = self.visualizer.visualize_parameter_adaptations(
            output_file=params_png,
            interactive=False,
            alert_markers=self.alert_markers
        )
        if params_result:
            results['parameter_adaptations_static'] = params_png

        strategy_png = os.path.join(self.visualization_dir, f"strategy_effectiveness_{timestamp}.png")
        strategy_result = self.visualizer.visualize_strategy_effectiveness(
            output_file=strategy_png,
            interactive=False,
            alert_markers=self.alert_markers
        )
        if strategy_result:
            results['strategy_effectiveness_static'] = strategy_png

        # Generate dashboard if requested
        if create_dashboard:
            dashboard_path = self.visualizer.generate_learning_metrics_dashboard(
                output_file=self.dashboard_path,
                alert_markers=self.alert_markers
            )
            if dashboard_path:
                results['dashboard'] = dashboard_path

        return results

    def add_alert_marker(self, timestamp, alert_type, message):
        """
        Add an alert marker to be displayed on visualizations.

        Args:
            timestamp (datetime): When the alert occurred
            alert_type (str): Type of alert (e.g., "oscillation", "performance")
            message (str): Alert message
        """
        marker = {
            "timestamp": timestamp,
            "type": alert_type,
            "message": message
        }
        self.alert_markers.append(marker)
        logger.info(f"Added alert marker: {alert_type} at {timestamp}: {message}")

        # Update visualizations immediately if auto-update is running
        if self._auto_update_thread and self._auto_update_thread.is_alive():
            self.update_visualizations(create_dashboard=True)

    def inject_sample_data(self, num_cycles=10, num_adaptations=20, num_strategies=30):
        """
        Inject sample data into the metrics collector for testing/demo purposes.

        Args:
            num_cycles: Number of learning cycles to simulate
            num_adaptations: Number of parameter adaptations to simulate
            num_strategies: Number of strategy effectiveness entries to simulate
        """
        import random

        metrics_collector = self.get_learning_metrics_collector()
        now = datetime.datetime.now()

        # Generate sample learning cycles
        for i in range(num_cycles):
            metrics_collector.record_learning_cycle(
                cycle_id=f"cycle_{i}",
                analyzed_queries=10 + i * 5 + random.randint(-2, 2),
                patterns_identified=2 + i + random.randint(0, 2),
                parameters_adjusted={f"param{j}": float(j) for j in range(i % 3 + 1)},
                execution_time=2.5 + i * 0.5 + random.random(),
                timestamp=now - datetime.timedelta(days=num_cycles-i)
            )

        # Generate sample parameter adaptations
        param_names = ['max_depth', 'min_similarity', 'vector_weight', 'graph_weight', 'cache_ttl']
        for i in range(num_adaptations):
            param_idx = i % len(param_names)
            param_name = param_names[param_idx]

            # Create different adaptation patterns for different parameters
            if param_name == 'max_depth':
                old_value = 2 + (i // 4)
                new_value = old_value + 1
            elif param_name == 'min_similarity':
                old_value = 0.5 + (i // 5) * 0.05
                new_value = max(0.4, old_value - 0.05) if i % 2 == 0 else min(0.9, old_value + 0.05)
            elif param_name == 'vector_weight':
                old_value = 0.6
                new_value = 0.7 if i % 4 == 0 else 0.6
            elif param_name == 'graph_weight':
                old_value = 0.4
                new_value = 0.3 if i % 4 == 0 else 0.4
            else:  # cache_ttl
                old_value = 300
                new_value = 600 if i > 10 else 300

            metrics_collector.record_parameter_adaptation(
                parameter_name=param_name,
                old_value=old_value,
                new_value=new_value,
                adaptation_reason=f"Performance tuning cycle {i//3}",
                confidence=0.8 + random.random() * 0.2,
                timestamp=now - datetime.timedelta(days=num_adaptations//2-i//2)
            )

        # Generate sample strategy effectiveness data
        strategies = ['vector_first', 'graph_first', 'balanced']
        query_types = ['factual', 'complex', 'exploratory']

        for i in range(num_strategies):
            strategy = strategies[i % len(strategies)]
            query_type = query_types[(i // 3) % len(query_types)]
            timestamp = now - datetime.timedelta(days=num_strategies//2-i//2)

            # Create different patterns for different strategies
            if strategy == 'vector_first':
                success_rate = 0.7 + min(0.25, (i / 40))
                mean_latency = 2.0 - min(1.0, (i / 30))
            elif strategy == 'graph_first':
                success_rate = 0.6 + min(0.35, (i / 30))
                mean_latency = 2.5 - min(1.2, (i / 25))
            else:  # balanced
                success_rate = 0.75 + min(0.2, (i / 50))
                mean_latency = 1.8 - min(0.7, (i / 35))

            # Adjust by query type
            if query_type == 'factual':
                success_rate = min(0.95, success_rate + 0.1)
                mean_latency = max(0.5, mean_latency - 0.5)
            elif query_type == 'complex':
                success_rate = max(0.6, success_rate - 0.1)
                mean_latency = mean_latency + 0.8

            metrics_collector.record_strategy_effectiveness(
                strategy_name=strategy,
                query_type=query_type,
                effectiveness_score=success_rate,
                execution_time=mean_latency,
                result_count=10 + i,
                timestamp=timestamp
            )

        logger.info(f"Injected sample data: {num_cycles} cycles, {num_adaptations} adaptations, {num_strategies} strategy records")


# Convenience function to create and setup visualization for an optimizer
def setup_optimizer_visualization(
    optimizer=None,
    metrics_dir=None,
    visualization_dir=None,
    auto_update=True,
    visualization_interval=3600,
    dashboard_filename="rag_optimizer_dashboard.html"
) -> LiveOptimizerVisualization:
    """
    Set up live visualization for a RAG query optimizer.

    Args:
        optimizer: RAG query optimizer instance to visualize
        metrics_dir: Directory for storing metrics data
        visualization_dir: Directory for storing visualization outputs
        auto_update: Whether to enable automatic visualization updates
        visualization_interval: Interval in seconds for visualization updates
        dashboard_filename: Filename for the HTML dashboard

    Returns:
        LiveOptimizerVisualization: The configured visualization system
    """
    visualization = LiveOptimizerVisualization(
        optimizer=optimizer,
        metrics_dir=metrics_dir,
        visualization_dir=visualization_dir,
        visualization_interval=visualization_interval,
        dashboard_filename=dashboard_filename
    )

    if auto_update:
        visualization.start_auto_update()

    return visualization
