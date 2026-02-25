"""Query visualization utilities and delegation layer for UnifiedGraphRAGQueryOptimizer."""

from __future__ import annotations

import logging
import os
import datetime
from typing import Dict, List, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from matplotlib.figure import Figure
    from matplotlib.axes import Axes
else:

    class Figure:  # pragma: no cover
        pass

    class Axes:  # pragma: no cover
        pass

logger = logging.getLogger(__name__)


class QueryVisualizationHelper:
    """
    Helper class for query visualization delegation.
    
    Provides clean delegation interface between UnifiedGraphRAGQueryOptimizer
    and the underlying QueryVisualizer, handling common setup patterns.
    """

    @staticmethod
    def visualize_query_plan(
        visualizer: Any,
        metrics_collector: Any,
        query_id: Optional[str] = None,
        last_query_id: Optional[str] = None,
        output_file: Optional[str] = None,
        show_plot: bool = True,
        figsize: tuple = (12, 8),
    ) -> Optional[Figure]:
        """
        Visualize the execution plan of a query.

        Args:
            visualizer: QueryVisualizer instance
            metrics_collector: QueryMetricsCollector instance
            query_id (str, optional): Query ID to visualize, most recent if None
            last_query_id (str, optional): Last query ID from optimizer
            output_file (str, optional): Path to save the visualization
            show_plot (bool): Whether to display the plot
            figsize (tuple): Figure size in inches

        Returns:
            Figure or None: The matplotlib figure if available
        """
        if not visualizer:
            logger.warning("No visualizer available. Cannot visualize query plan.")
            return None

        if not metrics_collector:
            logger.warning("No metrics collector available. Cannot visualize query plan.")
            return None

        # Get the query ID
        if query_id is None:
            # Use last query if available
            if last_query_id:
                query_id = last_query_id
            else:
                # Get most recent query
                recent = metrics_collector.get_recent_metrics(1)
                if not recent:
                    logger.warning("No recent queries to visualize.")
                    return None
                query_id = recent[0]["query_id"]

        # Get metrics for this query
        metrics = metrics_collector.get_query_metrics(query_id)
        if not metrics:
            logger.warning(f"No metrics found for query ID: {query_id}")
            return None

        # Create a query plan dictionary from the metrics
        plan = {
            "phases": metrics.get("phases", {}),
            "query_id": query_id,
            "execution_time": metrics.get("duration", 0),
            "params": metrics.get("params", {}),
        }

        # Use the visualizer to display the plan
        return visualizer.visualize_query_plan(
            query_plan=plan,
            title=f"Query Plan for {query_id[:8]}",
            show_plot=show_plot,
            output_file=output_file,
            figsize=figsize,
        )

    @staticmethod
    def visualize_metrics_dashboard(
        visualizer: Any,
        metrics_collector: Any,
        query_id: Optional[str] = None,
        output_file: Optional[str] = None,
        include_all_metrics: bool = False,
    ) -> Optional[str]:
        """
        Generate a comprehensive metrics dashboard for visualization.

        Args:
            visualizer: QueryVisualizer instance
            metrics_collector: QueryMetricsCollector instance
            query_id (str, optional): Specific query ID to focus on
            output_file (str, optional): Path to save the dashboard
            include_all_metrics (bool): Whether to include all available metrics

        Returns:
            str or None: Path to the generated dashboard if successful
        """
        if not visualizer:
            logger.warning("No visualizer available. Cannot create dashboard.")
            return None

        if not metrics_collector:
            logger.warning("No metrics collector available. Cannot create dashboard.")
            return None

        # Set default output file if not provided
        if not output_file and hasattr(metrics_collector, "metrics_dir") and metrics_collector.metrics_dir:
            timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            output_file = os.path.join(metrics_collector.metrics_dir, f"dashboard_{timestamp}.html")

        # Generate dashboard
        visualizer.export_dashboard_html(
            output_file=output_file,
            query_id=query_id,
            include_all_metrics=include_all_metrics,
        )

        return output_file

    @staticmethod
    def visualize_performance_comparison(
        visualizer: Any,
        metrics_collector: Any,
        query_ids: Optional[List[str]] = None,
        labels: Optional[List[str]] = None,
        output_file: Optional[str] = None,
        show_plot: bool = True,
    ) -> Optional[Figure]:
        """
        Compare performance metrics across multiple queries.

        Args:
            visualizer: QueryVisualizer instance
            metrics_collector: QueryMetricsCollector instance
            query_ids (List[str], optional): List of query IDs to compare
            labels (List[str], optional): Labels for each query
            output_file (str, optional): Path to save the visualization
            show_plot (bool): Whether to display the plot

        Returns:
            Figure or None: The matplotlib figure if available
        """
        if not visualizer:
            logger.warning("No visualizer available. Cannot create visualization.")
            return None

        if not metrics_collector:
            logger.warning("No metrics collector available. Cannot create visualization.")
            return None

        # If no query IDs provided, use most recent queries
        if not query_ids:
            recent_metrics = metrics_collector.get_recent_metrics(count=5)
            query_ids = [m["query_id"] for m in recent_metrics]

        # Generate comparison visualization
        return visualizer.visualize_performance_comparison(
            query_ids=query_ids,
            labels=labels,
            show_plot=show_plot,
            output_file=output_file,
        )

    @staticmethod
    def visualize_resource_usage(
        visualizer: Any,
        metrics_collector: Any,
        query_id: Optional[str] = None,
        last_query_id: Optional[str] = None,
        output_file: Optional[str] = None,
        show_plot: bool = True,
    ) -> Optional[Figure]:
        """
        Visualize resource usage (memory and CPU) for a specific query.

        Args:
            visualizer: QueryVisualizer instance
            metrics_collector: QueryMetricsCollector instance
            query_id (str, optional): Query ID to visualize, most recent if None
            last_query_id (str, optional): Last query ID from optimizer
            output_file (str, optional): Path to save the visualization
            show_plot (bool): Whether to display the plot

        Returns:
            Figure or None: The matplotlib figure if available
        """
        if not visualizer:
            logger.warning("No visualizer available. Cannot create visualization.")
            return None

        if not metrics_collector:
            logger.warning("No metrics collector available. Cannot create visualization.")
            return None

        # If no query ID provided, use the most recent query
        if not query_id:
            if last_query_id:
                query_id = last_query_id
            else:
                recent = metrics_collector.get_recent_metrics(1)
                if not recent:
                    logger.warning("No recent queries to visualize.")
                    return None
                query_id = recent[0]["query_id"]

        # Generate resource usage visualization
        return visualizer.visualize_resource_usage(
            query_id=query_id,
            show_plot=show_plot,
            output_file=output_file,
        )

    @staticmethod
    def visualize_query_patterns(
        visualizer: Any,
        limit: int = 10,
        output_file: Optional[str] = None,
        show_plot: bool = True,
    ) -> Optional[Figure]:
        """
        Visualize common query patterns from collected metrics.

        Args:
            visualizer: QueryVisualizer instance
            limit (int): Maximum number of patterns to display
            output_file (str, optional): Path to save the visualization
            show_plot (bool): Whether to display the plot

        Returns:
            Figure or None: The matplotlib figure if available
        """
        if not visualizer:
            logger.warning("No visualizer available. Cannot create visualization.")
            return None

        # Generate query patterns visualization
        return visualizer.visualize_query_patterns(
            limit=limit,
            show_plot=show_plot,
            output_file=output_file,
        )
