"""
Enhanced RAG Query Visualization module.

This module extends the RAG query visualization capabilities
with additional visualizations for metrics collection and
performance analysis, particularly integrating with the audit
visualization system.
"""

import os
import time
import datetime
import logging
import numpy as np
from typing import Dict, List, Any, Optional, Tuple, Union, TYPE_CHECKING

# Type checking imports
if TYPE_CHECKING:
    try:
        from matplotlib.figure import Figure
    except ImportError:
        Figure = Any
from collections import defaultdict

# Import visualization libraries if available
try:
    import numpy as np
    import pandas as pd
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend for server environments
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.figure import Figure
    import seaborn as sns
    VISUALIZATION_LIBS_AVAILABLE = True
except ImportError:
    VISUALIZATION_LIBS_AVAILABLE = False

# Import for interactive components
try:
    import plotly.express as px
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    INTERACTIVE_LIBS_AVAILABLE = True
except ImportError:
    INTERACTIVE_LIBS_AVAILABLE = False

# Import existing visualization components
from ipfs_datasets_py.rag.rag_query_visualization import EnhancedQueryVisualizer
from ipfs_datasets_py.rag.rag_query_optimizer import QueryMetricsCollector

class EnhancedQueryAuditVisualizer(EnhancedQueryVisualizer):
    """
    Extended visualization capabilities for RAG query metrics with audit integration.

    This class adds audit-related visualizations to the EnhancedQueryVisualizer,
    including correlation analysis between query performance and security events.
    """

    def visualize_query_audit_metrics(
        self,
        audit_metrics_aggregator,
        time_window: Optional[int] = None,  # in seconds
        title: str = "Query Performance and Audit Events Timeline",
        show_plot: bool = True,
        output_file: Optional[str] = None,
        interactive: bool = False,
        figsize: Tuple[int, int] = (14, 8)
    ) -> Optional[Union["Figure", Dict[str, Any]]]:
        """
        Visualize the relationship between RAG query performance and audit/security events.

        Args:
            audit_metrics_aggregator: AuditMetricsAggregator to get audit events from
            time_window: Time window in seconds to include, or None for all time
            title: Plot title
            show_plot: Whether to display the plot
            output_file: Path to save the plot image
            interactive: Whether to create an interactive plot (requires plotly)
            figsize: Figure size (width, height) in inches

        Returns:
            matplotlib.figure.Figure, plotly figure dict, or None
        """
        if not VISUALIZATION_LIBS_AVAILABLE:
            logging.warning("Visualization libraries not available. Install matplotlib and seaborn.")
            return None

        if interactive and not INTERACTIVE_LIBS_AVAILABLE:
            logging.warning("Interactive plotting libraries not available. Install plotly.")
            interactive = False

        if not self.metrics_collector:
            logging.warning("No query metrics collector set. Use set_metrics_collector() first.")
            return None

        if audit_metrics_aggregator is None:
            logging.warning("No audit metrics aggregator provided.")
            return None

        # Get query metrics
        metrics_list = list(self.metrics_collector.query_metrics)

        if not metrics_list:
            logging.warning("No query metrics available for visualization.")
            return None

        # Get audit metrics with efficient batch retrieval
        audit_events = audit_metrics_aggregator.get_recent_events(
            hours_back=time_window // 3600 if time_window else 24,
            include_details=True,
            max_events=1000  # Limit to prevent memory issues with very large datasets
        )

        if not audit_events:
            logging.warning("No audit events available for visualization.")

        # Filter query metrics by time window if specified
        if time_window:
            current_time = time.time()
            cutoff_time = current_time - time_window
            metrics_list = [m for m in metrics_list if m.get("start_time", 0) >= cutoff_time]

        # Sort by timestamp
        metrics_list.sort(key=lambda x: x.get("start_time", 0))

        # Sample data for large datasets to maintain performance
        MAX_DATAPOINTS = 500  # Maximum number of data points to display
        if len(metrics_list) > MAX_DATAPOINTS:
            logging.info(f"Sampling large dataset: {len(metrics_list)} -> {MAX_DATAPOINTS} points")
            # Use systematic sampling to preserve temporal patterns
            sample_indices = np.linspace(0, len(metrics_list) - 1, MAX_DATAPOINTS, dtype=int)
            metrics_list = [metrics_list[i] for i in sample_indices]

        # Extract time series data for queries
        query_timestamps = [datetime.datetime.fromtimestamp(m.get("start_time", 0)) for m in metrics_list]
        query_durations = [m.get("duration", 0) for m in metrics_list]
        query_ids = [m.get("query_id", f"q{i}") for i, m in enumerate(metrics_list)]

        # Extract time series data for audit events
        if audit_events:
            # Sample audit events if there are too many
            if len(audit_events) > MAX_DATAPOINTS:
                logging.info(f"Sampling large audit dataset: {len(audit_events)} -> {MAX_DATAPOINTS} points")
                # Preserve critical and error events, then sample the rest
                critical_events = [e for e in audit_events if e["level"] in ("CRITICAL", "ERROR")]
                other_events = [e for e in audit_events if e["level"] not in ("CRITICAL", "ERROR")]

                # Calculate how many regular events to include
                remaining_slots = MAX_DATAPOINTS - len(critical_events)
                if remaining_slots > 0 and other_events:
                    # Sample from regular events
                    sample_indices = np.linspace(0, len(other_events) - 1,
                                                min(remaining_slots, len(other_events)),
                                                dtype=int)
                    sampled_other_events = [other_events[i] for i in sample_indices]
                    audit_events = critical_events + sampled_other_events
                else:
                    # If we have more critical events than MAX_DATAPOINTS or no other events
                    audit_events = critical_events[:MAX_DATAPOINTS]

                # Sort events by timestamp again after sampling
                audit_events.sort(key=lambda e: e["timestamp"])

            audit_timestamps = [datetime.datetime.fromtimestamp(e["timestamp"]) for e in audit_events]
            audit_levels = [e["level"] for e in audit_events]
            audit_categories = [e["category"] for e in audit_events]
            audit_messages = [e["message"] for e in audit_events]
        else:
            audit_timestamps = []
            audit_levels = []
            audit_categories = []
            audit_messages = []

        # Determine time range for the plot
        if query_timestamps and audit_timestamps:
            min_time = min(min(query_timestamps), min(audit_timestamps))
            max_time = max(max(query_timestamps), max(audit_timestamps))
        elif query_timestamps:
            min_time = min(query_timestamps)
            max_time = max(query_timestamps)
        elif audit_timestamps:
            min_time = min(audit_timestamps)
            max_time = max(audit_timestamps)
        else:
            logging.warning("No data available for visualization.")
            return None

        # Map audit levels to colors
        level_colors = {
            "INFO": "#4CAF50",  # Green
            "WARNING": "#FF9800",  # Orange
            "ERROR": "#F44336",  # Red
            "CRITICAL": "#9C27B0",  # Purple
            "DEBUG": "#2196F3"  # Blue
        }

        if interactive:
            # Create interactive visualization with plotly
            fig = make_subplots(
                rows=2, cols=1,
                shared_xaxes=True,
                subplot_titles=("Query Duration", "Audit Events"),
                vertical_spacing=0.1,
                row_heights=[0.6, 0.4]
            )

            # Add query duration scatter plot
            fig.add_trace(
                go.Scatter(
                    x=query_timestamps,
                    y=query_durations,
                    mode='lines+markers',
                    name='Query Duration (s)',
                    marker=dict(
                        size=8,
                        color=self.colors["vector_search"],
                        line=dict(width=1, color=self.colors["text"])
                    ),
                    hovertemplate='<b>Query ID:</b> %{text}<br>Time: %{x}<br>Duration: %{y:.3f}s',
                    text=query_ids
                ),
                row=1, col=1
            )

            # Add audit events scatter plot with color coding by level
            for level in set(audit_levels):
                indices = [i for i, l in enumerate(audit_levels) if l == level]
                if not indices:
                    continue

                fig.add_trace(
                    go.Scatter(
                        x=[audit_timestamps[i] for i in indices],
                        y=[1] * len(indices),  # All at same y level
                        mode='markers',
                        name=f'{level} Events',
                        marker=dict(
                            symbol='diamond',
                            size=12,
                            color=level_colors.get(level, "#777777"),
                            line=dict(width=1, color=self.colors["text"])
                        ),
                        hovertemplate='<b>%{text}</b><br>Time: %{x}<br>Level: ' + level + '<br>Category: %{customdata}',
                        text=[audit_messages[i] for i in indices],
                        customdata=[audit_categories[i] for i in indices]
                    ),
                    row=2, col=1
                )

            # Add category-based stacked area chart
            if audit_events:
                # Generate time series for categories - optimized for large datasets
                category_counts = defaultdict(list)
                NUM_TIME_POINTS = 50  # Number of points for area chart
                time_points = pd.date_range(min_time, max_time, periods=NUM_TIME_POINTS)

                # Convert to numpy for faster calculations
                timestamps_array = np.array([ts.timestamp() for ts in audit_timestamps])
                categories_array = np.array(audit_categories)
                unique_categories = set(audit_categories)

                # Pre-calculate time points as timestamps for faster comparison
                time_points_ts = np.array([t.timestamp() for t in time_points])
                window_seconds = 30 * 60  # 30 minutes in seconds

                for category in unique_categories:
                    counts = []
                    # Create mask for this category
                    category_mask = (categories_array == category)
                    category_timestamps = timestamps_array[category_mask]

                    for t in time_points_ts:
                        # Efficient window calculation using numpy
                        time_diffs = np.abs(category_timestamps - t)
                        in_window = time_diffs <= window_seconds
                        counts.append(np.sum(in_window))

                    category_counts[category] = counts

                # Add stacked area chart
                for category, counts in category_counts.items():
                    fig.add_trace(
                        go.Scatter(
                            x=time_points,
                            y=counts,
                            mode='lines',
                            name=f'{category} Events',
                            line=dict(width=0.5),
                            stackgroup='categories'
                        ),
                        row=2, col=1
                    )

            # Update layout
            fig.update_layout(
                title=title,
                height=800,
                width=1200,
                showlegend=True,
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1
                ),
                paper_bgcolor=self.colors["background"],
                plot_bgcolor=self.colors["background"],
                font=dict(
                    family="Arial, sans-serif",
                    size=12,
                    color=self.colors["text"]
                )
            )

            # Configure y-axes
            fig.update_yaxes(title_text="Duration (s)", row=1, col=1)
            fig.update_yaxes(title_text="Event Count", row=2, col=1)

            # Update axes appearance
            fig.update_xaxes(
                showgrid=True,
                gridwidth=1,
                gridcolor=self.colors["grid"],
                linecolor=self.colors["text"]
            )

            fig.update_yaxes(
                showgrid=True,
                gridwidth=1,
                gridcolor=self.colors["grid"],
                linecolor=self.colors["text"]
            )

            # Save if output file specified
            if output_file:
                if output_file.endswith(".html"):
                    fig.write_html(output_file)
                else:
                    fig.write_image(output_file)

            # Show plot if requested
            if show_plot:
                fig.show()

            return fig

        else:
            # Create static visualization with matplotlib
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=figsize, gridspec_kw={'height_ratios': [3, 2]}, sharex=True)

            # Set style
            plt.style.use('seaborn-v0_8-darkgrid' if self.theme == 'dark' else 'seaborn-v0_8-whitegrid')

            # Plot query durations on top subplot
            ax1.plot(query_timestamps, query_durations, 'o-', color=self.colors["vector_search"], linewidth=2, markersize=6, label="Query Duration")
            ax1.set_ylabel('Duration (s)')
            ax1.set_title('Query Performance')
            ax1.grid(True, linestyle='--', alpha=0.7)

            # Handle audit events on bottom subplot
            if audit_events:
                # Create event scatter plot with color coding
                for level in set(audit_levels):
                    indices = [i for i, l in enumerate(audit_levels) if l == level]
                    if not indices:
                        continue

                    ax2.scatter(
                        [audit_timestamps[i] for i in indices],
                        [1] * len(indices),  # All at same y level
                        marker='D',  # Diamond marker
                        s=100,  # Size
                        color=level_colors.get(level, "#777777"),
                        label=f'{level} Events',
                        alpha=0.7,
                        zorder=5  # To ensure markers are on top
                    )

                # Generate stacked area chart of event categories - optimized for large datasets
                if audit_timestamps:
                    category_counts = {}
                    NUM_TIME_POINTS = 50  # Number of points for area chart
                    time_points = pd.date_range(min_time, max_time, periods=NUM_TIME_POINTS)

                    # Convert to numpy for faster calculations
                    timestamps_array = np.array([ts.timestamp() for ts in audit_timestamps])
                    categories_array = np.array(audit_categories)
                    unique_categories = set(audit_categories)

                    # Pre-calculate time points as timestamps for faster comparison
                    time_points_ts = np.array([t.timestamp() for t in time_points])
                    window_seconds = 30 * 60  # 30 minutes in seconds

                    for category in unique_categories:
                        counts = []
                        # Create mask for this category
                        category_mask = (categories_array == category)
                        category_timestamps = timestamps_array[category_mask]

                        for t in time_points_ts:
                            # Efficient window calculation using numpy
                            time_diffs = np.abs(category_timestamps - t)
                            in_window = time_diffs <= window_seconds
                            counts.append(np.sum(in_window))

                        category_counts[category] = counts

                    # Plot stacked area
                    ax2.stackplot(
                        time_points,
                        category_counts.values(),
                        labels=category_counts.keys(),
                        alpha=0.4
                    )

                ax2.set_ylabel('Event Count')
                ax2.set_title('Audit Events by Category')
                ax2.grid(True, linestyle='--', alpha=0.7)
                ax2.legend(loc='upper right', fontsize='small')
            else:
                ax2.text(0.5, 0.5, "No audit events available",
                         ha='center', va='center', transform=ax2.transAxes,
                         fontsize=12, color=self.colors["text"])

            # Format x-axis with date formatter
            ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
            fig.autofmt_xdate()  # Rotate date labels

            # Add annotations for significant events
            if audit_events:
                # Find high-severity events
                high_events = [i for i, level in enumerate(audit_levels)
                               if level in ('ERROR', 'CRITICAL')]

                for i in high_events[:5]:  # Limit to prevent overcrowding
                    ax2.annotate(
                        f"{audit_levels[i]}: {audit_categories[i]}",
                        xy=(audit_timestamps[i], 1),
                        xytext=(0, 20),
                        textcoords='offset points',
                        arrowprops=dict(arrowstyle="->", color=self.colors["text"]),
                        fontsize=8,
                        color=level_colors.get(audit_levels[i], "#777777")
                    )

            # Set main title
            fig.suptitle(title, fontsize=14)

            # Adjust layout
            plt.tight_layout()
            plt.subplots_adjust(top=0.90)

            # Save if output file specified
            if output_file:
                plt.savefig(output_file, dpi=300, bbox_inches='tight')

            # Show plot if requested
            if show_plot:
                plt.show()
            else:
                plt.close(fig)

            return fig

    def analyze_query_audit_correlation(
        self,
        audit_metrics_aggregator,
        time_window: Optional[int] = None,  # in seconds
        title: str = "Query-Audit Correlation Analysis",
        show_plot: bool = True,
        output_file: Optional[str] = None,
        interactive: bool = False,
        figsize: Tuple[int, int] = (14, 10)
    ) -> Optional[Union["Figure", Dict[str, Any], Dict[str, float]]]:
        """
        Analyze correlation between RAG query performance and audit events.

        This method identifies patterns and correlations between security events
        and query performance degradation, helping to detect security-related
        performance impacts.

        Args:
            audit_metrics_aggregator: AuditMetricsAggregator to get audit events from
            time_window: Time window in seconds to include, or None for all time
            title: Plot title
            show_plot: Whether to display the plot
            output_file: Path to save the plot image
            interactive: Whether to create an interactive plot (requires plotly)
            figsize: Figure size (width, height) in inches

        Returns:
            matplotlib.figure.Figure, plotly figure dict, Dict of correlation stats, or None
        """
        if not VISUALIZATION_LIBS_AVAILABLE:
            logging.warning("Visualization libraries not available. Install matplotlib and seaborn.")
            return None

        if interactive and not INTERACTIVE_LIBS_AVAILABLE:
            logging.warning("Interactive plotting libraries not available. Install plotly.")
            interactive = False

        if not self.metrics_collector:
            logging.warning("No query metrics collector set. Use set_metrics_collector() first.")
            return None

        if audit_metrics_aggregator is None:
            logging.warning("No audit metrics aggregator provided.")
            return None

        # Get query metrics
        metrics_list = list(self.metrics_collector.query_metrics)

        if not metrics_list:
            logging.warning("No query metrics available for correlation analysis.")
            return None

        # Get audit metrics with efficient batch retrieval
        audit_events = audit_metrics_aggregator.get_recent_events(
            hours_back=time_window // 3600 if time_window else 24,
            include_details=True,
            max_events=1000  # Limit to prevent memory issues with very large datasets
        )

        if not audit_events:
            logging.warning("No audit events available for correlation analysis.")
            return None

        # Filter query metrics by time window if specified
        if time_window:
            current_time = time.time()
            cutoff_time = current_time - time_window
            metrics_list = [m for m in metrics_list if m.get("start_time", 0) >= cutoff_time]

        # Sort by timestamp
        metrics_list.sort(key=lambda x: x.get("start_time", 0))

        # Extract time series data with timestamps
        query_timestamps = [m.get("start_time", 0) for m in metrics_list]
        query_durations = [m.get("duration", 0) for m in metrics_list]
        query_results = [m.get("results", {}).get("count", 0) for m in metrics_list]
        query_quality = [m.get("results", {}).get("quality_score", 0) for m in metrics_list]

        # Extract audit event data with timestamps
        audit_timestamps = [e["timestamp"] for e in audit_events]

        # Split audit events by severity
        error_timestamps = [e["timestamp"] for e in audit_events if e["level"] in ("ERROR", "CRITICAL")]
        warning_timestamps = [e["timestamp"] for e in audit_events if e["level"] == "WARNING"]

        # Compute time-based metrics

        # 1. Time-binned metrics (create bins of fixed duration)
        BIN_SIZE = 300  # 5 minute bins
        bin_edges = []
        min_time = min(min(query_timestamps), min(audit_timestamps))
        max_time = max(max(query_timestamps), max(audit_timestamps))
        current_bin = min_time

        while current_bin <= max_time:
            bin_edges.append(current_bin)
            current_bin += BIN_SIZE

        # Create bins for queries
        binned_query_durations = [[] for _ in range(len(bin_edges) - 1)]
        binned_query_results = [[] for _ in range(len(bin_edges) - 1)]
        binned_query_quality = [[] for _ in range(len(bin_edges) - 1)]

        for i, timestamp in enumerate(query_timestamps):
            for bin_idx in range(len(bin_edges) - 1):
                if bin_edges[bin_idx] <= timestamp < bin_edges[bin_idx + 1]:
                    binned_query_durations[bin_idx].append(query_durations[i])
                    binned_query_results[bin_idx].append(query_results[i])
                    binned_query_quality[bin_idx].append(query_quality[i])
                    break

        # Calculate bin statistics
        bin_avg_duration = []
        bin_avg_results = []
        bin_avg_quality = []
        bin_centers = []

        for bin_idx in range(len(bin_edges) - 1):
            durations = binned_query_durations[bin_idx]
            results = binned_query_results[bin_idx]
            qualities = binned_query_quality[bin_idx]

            bin_centers.append((bin_edges[bin_idx] + bin_edges[bin_idx+1]) / 2)
            bin_avg_duration.append(np.mean(durations) if durations else None)
            bin_avg_results.append(np.mean(results) if results else None)
            bin_avg_quality.append(np.mean(qualities) if qualities else None)

        # Count events per bin
        binned_error_events = np.zeros(len(bin_edges) - 1)
        binned_warning_events = np.zeros(len(bin_edges) - 1)

        for timestamp in error_timestamps:
            for bin_idx in range(len(bin_edges) - 1):
                if bin_edges[bin_idx] <= timestamp < bin_edges[bin_idx + 1]:
                    binned_error_events[bin_idx] += 1
                    break

        for timestamp in warning_timestamps:
            for bin_idx in range(len(bin_edges) - 1):
                if bin_edges[bin_idx] <= timestamp < bin_edges[bin_idx + 1]:
                    binned_warning_events[bin_idx] += 1
                    break

        # 2. Compute correlations
        # Remove None values for correlation calculation
        valid_bins = []
        valid_durations = []
        valid_errors = []
        valid_warnings = []

        for i, duration in enumerate(bin_avg_duration):
            if duration is not None:
                valid_bins.append(i)
                valid_durations.append(duration)
                valid_errors.append(binned_error_events[i])
                valid_warnings.append(binned_warning_events[i])

        # Calculate correlations if we have enough data points
        correlations = {}
        if len(valid_durations) >= 3:
            correlations["duration_error_correlation"] = np.corrcoef(valid_durations, valid_errors)[0, 1]
            correlations["duration_warning_correlation"] = np.corrcoef(valid_durations, valid_warnings)[0, 1]

            # Create normalized versions for plotting
            norm_durations = (valid_durations - np.min(valid_durations)) / (np.max(valid_durations) - np.min(valid_durations)) if np.max(valid_durations) > np.min(valid_durations) else valid_durations
            norm_errors = (valid_errors - np.min(valid_errors)) / (np.max(valid_errors) - np.min(valid_errors)) if np.max(valid_errors) > np.min(valid_errors) else valid_errors
            norm_warnings = (valid_warnings - np.min(valid_warnings)) / (np.max(valid_warnings) - np.min(valid_warnings)) if np.max(valid_warnings) > np.min(valid_warnings) else valid_warnings
        else:
            correlations["duration_error_correlation"] = None
            correlations["duration_warning_correlation"] = None
            norm_durations = valid_durations
            norm_errors = valid_errors
            norm_warnings = valid_warnings

        # Calculate lag correlations (how events affect future performance)
        LAG_STEPS = min(5, len(valid_bins) // 2)  # Use at most 5 lag steps or half the bins
        if len(valid_durations) > LAG_STEPS + 1:
            lag_correlations = []
            for lag in range(1, LAG_STEPS + 1):
                # Errors lead durations by 'lag' time bins
                error_lagged = valid_errors[:-lag]
                duration_lagged = valid_durations[lag:]
                if len(error_lagged) >= 2:  # Need at least 2 points for correlation
                    lag_corr = np.corrcoef(error_lagged, duration_lagged)[0, 1]
                    lag_correlations.append((lag, lag_corr))

            if lag_correlations:
                # Find the lag with maximum correlation
                max_lag, max_corr = max(lag_correlations, key=lambda x: abs(x[1]) if not np.isnan(x[1]) else 0)
                correlations["max_lag_correlation"] = max_corr
                correlations["max_lag_bins"] = max_lag
                correlations["max_lag_time"] = max_lag * BIN_SIZE  # Convert to seconds

        # Create visualization of correlations
        if interactive:
            # Create interactive correlation visualization with plotly
            fig = make_subplots(
                rows=2, cols=2,
                subplot_titles=(
                    "Performance & Security Events Timeline",
                    "Correlation Analysis",
                    "Performance Metrics Distribution",
                    "Lag Correlation Analysis"
                ),
                specs=[
                    [{"colspan": 2}, None],
                    [{"type": "xy"}, {"type": "xy"}]
                ],
                vertical_spacing=0.1,
                horizontal_spacing=0.05
            )

            # Add performance timeline (top plot)
            # Convert bin centers to datetime for better readability
            bin_center_dates = [datetime.datetime.fromtimestamp(t) for t in bin_centers]

            # Add query duration line
            fig.add_trace(
                go.Scatter(
                    x=bin_center_dates,
                    y=bin_avg_duration,
                    mode='lines+markers',
                    name='Query Duration (s)',
                    line=dict(color=self.colors["vector_search"], width=2),
                    hovertemplate='Time: %{x}<br>Avg Duration: %{y:.3f}s'
                ),
                row=1, col=1
            )

            # Add error events bars
            fig.add_trace(
                go.Bar(
                    x=bin_center_dates,
                    y=binned_error_events,
                    name='Error Events',
                    marker_color=self.colors["error"],
                    hovertemplate='Time: %{x}<br>Error Events: %{y}'
                ),
                row=1, col=1
            )

            # Add warning events bars
            fig.add_trace(
                go.Bar(
                    x=bin_center_dates,
                    y=binned_warning_events,
                    name='Warning Events',
                    marker_color='orange',
                    hovertemplate='Time: %{x}<br>Warning Events: %{y}'
                ),
                row=1, col=1
            )

            # Add scatter plot of errors vs duration (correlation plot)
            fig.add_trace(
                go.Scatter(
                    x=valid_errors,
                    y=valid_durations,
                    mode='markers',
                    name='Error-Duration Correlation',
                    marker=dict(
                        size=10,
                        color=self.colors["error"],
                        opacity=0.7
                    ),
                    hovertemplate='Errors: %{x}<br>Duration: %{y:.3f}s'
                ),
                row=2, col=1
            )

            # Add regression line if we have correlation
            if len(valid_durations) >= 3 and 'duration_error_correlation' in correlations and correlations['duration_error_correlation'] is not None:
                # Compute regression line
                z = np.polyfit(valid_errors, valid_durations, 1)
                p = np.poly1d(z)
                x_range = np.linspace(min(valid_errors), max(valid_errors), 100)

                fig.add_trace(
                    go.Scatter(
                        x=x_range,
                        y=p(x_range),
                        mode='lines',
                        line=dict(color='red', width=2, dash='dash'),
                        name=f'Correlation: {correlations["duration_error_correlation"]:.2f}',
                        hoverinfo='skip'
                    ),
                    row=2, col=1
                )

            # Add lag correlation analysis if available
            if 'max_lag_correlation' in correlations and correlations['max_lag_correlation'] is not None:
                lag_labels = [f"Lag {i} ({i*BIN_SIZE/60:.1f}min)" for i in range(1, LAG_STEPS + 1)]
                lag_values = [corr for _, corr in lag_correlations]

                fig.add_trace(
                    go.Bar(
                        x=lag_labels,
                        y=lag_values,
                        name='Lag Correlations',
                        marker_color=[
                            'red' if val < -0.3 else
                            'orange' if val < 0 else
                            'green' if val > 0.3 else
                            'lightgreen'
                            for val in lag_values
                        ],
                        hovertemplate='%{x}<br>Correlation: %{y:.3f}'
                    ),
                    row=2, col=2
                )

                # Highlight the strongest correlation
                fig.add_annotation(
                    x=lag_labels[max_lag-1],
                    y=max_corr,
                    text=f"Max: {max_corr:.2f}",
                    showarrow=True,
                    arrowhead=1,
                    ax=0,
                    ay=-40,
                    row=2,
                    col=2
                )
            else:
                fig.add_annotation(
                    x=0.5,
                    y=0.5,
                    text="Insufficient data for lag correlation",
                    showarrow=False,
                    xref="paper",
                    yref="paper",
                    row=2,
                    col=2
                )

            # Update layout
            fig.update_layout(
                title=title,
                height=800,
                width=1200,
                showlegend=True,
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1
                ),
                barmode='overlay',
                paper_bgcolor=self.colors["background"],
                plot_bgcolor=self.colors["background"],
                font=dict(
                    family="Arial, sans-serif",
                    size=12,
                    color=self.colors["text"]
                )
            )

            # Update axis labels
            fig.update_xaxes(title_text="Time", row=1, col=1)
            fig.update_yaxes(title_text="Duration / Event Count", row=1, col=1)
            fig.update_xaxes(title_text="Error Events", row=2, col=1)
            fig.update_yaxes(title_text="Query Duration (s)", row=2, col=1)
            fig.update_xaxes(title_text="Lag Period", row=2, col=2)
            fig.update_yaxes(title_text="Correlation Strength", row=2, col=2)

            # Update axes appearance
            fig.update_xaxes(
                showgrid=True,
                gridwidth=1,
                gridcolor=self.colors["grid"],
                linecolor=self.colors["text"]
            )

            fig.update_yaxes(
                showgrid=True,
                gridwidth=1,
                gridcolor=self.colors["grid"],
                linecolor=self.colors["text"]
            )

            # Save if output file specified
            if output_file:
                if output_file.endswith(".html"):
                    fig.write_html(output_file)
                else:
                    fig.write_image(output_file)

            # Show plot if requested
            if show_plot:
                fig.show()

            # Return the figure and correlation stats
            return {
                "figure": fig,
                "correlations": correlations
            }

        else:
            # Create static correlation visualization with matplotlib
            fig = plt.figure(figsize=figsize)
            gs = plt.GridSpec(2, 2, height_ratios=[3, 2], width_ratios=[2, 1])

            # Timeline plot (top)
            ax1 = fig.add_subplot(gs[0, :])
            ax2 = fig.add_subplot(gs[1, 0])  # Correlation plot
            ax3 = fig.add_subplot(gs[1, 1])  # Lag correlation

            # Set style
            plt.style.use('seaborn-v0_8-darkgrid' if self.theme == 'dark' else 'seaborn-v0_8-whitegrid')

            # Plot timeline on top subplot
            bin_center_dates = [datetime.datetime.fromtimestamp(t) for t in bin_centers]

            # Query duration line
            duration_line = ax1.plot(bin_center_dates, bin_avg_duration, 'o-',
                              color=self.colors["vector_search"],
                              linewidth=2,
                              label="Query Duration (s)")

            # Create secondary y-axis for event counts
            ax1_events = ax1.twinx()
            error_bars = ax1_events.bar(bin_center_dates, binned_error_events,
                             color=self.colors["error"], alpha=0.5,
                             label="Error Events", width=datetime.timedelta(seconds=BIN_SIZE*0.4))
            warning_bars = ax1_events.bar(bin_center_dates, binned_warning_events,
                               color='orange', alpha=0.5,
                               label="Warning Events", width=datetime.timedelta(seconds=BIN_SIZE*0.4))

            # Set labels
            ax1.set_ylabel('Query Duration (s)')
            ax1_events.set_ylabel('Event Count')
            ax1.set_title('Performance & Security Events Timeline')

            # Combine legends from both y-axes
            handles1, labels1 = ax1.get_legend_handles_labels()
            handles2, labels2 = ax1_events.get_legend_handles_labels()
            ax1.legend(handles1 + handles2, labels1 + labels2, loc='upper right')

            # Format x-axis
            ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
            ax1.tick_params(axis='x', rotation=30)

            # Correlation plot in bottom-left
            if len(valid_durations) >= 3:
                ax2.scatter(valid_errors, valid_durations, color=self.colors["error"],
                           alpha=0.7, s=80, label="Data Points")

                # Add correlation coefficient
                if 'duration_error_correlation' in correlations and correlations['duration_error_correlation'] is not None:
                    corr = correlations['duration_error_correlation']

                    # Add regression line
                    z = np.polyfit(valid_errors, valid_durations, 1)
                    p = np.poly1d(z)
                    x_range = np.linspace(min(valid_errors), max(valid_errors), 100)

                    ax2.plot(x_range, p(x_range), 'r--', linewidth=2,
                            label=f"Correlation: {corr:.2f}")

                    # Correlation strength text
                    if abs(corr) > 0.7:
                        strength_text = "Strong "
                    elif abs(corr) > 0.3:
                        strength_text = "Moderate "
                    else:
                        strength_text = "Weak "

                    direction_text = "positive" if corr > 0 else "negative"
                    corr_text = f"{strength_text}{direction_text} correlation"
                    ax2.text(0.05, 0.95, corr_text, transform=ax2.transAxes,
                            ha='left', va='top', fontsize=10)
            else:
                ax2.text(0.5, 0.5, "Insufficient data for correlation analysis",
                        transform=ax2.transAxes, ha='center', va='center')

            ax2.set_xlabel('Error Events')
            ax2.set_ylabel('Query Duration (s)')
            ax2.set_title('Correlation Analysis')
            ax2.legend(loc='upper left')

            # Lag correlation plot in bottom-right
            if 'max_lag_correlation' in correlations and correlations['max_lag_correlation'] is not None:
                lag_labels = [f"Lag {i}\n({i*BIN_SIZE/60:.1f}min)" for i in range(1, LAG_STEPS + 1)]
                lag_values = [corr for _, corr in lag_correlations]

                # Color bars based on correlation strength
                colors = [
                    'red' if val < -0.3 else
                    'orange' if val < 0 else
                    'green' if val > 0.3 else
                    'lightgreen'
                    for val in lag_values
                ]

                ax3.bar(lag_labels, lag_values, color=colors)

                # Mark the maximum correlation
                max_lag, max_corr = max(lag_correlations, key=lambda x: abs(x[1]) if not np.isnan(x[1]) else 0)
                ax3.annotate(f"Max: {max_corr:.2f}",
                            xy=(lag_labels[max_lag-1], max_corr),
                            xytext=(0, 10), textcoords='offset points',
                            ha='center', va='bottom',
                            arrowprops=dict(arrowstyle="->", color=self.colors["text"]))

                ax3.set_ylabel('Correlation Strength')
                ax3.set_title('Lag Correlation Analysis')

                # Add horizontal line at zero
                ax3.axhline(y=0, color='gray', linestyle='-', linewidth=1)

                # Set y limits with padding
                y_max = max(abs(min(lag_values)), abs(max(lag_values))) * 1.2
                ax3.set_ylim(-y_max, y_max)
            else:
                ax3.text(0.5, 0.5, "Insufficient data for lag analysis",
                        transform=ax3.transAxes, ha='center', va='center')

            # Add correlation statistics as text
            corr_text = "Correlation Statistics:\n"
            if 'duration_error_correlation' in correlations and correlations['duration_error_correlation'] is not None:
                corr_text += f"• Error-Duration: {correlations['duration_error_correlation']:.2f}\n"
            if 'duration_warning_correlation' in correlations and correlations['duration_warning_correlation'] is not None:
                corr_text += f"• Warning-Duration: {correlations['duration_warning_correlation']:.2f}\n"
            if 'max_lag_correlation' in correlations and correlations['max_lag_correlation'] is not None:
                corr_text += f"• Max Lag Correlation: {correlations['max_lag_correlation']:.2f} at {correlations['max_lag_time']/60:.1f} minutes"

            fig.text(0.02, 0.01, corr_text, fontsize=9,
                    bbox=dict(facecolor='white', alpha=0.8, boxstyle='round,pad=0.5'))

            # Set main title
            fig.suptitle(title, fontsize=14)

            # Adjust layout
            plt.tight_layout()
            plt.subplots_adjust(top=0.92)

            # Save if output file specified
            if output_file:
                plt.savefig(output_file, dpi=300, bbox_inches='tight')

            # Show plot if requested
            if show_plot:
                plt.show()
            else:
                plt.close(fig)

            # Return the figure and correlation stats
            return {
                "figure": fig,
                "correlations": correlations
            }

# For testing
if __name__ == "__main__":
    import tempfile

    # Create test directory
    temp_dir = tempfile.mkdtemp()
    print(f"Test directory: {temp_dir}")

    # Create metrics collector
    metrics_collector = QueryMetricsCollector()

    # Create visualizer
    visualizer = EnhancedQueryAuditVisualizer(
        metrics_collector=metrics_collector,
        dashboard_dir=temp_dir
    )

    print("Created visualizer with methods:")
    print([method for method in dir(visualizer) if not method.startswith('_')])

    # Check if our method exists
    if hasattr(visualizer, 'visualize_query_audit_metrics'):
        print("visualize_query_audit_metrics method exists!")
    else:
        print("visualize_query_audit_metrics method not found!")
