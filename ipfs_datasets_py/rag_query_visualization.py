"""
RAG Query Visualization Module

This module provides visualization and analytics for RAG queries, enabling performance
analysis, trend detection, and integration with the security and audit systems for 
comprehensive monitoring of query patterns and anomalies.
"""

import os
import json
import time
import logging
import datetime
import threading
from collections import Counter, defaultdict
from typing import Dict, List, Any, Optional, Tuple, Union, Callable, Set

# Add UTC import to fix deprecation warnings
# Python 3.11+ supports datetime.UTC directly, older versions need to use timezone.utc
try:
    from datetime import UTC  # Python 3.11+
except ImportError:
    from datetime import timezone
    UTC = timezone.utc

try:
    import numpy as np
    import pandas as pd
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import MaxNLocator
    import seaborn as sns
    VISUALIZATION_LIBS_AVAILABLE = True
except ImportError:
    VISUALIZATION_LIBS_AVAILABLE = False

try:
    import plotly.graph_objects as go
    import plotly.express as px
    from plotly.subplots import make_subplots
    INTERACTIVE_VISUALIZATION_AVAILABLE = True
except ImportError:
    INTERACTIVE_VISUALIZATION_AVAILABLE = False

try:
    from jinja2 import Template
    TEMPLATE_ENGINE_AVAILABLE = True
except ImportError:
    TEMPLATE_ENGINE_AVAILABLE = False

from ipfs_datasets_py.audit.audit_visualization import create_query_audit_timeline


class QueryMetricsCollector:
    """
    Collects and analyzes metrics for RAG queries.
    
    This class records detailed metrics about query execution, including timing data,
    query parameters, and results. It provides methods for analyzing query performance,
    detecting anomalies, and generating statistical summaries.
    """
    
    def __init__(self, window_size=3600):
        """
        Initialize the metrics collector.
        
        Args:
            window_size (int): Time window for metrics in seconds (default: 1 hour)
        """
        self.query_metrics = {}  # Store metrics by query ID
        self.window_size = window_size  # Time window for analysis in seconds
        self.current_queries = set()  # Currently executing queries
        self.anomaly_thresholds = {
            'duration': 5.0,  # Seconds
            'vector_search_time': 2.0,  # Seconds
            'graph_search_time': 3.0,  # Seconds
            'error_rate': 0.1  # 10% error rate threshold
        }
        self._lock = threading.RLock()  # Thread safety for metrics updates
        
    def record_query_start(self, query_id, query_params):
        """
        Record the start of a query execution.
        
        Args:
            query_id (str): Unique identifier for the query
            query_params (dict): Parameters of the query
        """
        with self._lock:
            start_time = time.time()
            self.query_metrics[query_id] = {
                'start_time': start_time,
                'timestamp': datetime.datetime.fromtimestamp(start_time, UTC),
                'query_params': query_params,
                'status': 'running'
            }
            self.current_queries.add(query_id)
            
    def record_query_end(self, query_id, results=None, error=None, metrics=None):
        """
        Record the end of a query execution with results or error.
        
        Args:
            query_id (str): Unique identifier for the query
            results (list, optional): Query results
            error (str, optional): Error message if query failed
            metrics (dict, optional): Additional metrics from the query execution
        """
        with self._lock:
            end_time = time.time()
            
            # Check if query exists in metrics
            if query_id not in self.query_metrics:
                # Create a minimal record if query wasn't started properly
                self.query_metrics[query_id] = {
                    'start_time': end_time,  # Use end time as fallback
                    'timestamp': datetime.datetime.fromtimestamp(end_time, UTC),
                    'query_params': {},
                    'status': 'unknown'
                }
            
            # Update the query record
            query_data = self.query_metrics[query_id]
            query_data['end_time'] = end_time
            
            # Calculate duration
            start_time = query_data.get('start_time', end_time)
            query_data['duration'] = end_time - start_time
            
            # Update status and results
            if error:
                query_data['status'] = 'error'
                query_data['error'] = error
                query_data['results_count'] = 0
            else:
                query_data['status'] = 'completed'
                query_data['results'] = results or []
                query_data['results_count'] = len(results) if results else 0
            
            # Add any additional metrics
            if metrics:
                query_data.update(metrics)
                
            # Remove from current queries set
            if query_id in self.current_queries:
                self.current_queries.remove(query_id)
                
            # Check for anomalies after recording metrics
            self._check_for_anomalies(query_id, query_data)
            
    def get_performance_metrics(self, time_window=None):
        """
        Get performance metrics based on recorded queries.
        
        Args:
            time_window (int, optional): Time window in seconds, defaults to instance window_size
            
        Returns:
            dict: Performance metrics and statistics
        """
        with self._lock:
            current_time = time.time()
            window = time_window or self.window_size
            cutoff_time = current_time - window
            
            # Filter queries by time window
            recent_queries = {
                qid: data for qid, data in self.query_metrics.items()
                if data.get('start_time', 0) >= cutoff_time
            }
            
            if not recent_queries:
                return {
                    'total_queries': 0,
                    'completed_queries': 0,
                    'error_queries': 0,
                    'success_rate': 0,
                    'avg_duration': 0,
                    'avg_results': 0,
                    'hourly_trends': {},
                    'current_queries': len(self.current_queries)
                }
            
            # Calculate basic metrics
            total_queries = len(recent_queries)
            completed_queries = sum(1 for q in recent_queries.values() if q.get('status') == 'completed')
            error_queries = sum(1 for q in recent_queries.values() if q.get('status') == 'error')
            
            # Calculate derived metrics
            success_rate = completed_queries / total_queries if total_queries > 0 else 0
            avg_duration = np.mean([q.get('duration', 0) for q in recent_queries.values()])
            avg_results = np.mean([q.get('results_count', 0) for q in recent_queries.values()])
            
            # Calculate hourly trends
            hourly_trends = self._calculate_hourly_trends(recent_queries)
            
            # Return comprehensive metrics
            return {
                'total_queries': total_queries,
                'completed_queries': completed_queries,
                'error_queries': error_queries,
                'success_rate': success_rate,
                'avg_duration': avg_duration,
                'avg_results': avg_results,
                'hourly_trends': hourly_trends,
                'current_queries': len(self.current_queries),
                'peak_duration': max((q.get('duration', 0) for q in recent_queries.values()), default=0),
                'anomalies_detected': sum(1 for q in recent_queries.values() if q.get('is_anomaly', False))
            }
            
    def _calculate_hourly_trends(self, queries):
        """
        Calculate hourly trends from query data.
        
        Args:
            queries (dict): Query data dictionary
            
        Returns:
            dict: Hourly trends statistics
        """
        if not queries:
            return {}
            
        # Extract timestamps and convert to hourly buckets
        hours = {}
        for query_id, data in queries.items():
            timestamp = data.get('timestamp')
            if not timestamp:
                continue
                
            # Create hourly bucket key
            hour_key = timestamp.strftime('%Y-%m-%d %H:00')
            
            if hour_key not in hours:
                hours[hour_key] = {
                    'count': 0,
                    'duration_sum': 0,
                    'success_count': 0,
                    'error_count': 0
                }
                
            # Update bucket stats
            hours[hour_key]['count'] += 1
            hours[hour_key]['duration_sum'] += data.get('duration', 0)
            
            if data.get('status') == 'completed':
                hours[hour_key]['success_count'] += 1
            elif data.get('status') == 'error':
                hours[hour_key]['error_count'] += 1
                
        # Calculate averages for each hour
        for hour, stats in hours.items():
            stats['avg_duration'] = stats['duration_sum'] / stats['count'] if stats['count'] > 0 else 0
            stats['success_rate'] = stats['success_count'] / stats['count'] if stats['count'] > 0 else 0
            
        return hours
        
    def _check_for_anomalies(self, query_id, query_data):
        """
        Check if a query is anomalous based on defined thresholds.
        
        Args:
            query_id (str): Query identifier
            query_data (dict): Query metrics data
        """
        # Initialize anomaly flag
        query_data['is_anomaly'] = False
        anomaly_reasons = []
        
        # Check duration
        if query_data.get('duration', 0) > self.anomaly_thresholds['duration']:
            query_data['is_anomaly'] = True
            anomaly_reasons.append('duration')
            
        # Check vector search time
        if query_data.get('vector_search_time', 0) > self.anomaly_thresholds['vector_search_time']:
            query_data['is_anomaly'] = True
            anomaly_reasons.append('vector_search_time')
            
        # Check graph search time
        if query_data.get('graph_search_time', 0) > self.anomaly_thresholds['graph_search_time']:
            query_data['is_anomaly'] = True
            anomaly_reasons.append('graph_search_time')
            
        # Add anomaly reasons if any were found
        if anomaly_reasons:
            query_data['anomaly_reasons'] = anomaly_reasons
            # Log the anomaly - in a production system this might trigger alerts
            logging.warning(f"Query anomaly detected for {query_id}: {', '.join(anomaly_reasons)}")


class RAGQueryVisualizer:
    """
    Visualizes metrics and performance data for RAG queries.
    
    This class generates various visualizations for analyzing RAG query performance,
    including timelines, histograms, and statistical charts.
    """
    
    def __init__(self, metrics_collector):
        """
        Initialize the query visualizer.
        
        Args:
            metrics_collector (QueryMetricsCollector): Metrics collector with query data
        """
        self.metrics_collector = metrics_collector
        self.default_figsize = (10, 6)
        self.colors = {
            "text": "#333333",
            "background": "#f5f5f5",
            "grid": "#dddddd",
            "completed": "#4caf50",
            "error": "#f44336",
            "running": "#2196f3",
            "anomaly": "#ff9800"
        }
        
    def plot_query_performance(self, time_window=None, figsize=None, output_file=None, show_plot=True):
        """
        Create a performance visualization for RAG queries.
        
        Args:
            time_window (int, optional): Time window in seconds
            figsize (tuple, optional): Figure size (width, height) in inches
            output_file (str, optional): Path to save the visualization
            show_plot (bool): Whether to display the plot
            
        Returns:
            matplotlib.figure.Figure: The generated figure
        """
        if not VISUALIZATION_LIBS_AVAILABLE:
            logging.warning("Visualization libraries not available")
            return None
            
        # Get performance metrics
        metrics = self.metrics_collector.get_performance_metrics(time_window)
        if metrics['total_queries'] == 0:
            logging.warning("No queries available for visualization")
            return None
            
        # Create figure with multiple subplots
        fig, axes = plt.subplots(2, 2, figsize=figsize or self.default_figsize)
        
        # Set figure title
        fig.suptitle('RAG Query Performance Overview', fontsize=16)
        
        # Plot 1: Query counts by status
        ax1 = axes[0, 0]
        status_counts = [
            metrics['completed_queries'],
            metrics['error_queries'],
            metrics['current_queries']
        ]
        status_labels = ['Completed', 'Error', 'Running']
        status_colors = [self.colors['completed'], self.colors['error'], self.colors['running']]
        
        bars = ax1.bar(status_labels, status_counts, color=status_colors)
        ax1.set_title('Query Status Distribution')
        ax1.set_ylabel('Count')
        
        # Add count labels on top of bars
        for bar in bars:
            height = bar.get_height()
            ax1.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                    f'{int(height)}', ha='center', va='bottom')
        
        # Plot 2: Success rate
        ax2 = axes[0, 1]
        success_rate = metrics['success_rate'] * 100  # Convert to percentage
        
        # Create a gauge-like visualization
        ax2.set_title('Query Success Rate')
        ax2.set_aspect('equal')
        
        # Clear axis and set limits
        ax2.clear()
        ax2.set_xlim(0, 10)
        ax2.set_ylim(0, 10)
        
        # Draw a circular gauge
        circle = plt.Circle((5, 5), 4, fill=False, color='#cccccc', linewidth=2)
        ax2.add_artist(circle)
        
        # Add text in the center
        ax2.text(5, 5, f"{success_rate:.1f}%", ha='center', va='center', fontsize=24)
        ax2.text(5, 3.5, "Success Rate", ha='center', va='center', fontsize=12)
        
        # Remove axis ticks and labels
        ax2.set_xticks([])
        ax2.set_yticks([])
        
        # Plot 3: Duration distribution
        ax3 = axes[1, 0]
        
        # Extract durations from queries
        durations = [q.get('duration', 0) for q in self.metrics_collector.query_metrics.values()
                     if 'duration' in q]
        
        if durations:
            # Create histogram
            ax3.hist(durations, bins=10, color=self.colors['completed'], alpha=0.7)
            ax3.set_title('Query Duration Distribution')
            ax3.set_xlabel('Duration (seconds)')
            ax3.set_ylabel('Count')
            
            # Add mean line
            mean_duration = np.mean(durations)
            ax3.axvline(mean_duration, color='red', linestyle='dashed', linewidth=1)
            ax3.text(mean_duration + 0.1, ax3.get_ylim()[1] * 0.9, 
                    f'Mean: {mean_duration:.2f}s', color='red')
        else:
            ax3.text(0.5, 0.5, 'No duration data available', 
                    ha='center', va='center', transform=ax3.transAxes)
        
        # Plot 4: Hourly trends
        ax4 = axes[1, 1]
        
        if metrics['hourly_trends']:
            # Extract data
            hours = list(metrics['hourly_trends'].keys())
            counts = [h['count'] for h in metrics['hourly_trends'].values()]
            
            # Sort by time
            sorted_data = sorted(zip(hours, counts))
            hours, counts = zip(*sorted_data) if sorted_data else ([], [])
            
            # Plot trend
            ax4.plot(hours, counts, marker='o', linestyle='-', color=self.colors['running'])
            ax4.set_title('Query Volume by Hour')
            ax4.set_ylabel('Query Count')
            
            # Rotate x labels for better readability
            plt.setp(ax4.get_xticklabels(), rotation=45, ha='right')
        else:
            ax4.text(0.5, 0.5, 'No hourly trend data available', 
                    ha='center', va='center', transform=ax4.transAxes)
        
        # Adjust layout
        plt.tight_layout(rect=[0, 0, 1, 0.95])  # Adjust for the suptitle
        
        # Save plot if output file is specified
        if output_file:
            plt.savefig(output_file, dpi=300, bbox_inches='tight')
        
        # Show or close the plot
        if show_plot:
            plt.show()
        else:
            plt.close(fig)
            
        return fig
        
    def plot_query_term_frequency(self, max_terms=20, figsize=None, output_file=None, show_plot=True):
        """
        Plot frequency of terms used in queries.
        
        Args:
            max_terms (int): Maximum number of terms to include
            figsize (tuple, optional): Figure size (width, height) in inches
            output_file (str, optional): Path to save the visualization
            show_plot (bool): Whether to display the plot
            
        Returns:
            matplotlib.figure.Figure: The generated figure
        """
        if not VISUALIZATION_LIBS_AVAILABLE:
            logging.warning("Visualization libraries not available")
            return None
            
        # Extract query texts from metrics
        query_texts = []
        for query_data in self.metrics_collector.query_metrics.values():
            query_params = query_data.get('query_params', {})
            if 'query_text' in query_params:
                query_texts.append(query_params['query_text'])
                
        if not query_texts:
            logging.warning("No query texts available for term frequency analysis")
            return None
            
        # Process text to extract terms
        all_terms = []
        for text in query_texts:
            # Simple tokenization by splitting on spaces and removing punctuation
            terms = text.lower().replace('.', ' ').replace(',', ' ').replace('?', ' ').split()
            all_terms.extend(terms)
            
        # Count term frequencies
        term_counts = Counter(all_terms)
        
        # Remove very common words if needed (stopwords)
        stopwords = {'the', 'a', 'an', 'in', 'on', 'at', 'to', 'for', 'with', 'by'}
        for word in stopwords:
            if word in term_counts:
                del term_counts[word]
                
        # Get top terms
        top_terms = term_counts.most_common(max_terms)
        
        if not top_terms:
            logging.warning("No terms found for frequency analysis")
            return None
            
        # Create figure
        fig, ax = plt.subplots(figsize=figsize or (12, 8))
        
        # Extract data for plotting
        terms, counts = zip(*top_terms)
        
        # Create horizontal bar chart
        bars = ax.barh(terms, counts, color=self.colors['running'])
        
        # Add count labels
        for i, bar in enumerate(bars):
            width = bar.get_width()
            ax.text(width + 0.3, bar.get_y() + bar.get_height()/2,
                   f'{int(width)}', ha='left', va='center')
        
        # Set labels and title
        ax.set_title('Most Common Query Terms', fontsize=16)
        ax.set_xlabel('Frequency')
        ax.set_ylabel('Term')
        
        # Adjust layout
        plt.tight_layout()
        
        # Save plot if output file is specified
        if output_file:
            plt.savefig(output_file, dpi=300, bbox_inches='tight')
        
        # Show or close the plot
        if show_plot:
            plt.show()
        else:
            plt.close(fig)
            
        return fig


class EnhancedQueryVisualizer(RAGQueryVisualizer):
    """
    Enhanced version of query visualizer with additional interactive
    and advanced visualization capabilities.
    """
    
    def __init__(self, metrics_collector):
        """
        Initialize the enhanced query visualizer.
        
        Args:
            metrics_collector (QueryMetricsCollector): Metrics collector with query data
        """
        super().__init__(metrics_collector)
        
    def visualize_query_performance_timeline(self, time_window=None, figsize=None, 
                                           output_file=None, show_plot=True):
        """
        Create a timeline visualization of query performance.
        
        Args:
            time_window (int, optional): Time window in seconds
            figsize (tuple, optional): Figure size (width, height) in inches
            output_file (str, optional): Path to save the visualization
            show_plot (bool): Whether to display the plot
            
        Returns:
            matplotlib.figure.Figure: The generated figure
        """
        if not VISUALIZATION_LIBS_AVAILABLE:
            logging.warning("Visualization libraries not available")
            return None
            
        # Extract query data
        queries = self.metrics_collector.query_metrics
        if not queries:
            logging.warning("No queries available for visualization")
            return None
            
        # Filter by time window if specified
        if time_window:
            current_time = time.time()
            cutoff_time = current_time - time_window
            queries = {
                qid: data for qid, data in queries.items()
                if data.get('start_time', 0) >= cutoff_time
            }
            
        if not queries:
            logging.warning("No queries in the specified time window")
            return None
            
        # Extract timestamps and durations
        timestamps = []
        durations = []
        statuses = []
        is_anomaly = []
        
        for query_id, data in queries.items():
            if 'start_time' in data and 'duration' in data:
                timestamp = datetime.datetime.fromtimestamp(data['start_time'])
                timestamps.append(timestamp)
                durations.append(data['duration'])
                statuses.append(data.get('status', 'unknown'))
                is_anomaly.append(data.get('is_anomaly', False))
        
        if not timestamps:
            logging.warning("No valid timestamp/duration data for visualization")
            return None
            
        # Create figure
        fig, ax = plt.subplots(figsize=figsize or (12, 6))
        
        # Define colors for different statuses
        status_colors = {
            'completed': self.colors['completed'],
            'error': self.colors['error'],
            'running': self.colors['running'],
            'unknown': '#999999'
        }
        
        # Create colormap for points
        colors = [
            self.colors['anomaly'] if anom else status_colors.get(status, '#999999')
            for status, anom in zip(statuses, is_anomaly)
        ]
        
        # Create scatter plot
        scatter = ax.scatter(timestamps, durations, c=colors, alpha=0.7, s=50)
        
        # Connect points with line
        ax.plot(timestamps, durations, 'k-', alpha=0.3)
        
        # Set labels and title
        ax.set_title('Query Performance Timeline', fontsize=16)
        ax.set_xlabel('Time')
        ax.set_ylabel('Duration (seconds)')
        
        # Format x-axis as dates
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))
        plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
        
        # Create legend
        legend_elements = [
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor=self.colors['completed'], 
                      label='Completed', markersize=10),
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor=self.colors['error'], 
                      label='Error', markersize=10),
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor=self.colors['running'], 
                      label='Running', markersize=10),
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor=self.colors['anomaly'], 
                      label='Anomaly', markersize=10)
        ]
        ax.legend(handles=legend_elements, loc='best')
        
        # Add trendline
        if len(timestamps) > 1:
            try:
                # Convert timestamps to numeric values for regression
                time_nums = mdates.date2num(timestamps)
                z = np.polyfit(time_nums, durations, 1)
                p = np.poly1d(z)
                
                # Add trendline to plot
                ax.plot(timestamps, p(time_nums), "r--", alpha=0.8, label="Trend")
                
                # Calculate trend direction
                trend_direction = 'increasing' if z[0] > 0 else 'decreasing'
                trend_text = f"Trend: {trend_direction} ({z[0]:.6f})"
                ax.text(0.02, 0.95, trend_text, transform=ax.transAxes, 
                       fontsize=10, verticalalignment='top')
            except Exception as e:
                logging.warning(f"Error calculating trendline: {str(e)}")
        
        # Adjust layout
        plt.tight_layout()
        
        # Save plot if output file is specified
        if output_file:
            plt.savefig(output_file, dpi=300, bbox_inches='tight')
        
        # Show or close the plot
        if show_plot:
            plt.show()
        else:
            plt.close(fig)
            
        return fig
        
    def create_interactive_dashboard(self, output_dir, time_window=None):
        """
        Create an interactive HTML dashboard with multiple visualizations.
        
        Args:
            output_dir (str): Directory to save dashboard files
            time_window (int, optional): Time window in seconds
            
        Returns:
            str: Path to the generated dashboard HTML file
        """
        if not TEMPLATE_ENGINE_AVAILABLE or not INTERACTIVE_VISUALIZATION_AVAILABLE:
            logging.warning("Interactive dashboard requires Jinja2 and Plotly")
            return None
            
        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        
        # Generate performance metrics
        metrics = self.metrics_collector.get_performance_metrics(time_window)
        
        # Create interactive plots
        plots = {}
        
        # 1. Timeline plot
        queries = self.metrics_collector.query_metrics
        if queries:
            # Extract timestamps and durations
            data = []
            for query_id, query_data in queries.items():
                if 'start_time' in query_data and 'duration' in query_data:
                    timestamp = datetime.datetime.fromtimestamp(query_data['start_time'])
                    duration = query_data['duration']
                    status = query_data.get('status', 'unknown')
                    is_anomaly = query_data.get('is_anomaly', False)
                    
                    data.append({
                        'timestamp': timestamp,
                        'duration': duration,
                        'status': status,
                        'is_anomaly': is_anomaly,
                        'query_id': query_id,
                        'query_text': query_data.get('query_params', {}).get('query_text', 'Unknown')
                    })
            
            if data:
                # Create DataFrame
                df = pd.DataFrame(data)
                
                # Create color mapping
                df['color'] = df.apply(
                    lambda row: self.colors['anomaly'] if row['is_anomaly'] else 
                                self.colors.get(row['status'], '#999999'),
                    axis=1
                )
                
                # Create hover text
                df['hover_text'] = df.apply(
                    lambda row: f"Query: {row['query_text']}<br>" +
                                f"ID: {row['query_id']}<br>" +
                                f"Duration: {row['duration']:.3f}s<br>" +
                                f"Status: {row['status']}<br>" +
                                f"Anomaly: {'Yes' if row['is_anomaly'] else 'No'}",
                    axis=1
                )
                
                # Create figure
                fig = go.Figure()
                
                # Add scatter plot
                fig.add_trace(go.Scatter(
                    x=df['timestamp'],
                    y=df['duration'],
                    mode='markers+lines',
                    marker=dict(
                        size=10,
                        color=df['color'],
                        opacity=0.7
                    ),
                    line=dict(
                        color='rgba(0,0,0,0.3)',
                        width=1
                    ),
                    text=df['hover_text'],
                    hoverinfo='text'
                ))
                
                # Update layout
                fig.update_layout(
                    title='Query Performance Timeline',
                    xaxis_title='Time',
                    yaxis_title='Duration (seconds)',
                    template='plotly_white'
                )
                
                # Save to HTML
                timeline_path = os.path.join(output_dir, 'timeline.html')
                fig.write_html(timeline_path)
                plots['timeline'] = 'timeline.html'
        
        # 2. Query status distribution
        status_counts = {
            'Completed': metrics['completed_queries'],
            'Error': metrics['error_queries'],
            'Running': metrics['current_queries'],
            'Anomaly': metrics.get('anomalies_detected', 0)
        }
        
        status_colors = {
            'Completed': self.colors['completed'],
            'Error': self.colors['error'],
            'Running': self.colors['running'],
            'Anomaly': self.colors['anomaly']
        }
        
        fig = go.Figure(data=[
            go.Bar(
                x=list(status_counts.keys()),
                y=list(status_counts.values()),
                marker_color=list(status_colors.values())
            )
        ])
        
        fig.update_layout(
            title='Query Status Distribution',
            xaxis_title='Status',
            yaxis_title='Count',
            template='plotly_white'
        )
        
        status_path = os.path.join(output_dir, 'status.html')
        fig.write_html(status_path)
        plots['status'] = 'status.html'
        
        # Create dashboard HTML
        dashboard_template = Template('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>RAG Query Performance Dashboard</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }
                .header { background-color: #2196F3; color: white; padding: 20px; margin-bottom: 20px; border-radius: 5px; }
                .metrics { display: flex; flex-wrap: wrap; margin-bottom: 20px; }
                .metric-card { background-color: white; border-radius: 5px; box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                              padding: 15px; margin: 10px; min-width: 200px; flex: 1; }
                .metric-value { font-size: 24px; font-weight: bold; margin-top: 10px; }
                .plot-container { background-color: white; border-radius: 5px; box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                                 padding: 15px; margin-bottom: 20px; }
                iframe { border: none; width: 100%; height: 500px; }
            </style>
        </head>
        <body>
            <div class="header">
                <h1>RAG Query Performance Dashboard</h1>
                <p>Generated: {{ timestamp }}</p>
            </div>
            
            <div class="metrics">
                <div class="metric-card">
                    <h3>Total Queries</h3>
                    <div class="metric-value">{{ metrics.total_queries }}</div>
                </div>
                <div class="metric-card">
                    <h3>Success Rate</h3>
                    <div class="metric-value">{{ "%.1f"|format(metrics.success_rate * 100) }}%</div>
                </div>
                <div class="metric-card">
                    <h3>Avg Duration</h3>
                    <div class="metric-value">{{ "%.3f"|format(metrics.avg_duration) }}s</div>
                </div>
                <div class="metric-card">
                    <h3>Anomalies</h3>
                    <div class="metric-value">{{ metrics.anomalies_detected|default(0) }}</div>
                </div>
            </div>
            
            {% for name, file in plots.items() %}
            <div class="plot-container">
                <h2>{{ name|capitalize }}</h2>
                <iframe src="{{ file }}"></iframe>
            </div>
            {% endfor %}
        </body>
        </html>
        ''')
        
        # Render template
        dashboard_html = dashboard_template.render(
            timestamp=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            metrics=metrics,
            plots=plots
        )
        
        # Write dashboard file
        dashboard_path = os.path.join(output_dir, 'dashboard.html')
        with open(dashboard_path, 'w') as f:
            f.write(dashboard_html)
            
        return dashboard_path


class RAGQueryDashboard:
    """
    Interactive dashboard for monitoring and analyzing RAG query performance.
    
    This class integrates query metrics, visualization, and audit logs to
    provide a comprehensive monitoring system.
    """
    
    def __init__(self, metrics_collector, visualizer=None, dashboard_dir=None, audit_logger=None):
        """
        Initialize the RAG query dashboard.
        
        Args:
            metrics_collector (QueryMetricsCollector): Query metrics collector
            visualizer (EnhancedQueryVisualizer, optional): Query visualizer
            dashboard_dir (str, optional): Directory for dashboard files
            audit_logger (object, optional): Audit logger for security events
        """
        self.metrics_collector = metrics_collector
        self.visualizer = visualizer or EnhancedQueryVisualizer(metrics_collector)
        self.dashboard_dir = dashboard_dir or os.path.join(tempfile.gettempdir(), 'rag_dashboard')
        self.audit_logger = audit_logger
        
        # Create dashboard directory if it doesn't exist
        os.makedirs(self.dashboard_dir, exist_ok=True)
        
    def generate_dashboard(self, time_window=None):
        """
        Generate the query monitoring dashboard.
        
        Args:
            time_window (int, optional): Time window in seconds
            
        Returns:
            str: Path to the generated dashboard
        """
        return self.visualizer.create_interactive_dashboard(
            self.dashboard_dir, time_window=time_window
        )
        
    def generate_performance_report(self, output_file=None, time_window=None):
        """
        Generate a comprehensive performance report with visualizations.
        
        Args:
            output_file (str, optional): Output file path
            time_window (int, optional): Time window in seconds
            
        Returns:
            str: Path to the generated report
        """
        # Get metrics
        metrics = self.metrics_collector.get_performance_metrics(time_window)
        
        # Default output file
        if not output_file:
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = os.path.join(self.dashboard_dir, f'performance_report_{timestamp}.html')
            
        # Create report directory
        report_dir = os.path.dirname(output_file)
        os.makedirs(report_dir, exist_ok=True)
        
        # Generate visualizations
        plot_files = {}
        
        # Timeline plot
        timeline_path = os.path.join(report_dir, 'timeline.png')
        self.visualizer.visualize_query_performance_timeline(
            time_window=time_window,
            output_file=timeline_path,
            show_plot=False
        )
        if os.path.exists(timeline_path):
            plot_files['timeline'] = os.path.basename(timeline_path)
            
        # Performance plot
        performance_path = os.path.join(report_dir, 'performance.png')
        self.visualizer.plot_query_performance(
            time_window=time_window,
            output_file=performance_path,
            show_plot=False
        )
        if os.path.exists(performance_path):
            plot_files['performance'] = os.path.basename(performance_path)
            
        # Term frequency plot
        terms_path = os.path.join(report_dir, 'terms.png')
        self.visualizer.plot_query_term_frequency(
            output_file=terms_path,
            show_plot=False
        )
        if os.path.exists(terms_path):
            plot_files['terms'] = os.path.basename(terms_path)
            
        # Generate HTML report
        report_template = Template('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>RAG Query Performance Report</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 0; padding: 20px; }
                .header { background-color: #2196F3; color: white; padding: 20px; margin-bottom: 20px; }
                .section { margin-bottom: 30px; }
                .metrics-table { width: 100%; border-collapse: collapse; }
                .metrics-table th, .metrics-table td { padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }
                .metrics-table th { background-color: #f2f2f2; }
                .plot-container { margin: 20px 0; }
                .plot-container img { max-width: 100%; height: auto; }
            </style>
        </head>
        <body>
            <div class="header">
                <h1>RAG Query Performance Report</h1>
                <p>Generated: {{ timestamp }}</p>
                <p>Time Window: {{ time_window_text }}</p>
            </div>
            
            <div class="section">
                <h2>Performance Metrics</h2>
                <table class="metrics-table">
                    <tr>
                        <th>Metric</th>
                        <th>Value</th>
                    </tr>
                    <tr>
                        <td>Total Queries</td>
                        <td>{{ metrics.total_queries }}</td>
                    </tr>
                    <tr>
                        <td>Completed Queries</td>
                        <td>{{ metrics.completed_queries }}</td>
                    </tr>
                    <tr>
                        <td>Error Queries</td>
                        <td>{{ metrics.error_queries }}</td>
                    </tr>
                    <tr>
                        <td>Success Rate</td>
                        <td>{{ "%.1f"|format(metrics.success_rate * 100) }}%</td>
                    </tr>
                    <tr>
                        <td>Average Duration</td>
                        <td>{{ "%.3f"|format(metrics.avg_duration) }} seconds</td>
                    </tr>
                    <tr>
                        <td>Average Results</td>
                        <td>{{ "%.1f"|format(metrics.avg_results) }}</td>
                    </tr>
                    <tr>
                        <td>Peak Duration</td>
                        <td>{{ "%.3f"|format(metrics.peak_duration) }} seconds</td>
                    </tr>
                    <tr>
                        <td>Anomalies Detected</td>
                        <td>{{ metrics.anomalies_detected|default(0) }}</td>
                    </tr>
                </table>
            </div>
            
            {% for name, file in plot_files.items() %}
            <div class="section">
                <h2>{{ name|capitalize }} Visualization</h2>
                <div class="plot-container">
                    <img src="{{ file }}" alt="{{ name }} visualization">
                </div>
            </div>
            {% endfor %}
            
            <div class="section">
                <h2>Hourly Trends</h2>
                <table class="metrics-table">
                    <tr>
                        <th>Hour</th>
                        <th>Query Count</th>
                        <th>Avg Duration</th>
                        <th>Success Rate</th>
                    </tr>
                    {% for hour, stats in hourly_trends|dictsort %}
                    <tr>
                        <td>{{ hour }}</td>
                        <td>{{ stats.count }}</td>
                        <td>{{ "%.3f"|format(stats.avg_duration) }}s</td>
                        <td>{{ "%.1f"|format(stats.success_rate * 100) }}%</td>
                    </tr>
                    {% endfor %}
                </table>
            </div>
        </body>
        </html>
        ''')
        
        # Format time window text
        if time_window:
            hours = time_window / 3600
            if hours >= 24:
                days = hours / 24
                time_window_text = f"{days:.1f} days"
            else:
                time_window_text = f"{hours:.1f} hours"
        else:
            time_window_text = "All available data"
            
        # Render template
        report_html = report_template.render(
            timestamp=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            time_window_text=time_window_text,
            metrics=metrics,
            plot_files=plot_files,
            hourly_trends=metrics.get('hourly_trends', {})
        )
        
        # Write report file
        with open(output_file, 'w') as f:
            f.write(report_html)
            
        return output_file
        
    def visualize_query_audit_metrics(self, time_window=None, output_file=None, show_plot=True):
        """
        Visualize audit metrics related to queries.
        
        Args:
            time_window (int, optional): Time window in seconds
            output_file (str, optional): Output file path
            show_plot (bool): Whether to display the plot
            
        Returns:
            object: The generated visualization
        """
        # Check if create_query_audit_timeline is available (imported from audit_visualization)
        if 'create_query_audit_timeline' not in globals():
            logging.warning("Audit visualization not available")
            return None
            
        return create_query_audit_timeline(
            time_window=time_window,
            output_file=output_file,
            show_plot=show_plot
        )
        
    def generate_interactive_audit_trends(self, output_file=None):
        """
        Generate interactive audit trend visualization.
        
        Args:
            output_file (str, optional): Output file path
            
        Returns:
            str: Path to the generated visualization
        """
        # Import locally to avoid circular imports
        try:
            from ipfs_datasets_py.audit.audit_visualization import create_interactive_audit_trends
            return create_interactive_audit_trends(output_file=output_file)
        except ImportError:
            logging.warning("Interactive audit trend visualization not available")
            return None


def create_integrated_monitoring_system(dashboard_dir=None):
    """
    Create an integrated monitoring system for RAG queries.
    
    Args:
        dashboard_dir (str, optional): Directory for dashboard files
        
    Returns:
        tuple: (audit_logger, audit_metrics, query_metrics, dashboard)
    """
    # Import audit components
    try:
        from ipfs_datasets_py.audit.audit_logger import AuditLogger
        from ipfs_datasets_py.audit.audit_visualization import AuditMetricsCollector
        audit_logger = AuditLogger()
        audit_metrics = AuditMetricsCollector()
    except ImportError:
        logging.warning("Audit components not available")
        audit_logger = None
        audit_metrics = None
        
    # Create query metrics and dashboard
    query_metrics = QueryMetricsCollector()
    dashboard = RAGQueryDashboard(
        metrics_collector=query_metrics,
        dashboard_dir=dashboard_dir,
        audit_logger=audit_logger
    )
    
    # Connect audit logger to metrics collector if available
    if audit_logger and audit_metrics:
        audit_logger.add_handler(audit_metrics.process_event)
        
    return audit_logger, audit_metrics, query_metrics, dashboard


class PerformanceMetricsVisualizer:
    """
    Specialized visualizer for query performance metrics analysis.
    
    This class focuses on visualizing the detailed performance metrics of RAG queries,
    including processing time breakdowns, component contributions to latency,
    throughput analysis, and resource utilization patterns.
    """
    
    def __init__(self, metrics_collector):
        """
        Initialize the performance metrics visualizer.
        
        Args:
            metrics_collector: QueryMetricsCollector instance with query metrics
        """
        self.metrics_collector = metrics_collector
        self.default_figsize = (10, 6)
        self.colors = {
            "text": "#333333",
            "background": "#f5f5f5",
            "grid": "#dddddd",
            "vector_search": "#1f77b4",
            "graph_traversal": "#ff7f0e",
            "post_processing": "#2ca02c",
            "error": "#d62728",
            "warning": "#ff9800",
            "success": "#4caf50",
            "total": "#9467bd"
        }
        # Set default theme based on matplotlib style
        self.theme = "light"
        
    def set_theme(self, theme="light"):
        """
        Set visualization theme (light or dark).
        
        Args:
            theme: Theme name ('light' or 'dark')
        """
        self.theme = theme
        if theme == "dark":
            self.colors = {
                "text": "#f5f5f5",
                "background": "#2d2d2d",
                "grid": "#3d3d3d",
                "vector_search": "#7eb3e6",
                "graph_traversal": "#ffb86c",
                "post_processing": "#6ece7a",
                "error": "#ff6b6b",
                "warning": "#ffb347",
                "success": "#88d498",
                "total": "#bd93f9" 
            }
        else:
            self.colors = {
                "text": "#333333",
                "background": "#f5f5f5",
                "grid": "#dddddd",
                "vector_search": "#1f77b4",
                "graph_traversal": "#ff7f0e",
                "post_processing": "#2ca02c",
                "error": "#d62728",
                "warning": "#ff9800",
                "success": "#4caf50",
                "total": "#9467bd"
            }
    
    def visualize_processing_time_breakdown(self, 
                                          time_window=None, 
                                          figsize=None,
                                          output_file=None,
                                          show_plot=True,
                                          interactive=False):
        """
        Visualize the breakdown of processing time across query phases.
        
        Args:
            time_window: Optional time window in seconds to include
            figsize: Figure size (width, height) in inches
            output_file: Path to save the visualization
            show_plot: Whether to display the plot
            interactive: Whether to create an interactive plot
            
        Returns:
            Figure object or None if visualization libraries not available
        """
        if not VISUALIZATION_LIBS_AVAILABLE:
            logging.warning("Visualization libraries not available")
            return None
            
        if interactive and not INTERACTIVE_VISUALIZATION_AVAILABLE:
            logging.warning("Interactive visualization libraries not available")
            interactive = False
            
        # Get metrics from the collector
        metrics = self.metrics_collector.query_metrics
        if not metrics:
            logging.warning("No query metrics available")
            return None
            
        # Filter by time window if specified
        if time_window:
            current_time = time.time()
            cutoff_time = current_time - time_window
            filtered_metrics = {
                qid: m for qid, m in metrics.items() 
                if m.get("start_time", 0) >= cutoff_time
            }
        else:
            filtered_metrics = metrics
            
        if not filtered_metrics:
            logging.warning("No query metrics in the specified time window")
            return None
        
        # Extract phase durations
        phase_durations = {
            "vector_search": [],
            "graph_traversal": [],
            "post_processing": [],
            "other": [],
            "total": []
        }
        
        for qid, m in filtered_metrics.items():
            # Get all phases
            phases = m.get("phases", {})
            
            # Track total and get individual phases
            total = 0
            
            # Handle known phases
            for phase in ["vector_search", "graph_traversal", "post_processing"]:
                duration = phases.get(phase, 0)
                phase_durations[phase].append(duration)
                total += duration
                
            # Calculate other time (total - known phases)
            query_duration = m.get("duration", 0)
            other_time = max(0, query_duration - total)
            phase_durations["other"].append(other_time)
            
            # Record total duration
            phase_durations["total"].append(query_duration)
        
        if interactive:
            # Create interactive visualization with plotly
            fig = make_subplots(
                rows=2, cols=2,
                subplot_titles=[
                    "Average Phase Duration", 
                    "Phase Duration Distribution",
                    "Percentage Breakdown", 
                    "Duration Timeline"
                ],
                specs=[
                    [{"type": "bar"}, {"type": "box"}],
                    [{"type": "pie"}, {"type": "scatter"}]
                ]
            )
            
            # Calculate average durations
            avg_durations = {
                phase: np.mean(durations) if durations else 0 
                for phase, durations in phase_durations.items()
                if phase != "total"  # Exclude total from bar chart
            }
            
            # Bar chart of average durations
            phases = list(avg_durations.keys())
            durations = list(avg_durations.values())
            
            fig.add_trace(
                go.Bar(
                    x=phases,
                    y=durations,
                    marker_color=[
                        self.colors.get(phase, self.colors["vector_search"]) 
                        for phase in phases
                    ],
                    name="Average Duration"
                ),
                row=1, col=1
            )
            
            # Box plot of duration distributions
            for phase, values in phase_durations.items():
                if phase != "total" and values:  # Skip total and empty phases
                    fig.add_trace(
                        go.Box(
                            y=values,
                            name=phase,
                            marker_color=self.colors.get(phase, self.colors["vector_search"])
                        ),
                        row=1, col=2
                    )
            
            # Pie chart of percentage breakdown
            total_avg = sum(avg_durations.values())
            if total_avg > 0:
                labels = phases
                values = [d / total_avg * 100 for d in durations]
                
                fig.add_trace(
                    go.Pie(
                        labels=labels,
                        values=values,
                        marker=dict(
                            colors=[
                                self.colors.get(phase, self.colors["vector_search"]) 
                                for phase in phases
                            ]
                        ),
                        textinfo="label+percent",
                        hoverinfo="label+percent",
                        hole=0.3
                    ),
                    row=2, col=1
                )
            
            # Time series plot of durations
            timestamps = [m.get("start_time", 0) for m in filtered_metrics.values()]
            timestamps = [datetime.datetime.fromtimestamp(ts) for ts in timestamps]
            
            for phase in ["vector_search", "graph_traversal", "post_processing", "other"]:
                if phase_durations[phase]:
                    fig.add_trace(
                        go.Scatter(
                            x=timestamps,
                            y=phase_durations[phase],
                            mode="lines+markers",
                            name=phase,
                            line=dict(
                                color=self.colors.get(phase, self.colors["vector_search"]),
                                width=2
                            ),
                            marker=dict(
                                size=6
                            )
                        ),
                        row=2, col=2
                    )
            
            # Update layout
            fig.update_layout(
                title="Query Processing Time Breakdown",
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
            
            # Update axes
            fig.update_xaxes(
                showgrid=True,
                gridwidth=1,
                gridcolor=self.colors["grid"],
                linecolor=self.colors["text"]
            )
            
            fig.update_yaxes(
                title_text="Duration (seconds)",
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
            figsize = figsize or self.default_figsize
            fig = plt.figure(figsize=(figsize[0] * 2, figsize[1] * 2))
            
            # Set style
            plt.style.use('seaborn-v0_8-darkgrid' if self.theme == 'dark' else 'seaborn-v0_8-whitegrid')
            
            # Create grid of subplots
            gs = plt.GridSpec(2, 2, figure=fig)
            ax1 = fig.add_subplot(gs[0, 0])  # Average durations
            ax2 = fig.add_subplot(gs[0, 1])  # Distribution
            ax3 = fig.add_subplot(gs[1, 0])  # Percentage breakdown
            ax4 = fig.add_subplot(gs[1, 1])  # Timeline
            
            # Calculate average durations
            avg_durations = {
                phase: np.mean(durations) if durations else 0 
                for phase, durations in phase_durations.items()
                if phase != "total"  # Exclude total from bar chart
            }
            
            # Bar chart of average durations
            phases = list(avg_durations.keys())
            durations = list(avg_durations.values())
            
            bars = ax1.bar(
                phases, 
                durations,
                color=[self.colors.get(phase, self.colors["vector_search"]) for phase in phases]
            )
            
            ax1.set_title("Average Phase Duration")
            ax1.set_ylabel("Duration (seconds)")
            ax1.set_xlabel("Query Phase")
            
            # Box plot of duration distributions
            box_data = [phase_durations[phase] for phase in phases if phase_durations[phase]]
            box_labels = [phase for phase in phases if phase_durations[phase]]
            
            ax2.boxplot(
                box_data,
                labels=box_labels,
                patch_artist=True,
                boxprops=dict(facecolor=self.colors["background"]),
                medianprops=dict(color=self.colors["text"])
            )
            
            ax2.set_title("Phase Duration Distribution")
            ax2.set_ylabel("Duration (seconds)")
            ax2.set_xlabel("Query Phase")
            
            # Pie chart of percentage breakdown
            total_avg = sum(avg_durations.values())
            if total_avg > 0:
                phase_percentages = [d / total_avg * 100 for d in durations]
                
                ax3.pie(
                    phase_percentages,
                    labels=phases,
                    autopct='%1.1f%%',
                    colors=[self.colors.get(phase, self.colors["vector_search"]) for phase in phases],
                    startangle=90
                )
                
                ax3.set_title("Percentage Breakdown")
                
            else:
                ax3.text(0.5, 0.5, "No duration data available", 
                     horizontalalignment='center', 
                     verticalalignment='center',
                     transform=ax3.transAxes,
                     fontsize=12, color=self.colors["text"])
            
            # Time series plot of durations
            timestamps = [m.get("start_time", 0) for m in filtered_metrics.values()]
            datetimes = [datetime.datetime.fromtimestamp(ts) for ts in timestamps]
            
            for phase in ["vector_search", "graph_traversal", "post_processing", "other"]:
                if phase_durations[phase]:
                    ax4.plot(
                        datetimes,
                        phase_durations[phase],
                        'o-',
                        label=phase,
                        color=self.colors.get(phase, self.colors["vector_search"])
                    )
            
            ax4.set_title("Duration Timeline")
            ax4.set_ylabel("Duration (seconds)")
            ax4.set_xlabel("Query Time")
            ax4.legend()
            
            # Format datetime x-axis
            ax4.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
            plt.setp(ax4.xaxis.get_majorticklabels(), rotation=45)
            
            # Add overall title
            fig.suptitle("Query Processing Time Breakdown", fontsize=16)
            
            # Adjust layout
            plt.tight_layout()
            plt.subplots_adjust(top=0.9)
            
            # Save if output file specified
            if output_file:
                plt.savefig(output_file, dpi=300, bbox_inches='tight')
            
            # Show plot if requested
            if show_plot:
                plt.show()
            else:
                plt.close(fig)
                
            return fig
    
    def visualize_latency_distribution(self,
                                     time_window=None,
                                     figsize=None,
                                     output_file=None,
                                     show_plot=True,
                                     interactive=False):
        """
        Visualize the distribution of query latency.
        
        Args:
            time_window: Optional time window in seconds to include
            figsize: Figure size (width, height) in inches
            output_file: Path to save the visualization
            show_plot: Whether to display the plot
            interactive: Whether to create an interactive plot
            
        Returns:
            Figure object or None if visualization libraries not available
        """
        if not VISUALIZATION_LIBS_AVAILABLE:
            logging.warning("Visualization libraries not available")
            return None
            
        if interactive and not INTERACTIVE_VISUALIZATION_AVAILABLE:
            logging.warning("Interactive visualization libraries not available")
            interactive = False
            
        # Get metrics from the collector
        metrics = self.metrics_collector.query_metrics
        if not metrics:
            logging.warning("No query metrics available")
            return None
            
        # Filter by time window if specified
        if time_window:
            current_time = time.time()
            cutoff_time = current_time - time_window
            filtered_metrics = {
                qid: m for qid, m in metrics.items() 
                if m.get("start_time", 0) >= cutoff_time
            }
        else:
            filtered_metrics = metrics
            
        if not filtered_metrics:
            logging.warning("No query metrics in the specified time window")
            return None
        
        # Extract query durations and timestamps
        durations = []
        timestamps = []
        
        for qid, m in filtered_metrics.items():
            if "duration" in m:
                durations.append(m["duration"])
                timestamps.append(m.get("start_time", 0))
        
        if not durations:
            logging.warning("No duration data available")
            return None
            
        # Sort data by timestamp
        sorted_data = sorted(zip(timestamps, durations), key=lambda x: x[0])
        timestamps = [x[0] for x in sorted_data]
        durations = [x[1] for x in sorted_data]
        
        # Convert timestamps to datetime
        datetimes = [datetime.datetime.fromtimestamp(ts) for ts in timestamps]
        
        if interactive:
            # Create interactive visualization with plotly
            fig = make_subplots(
                rows=2, cols=2,
                subplot_titles=[
                    "Latency Distribution", 
                    "Latency Histogram",
                    "Latency Over Time", 
                    "Statistics"
                ],
                specs=[
                    [{"type": "violin"}, {"type": "histogram"}],
                    [{"type": "scatter"}, {"type": "domain"}]
                ]
            )
            
            # Violin plot of latency distribution
            fig.add_trace(
                go.Violin(
                    y=durations,
                    box_visible=True,
                    line_color=self.colors["vector_search"],
                    fillcolor=self.colors["vector_search"],
                    opacity=0.6,
                    name="Latency Distribution"
                ),
                row=1, col=1
            )
            
            # Histogram of latencies
            fig.add_trace(
                go.Histogram(
                    x=durations,
                    marker_color=self.colors["vector_search"],
                    opacity=0.7,
                    name="Latency Histogram"
                ),
                row=1, col=2
            )
            
            # Time series plot of latencies
            fig.add_trace(
                go.Scatter(
                    x=datetimes,
                    y=durations,
                    mode="lines+markers",
                    line=dict(
                        color=self.colors["vector_search"],
                        width=2
                    ),
                    marker=dict(
                        size=6
                    ),
                    name="Latency Over Time"
                ),
                row=2, col=1
            )
            
            # Calculate statistics
            mean_latency = np.mean(durations)
            median_latency = np.median(durations)
            p95_latency = np.percentile(durations, 95)
            p99_latency = np.percentile(durations, 99)
            min_latency = min(durations)
            max_latency = max(durations)
            
            # Create statistics table
            stats_table = go.Table(
                header=dict(
                    values=["Metric", "Value (seconds)"],
                    fill_color=self.colors["background"],
                    align='left',
                    font=dict(color=self.colors["text"], size=12)
                ),
                cells=dict(
                    values=[
                        ["Mean", "Median", "95th Percentile", "99th Percentile", "Min", "Max"],
                        [
                            f"{mean_latency:.3f}", 
                            f"{median_latency:.3f}", 
                            f"{p95_latency:.3f}", 
                            f"{p99_latency:.3f}",
                            f"{min_latency:.3f}",
                            f"{max_latency:.3f}"
                        ]
                    ],
                    fill_color=self.colors["background"],
                    align='left',
                    font=dict(color=self.colors["text"], size=12)
                )
            )
            
            fig.add_trace(stats_table, row=2, col=2)
            
            # Update layout
            fig.update_layout(
                title="Query Latency Analysis",
                height=800,
                width=1200,
                showlegend=False,
                paper_bgcolor=self.colors["background"],
                plot_bgcolor=self.colors["background"],
                font=dict(
                    family="Arial, sans-serif",
                    size=12,
                    color=self.colors["text"]
                )
            )
            
            # Update axes
            fig.update_xaxes(
                showgrid=True,
                gridwidth=1,
                gridcolor=self.colors["grid"],
                linecolor=self.colors["text"]
            )
            
            fig.update_yaxes(
                title_text="Duration (seconds)",
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
            figsize = figsize or self.default_figsize
            fig = plt.figure(figsize=(figsize[0] * 2, figsize[1] * 2))
            
            # Set style
            plt.style.use('seaborn-v0_8-darkgrid' if self.theme == 'dark' else 'seaborn-v0_8-whitegrid')
            
            # Create grid of subplots
            gs = plt.GridSpec(2, 2, figure=fig)
            ax1 = fig.add_subplot(gs[0, 0])  # Distribution plot
            ax2 = fig.add_subplot(gs[0, 1])  # Histogram
            ax3 = fig.add_subplot(gs[1, 0])  # Time series
            ax4 = fig.add_subplot(gs[1, 1])  # Statistics
            
            # Distribution plot (violin plot or box plot)
            if len(durations) >= 10:  # Only use violin plot with enough data
                sns.violinplot(y=durations, ax=ax1, color=self.colors["vector_search"])
            else:
                sns.boxplot(y=durations, ax=ax1, color=self.colors["vector_search"])
                
            ax1.set_title("Latency Distribution")
            ax1.set_ylabel("Duration (seconds)")
            
            # Histogram
            sns.histplot(durations, ax=ax2, color=self.colors["vector_search"], kde=True)
            ax2.set_title("Latency Histogram")
            ax2.set_xlabel("Duration (seconds)")
            ax2.set_ylabel("Count")
            
            # Time series plot
            ax3.plot(datetimes, durations, 'o-', color=self.colors["vector_search"])
            ax3.set_title("Latency Over Time")
            ax3.set_ylabel("Duration (seconds)")
            ax3.set_xlabel("Query Time")
            
            # Format datetime x-axis
            ax3.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
            plt.setp(ax3.xaxis.get_majorticklabels(), rotation=45)
            
            # Calculate statistics
            mean_latency = np.mean(durations)
            median_latency = np.median(durations)
            p95_latency = np.percentile(durations, 95)
            p99_latency = np.percentile(durations, 99)
            min_latency = min(durations)
            max_latency = max(durations)
            
            # Statistics table
            ax4.axis('off')
            ax4.set_title("Statistics")
            
            table_data = [
                ["Mean", f"{mean_latency:.3f} s"],
                ["Median", f"{median_latency:.3f} s"],
                ["95th Percentile", f"{p95_latency:.3f} s"],
                ["99th Percentile", f"{p99_latency:.3f} s"],
                ["Min", f"{min_latency:.3f} s"],
                ["Max", f"{max_latency:.3f} s"]
            ]
            
            table = ax4.table(
                cellText=table_data,
                colLabels=["Metric", "Value"],
                loc='center',
                cellLoc='left'
            )
            
            table.auto_set_font_size(False)
            table.set_fontsize(10)
            table.scale(1.2, 1.5)
            
            # Add overall title
            fig.suptitle("Query Latency Analysis", fontsize=16)
            
            # Adjust layout
            plt.tight_layout()
            plt.subplots_adjust(top=0.9)
            
            # Save if output file specified
            if output_file:
                plt.savefig(output_file, dpi=300, bbox_inches='tight')
            
            # Show plot if requested
            if show_plot:
                plt.show()
            else:
                plt.close(fig)
                
            return fig
    
    def _extract_summary_metrics(self, time_window=None):
        """Extract summary metrics from query collector for dashboard display."""
        metrics = self.metrics_collector.query_metrics
        
        # Filter by time window if specified
        if time_window:
            current_time = time.time()
            cutoff_time = current_time - time_window
            filtered_metrics = {
                qid: m for qid, m in metrics.items() 
                if m.get("start_time", 0) >= cutoff_time
            }
        else:
            filtered_metrics = metrics
            
        # Default values
        summary = {
            "total_queries": 0,
            "avg_duration": "N/A",
            "success_rate": "N/A",
            "peak_throughput": "N/A",
            "p95_latency": None,
            "error_rate": None
        }
        
        if not filtered_metrics:
            return summary
            
        # Calculate basic metrics
        summary["total_queries"] = len(filtered_metrics)
        
        # Calculate success and error rates
        completed = sum(1 for m in filtered_metrics.values() if m.get("status") == "completed")
        errors = sum(1 for m in filtered_metrics.values() if m.get("status") == "error")
        
        if summary["total_queries"] > 0:
            summary["success_rate"] = f"{completed / summary['total_queries'] * 100:.1f}"
            summary["error_rate"] = f"{errors / summary['total_queries'] * 100:.1f}"
        
        # Calculate duration statistics
        durations = [m.get("duration", 0) for m in filtered_metrics.values() if "duration" in m]
        if durations:
            summary["avg_duration"] = f"{sum(durations) / len(durations):.3f}"
            
            # Calculate 95th percentile if we have enough data
            if len(durations) >= 20:
                summary["p95_latency"] = f"{np.percentile(durations, 95):.3f}"
        
        # Estimate peak throughput from timestamps
        if len(filtered_metrics) >= 2:
            timestamps = [m.get("start_time", 0) for m in filtered_metrics.values()]
            timestamps.sort()
            
            # Use rolling window to find max queries per second
            window_size = 60  # 1 minute window
            max_qps = 0
            
            for i in range(len(timestamps)):
                window_end = timestamps[i]
                window_start = window_end - window_size
                
                # Count queries in this window
                queries_in_window = sum(1 for ts in timestamps if window_start <= ts <= window_end)
                
                # Calculate queries per second
                qps = queries_in_window / window_size
                max_qps = max(max_qps, qps)
            
            summary["peak_throughput"] = f"{max_qps:.2f}"
        
        return summary


class QueryMetricsCollector:
    """
    Collects and aggregates metrics from RAG query executions.
    
    This class tracks query performance, results, and patterns to identify trends,
    anomalies, and optimization opportunities in RAG system usage.
    """
    
    def __init__(self, window_size: int = 86400):  # 24 hour default window
        """
        Initialize the query metrics collector.
        
        Args:
            window_size: Time window in seconds for metrics retention
        """
        self.window_size = window_size
        self.query_metrics = {}  # Dict of query_id -> metrics
        self.performance_trends = {}
        self.optimization_stats = {}
        self.query_patterns = {}
        self.alert_handlers = []
        self.last_cleanup_time = time.time()
    
    def record_query_start(self, query_id: str, query_params: Dict[str, Any]) -> None:
        """
        Record the start of a query execution.
        
        Args:
            query_id: Unique identifier for the query
            query_params: Parameters of the query including query text, filters, etc.
        """
        self.query_metrics[query_id] = {
            'start_time': time.time(),
            'query_params': query_params,
            'status': 'running'
        }
    
    def record_query_end(self, query_id: str, results: Optional[List[Dict[str, Any]]] = None, 
                        error: Optional[str] = None, metrics: Optional[Dict[str, Any]] = None) -> None:
        """
        Record the completion of a query execution.
        
        Args:
            query_id: Unique identifier for the query
            results: Optional query results
            error: Optional error message if query failed
            metrics: Optional additional metrics about the query execution
        """
        if query_id not in self.query_metrics:
            # Create entry if it doesn't exist (e.g., if start wasn't recorded)
            self.query_metrics[query_id] = {
                'start_time': time.time(),
                'status': 'unknown'
            }
        
        # Record end time and duration
        end_time = time.time()
        self.query_metrics[query_id]['end_time'] = end_time
        
        # Calculate duration if we have start time
        if 'start_time' in self.query_metrics[query_id]:
            start_time = self.query_metrics[query_id]['start_time']
            duration = end_time - start_time
            self.query_metrics[query_id]['duration'] = duration
        
        # Update status
        if error:
            self.query_metrics[query_id]['status'] = 'error'
            self.query_metrics[query_id]['error'] = error
        else:
            self.query_metrics[query_id]['status'] = 'completed'
        
        # Add results information
        if results:
            self.query_metrics[query_id]['results_count'] = len(results)
            if len(results) > 0 and 'score' in results[0]:
                # Record top result score
                self.query_metrics[query_id]['top_score'] = results[0]['score']
                # Record average score
                avg_score = sum(r.get('score', 0) for r in results) / len(results)
                self.query_metrics[query_id]['avg_score'] = avg_score
        
        # Add any additional metrics
        if metrics:
            for key, value in metrics.items():
                self.query_metrics[query_id][key] = value
        
        # Clean up old queries periodically
        current_time = time.time()
        if current_time - self.last_cleanup_time > 3600:  # Clean up once per hour
            self._cleanup_old_queries()
            self.last_cleanup_time = current_time
        
        # Analyze patterns and check for anomalies
        self._analyze_query_patterns()
        self._check_for_anomalies(query_id)
    
    def _cleanup_old_queries(self) -> None:
        """Remove queries older than the specified window size."""
        current_time = time.time()
        cutoff_time = current_time - self.window_size
        
        # Create a list of query IDs to remove
        to_remove = []
        for query_id, metrics in self.query_metrics.items():
            if metrics.get('start_time', current_time) < cutoff_time:
                to_remove.append(query_id)
        
        # Remove old queries
        for query_id in to_remove:
            del self.query_metrics[query_id]
    
    def _analyze_query_patterns(self) -> None:
        """Analyze query patterns to identify trends and optimization opportunities."""
        # Skip if we don't have enough queries
        if len(self.query_metrics) < 10:
            return
        
        # Group queries by type/category/pattern
        query_types = {}
        for query_id, metrics in self.query_metrics.items():
            if 'query_params' in metrics and 'query_type' in metrics['query_params']:
                query_type = metrics['query_params']['query_type']
                if query_type not in query_types:
                    query_types[query_type] = []
                query_types[query_type].append(metrics)
        
        # Calculate performance metrics by query type
        performance_by_type = {}
        for query_type, queries in query_types.items():
            if not queries:
                continue
                
            durations = [q.get('duration', 0) for q in queries if 'duration' in q]
            if durations:
                performance_by_type[query_type] = {
                    'count': len(queries),
                    'avg_duration': sum(durations) / len(durations),
                    'max_duration': max(durations),
                    'min_duration': min(durations),
                    'success_rate': sum(1 for q in queries if q.get('status') == 'completed') / len(queries)
                }
        
        self.performance_trends = performance_by_type
        
        # Identify frequently occurring query patterns
        query_texts = [m.get('query_params', {}).get('query_text', '') 
                     for m in self.query_metrics.values() 
                     if 'query_params' in m and 'query_text' in m['query_params']]
        
        # Count frequency of query terms (basic implementation)
        term_counts = {}
        for text in query_texts:
            if not text:
                continue
                
            # Simple tokenization by whitespace
            terms = text.lower().split()
            for term in terms:
                if term not in term_counts:
                    term_counts[term] = 0
                term_counts[term] += 1
        
        # Sort by frequency
        sorted_terms = sorted(term_counts.items(), key=lambda x: x[1], reverse=True)
        self.query_patterns['common_terms'] = dict(sorted_terms[:20])  # Top 20 terms
    
    def _check_for_anomalies(self, query_id: str) -> None:
        """
        Check for anomalies in the query metrics.
        
        Args:
            query_id: The ID of the query to check
        """
        if query_id not in self.query_metrics:
            return
        
        metrics = self.query_metrics[query_id]
        anomalies = []
        
        # Check for unusually long execution time
        if 'duration' in metrics:
            # Calculate average duration of previous queries
            other_durations = [q.get('duration', 0) for qid, q in self.query_metrics.items() 
                              if qid != query_id and 'duration' in q]
            
            if other_durations and len(other_durations) >= 5:
                avg_duration = sum(other_durations) / len(other_durations)
                current_duration = metrics['duration']
                
                # If query took more than 3x the average time
                if current_duration > avg_duration * 3 and current_duration > 1.0:  # At least 1 second
                    anomalies.append({
                        'type': 'performance_anomaly',
                        'query_id': query_id,
                        'metric': 'duration',
                        'value': current_duration,
                        'average': avg_duration,
                        'ratio': current_duration / avg_duration,
                        'timestamp': datetime.datetime.now(UTC).isoformat() + 'Z',
                        'severity': 'medium' if current_duration > avg_duration * 5 else 'low'
                    })
        
        # Check for empty results anomaly
        if 'results_count' in metrics and metrics.get('status') == 'completed':
            if metrics['results_count'] == 0:
                # Get the query text if available
                query_text = metrics.get('query_params', {}).get('query_text', 'Unknown query')
                
                anomalies.append({
                    'type': 'empty_results_anomaly',
                    'query_id': query_id,
                    'query_text': query_text,
                    'timestamp': datetime.datetime.now(UTC).isoformat() + 'Z',
                    'severity': 'low'
                })
        
        # Check for low relevance scores
        if 'avg_score' in metrics and metrics.get('status') == 'completed':
            avg_score = metrics['avg_score']
            
            # If average score is below threshold
            if avg_score < 0.3:  # Threshold for concern
                anomalies.append({
                    'type': 'relevance_anomaly',
                    'query_id': query_id,
                    'metric': 'avg_score',
                    'value': avg_score,
                    'timestamp': datetime.datetime.now(UTC).isoformat() + 'Z',
                    'severity': 'low' if avg_score >= 0.2 else 'medium'
                })
        
        # Notify handlers of anomalies
        if anomalies and self.alert_handlers:
            for handler in self.alert_handlers:
                for anomaly in anomalies:
                    try:
                        handler(anomaly)
                    except Exception as e:
                        logging.error(f"Error in query anomaly handler: {str(e)}")
    
    def add_alert_handler(self, handler: Callable[[Dict[str, Any]], None]) -> None:
        """
        Add a handler for query anomaly alerts.
        
        Args:
            handler: Function that processes anomaly notifications
        """
        self.alert_handlers.append(handler)
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """
        Get performance metrics summary.
        
        Returns:
            Dict[str, Any]: Summary of query performance metrics
        """
        if not self.query_metrics:
            return {
                'total_queries': 0,
                'avg_duration': 0,
                'success_rate': 0,
                'error_rate': 0
            }
        
        # Calculate performance metrics
        total_queries = len(self.query_metrics)
        completed_queries = sum(1 for m in self.query_metrics.values() if m.get('status') == 'completed')
        error_queries = sum(1 for m in self.query_metrics.values() if m.get('status') == 'error')
        
        durations = [m.get('duration', 0) for m in self.query_metrics.values() if 'duration' in m]
        avg_duration = sum(durations) / len(durations) if durations else 0
        
        success_rate = completed_queries / total_queries if total_queries > 0 else 0
        error_rate = error_queries / total_queries if total_queries > 0 else 0
        
        # Get performance by hour (for trends)
        hourly_stats = {}
        current_time = time.time()
        for metrics in self.query_metrics.values():
            if 'start_time' in metrics and 'duration' in metrics:
                # Calculate hour bucket
                hour_start = int((metrics['start_time'] - current_time) / 3600) * 3600 + current_time
                hour_key = datetime.datetime.fromtimestamp(hour_start).strftime('%Y-%m-%d %H:00')
                
                if hour_key not in hourly_stats:
                    hourly_stats[hour_key] = {
                        'count': 0,
                        'total_duration': 0,
                        'errors': 0
                    }
                
                hourly_stats[hour_key]['count'] += 1
                hourly_stats[hour_key]['total_duration'] += metrics.get('duration', 0)
                
                if metrics.get('status') == 'error':
                    hourly_stats[hour_key]['errors'] += 1
        
        # Calculate hourly averages
        hourly_trends = {}
        for hour, stats in hourly_stats.items():
            hourly_trends[hour] = {
                'query_count': stats['count'],
                'avg_duration': stats['total_duration'] / stats['count'] if stats['count'] > 0 else 0,
                'error_rate': stats['errors'] / stats['count'] if stats['count'] > 0 else 0
            }
        
        return {
            'total_queries': total_queries,
            'completed_queries': completed_queries,
            'error_queries': error_queries,
            'avg_duration': avg_duration,
            'success_rate': success_rate,
            'error_rate': error_rate,
            'hourly_trends': hourly_trends,
            'performance_by_type': self.performance_trends
        }
    
    def get_query_patterns(self) -> Dict[str, Any]:
        """
        Get query pattern insights.
        
        Returns:
            Dict[str, Any]: Information about query patterns and trends
        """
        # Return existing patterns and add any additional analysis
        return {
            'common_terms': self.query_patterns.get('common_terms', {}),
            'term_correlations': self.query_patterns.get('term_correlations', {})
        }
    
    def get_optimization_opportunities(self) -> Dict[str, Any]:
        """
        Get recommended optimization opportunities based on query patterns.
        
        Returns:
            Dict[str, Any]: Optimization suggestions
        """
        opportunities = []
        
        # Check for slow queries
        slow_queries = []
        if self.query_metrics:
            # Calculate percentiles
            durations = [m.get('duration', 0) for m in self.query_metrics.values() if 'duration' in m]
            if durations and len(durations) >= 10:
                durations.sort()
                p95 = durations[int(0.95 * len(durations))]
                
                # Find queries above 95th percentile
                for query_id, metrics in self.query_metrics.items():
                    if 'duration' in metrics and metrics['duration'] > p95:
                        query_text = metrics.get('query_params', {}).get('query_text', 'Unknown query')
                        slow_queries.append({
                            'query_id': query_id,
                            'duration': metrics['duration'],
                            'query_text': query_text,
                            'timestamp': datetime.datetime.fromtimestamp(
                                metrics.get('start_time', time.time())
                            ).isoformat()
                        })
                
                if slow_queries:
                    opportunities.append({
                        'type': 'slow_queries',
                        'description': f'Identified {len(slow_queries)} queries above 95th percentile',
                        'queries': slow_queries[:5]  # Top 5 slowest
                    })
        
        # Check for common zero-result queries
        zero_result_queries = []
        for query_id, metrics in self.query_metrics.items():
            if metrics.get('results_count', -1) == 0 and metrics.get('status') == 'completed':
                query_text = metrics.get('query_params', {}).get('query_text', 'Unknown query')
                zero_result_queries.append({
                    'query_id': query_id,
                    'query_text': query_text,
                    'timestamp': datetime.datetime.fromtimestamp(
                        metrics.get('start_time', time.time())
                    ).isoformat()
                })
        
        if zero_result_queries:
            opportunities.append({
                'type': 'zero_result_queries',
                'description': f'Found {len(zero_result_queries)} queries with zero results',
                'queries': zero_result_queries[:5]  # Top 5 examples
            })
        
        return {
            'opportunities': opportunities
        }
    
    def to_json(self) -> Dict[str, Any]:
        """
        Convert metrics to JSON-serializable format.
        
        Returns:
            Dict[str, Any]: Complete metrics in JSON-serializable format
        """
        return {
            'performance': self.get_performance_metrics(),
            'patterns': self.get_query_patterns(),
            'optimization': self.get_optimization_opportunities(),
            'collected_at': datetime.datetime.now().isoformat()
        }


class RAGQueryVisualizer:
    """
    Visualization tools for RAG query metrics.
    
    This class provides methods for creating visualizations of query performance,
    patterns, and optimization opportunities to help understand and improve 
    RAG system behavior.
    """
    
    def __init__(self, metrics_collector: QueryMetricsCollector):
        """
        Initialize the visualizer with a metrics collector.
        
        Args:
            metrics_collector: QueryMetricsCollector instance with query metrics
        """
        self.metrics = metrics_collector
        self.visualization_available = VISUALIZATION_LIBS_AVAILABLE
    
    def plot_query_performance(self, 
                             period: str = 'hourly',
                             days: int = 1,
                             figsize: Tuple[int, int] = (10, 6),
                             output_file: Optional[str] = None,
                             show_plot: bool = False) -> Optional[Any]:
        """
        Create a plot of query performance over time.
        
        Args:
            period: Aggregation period ('hourly', 'daily')
            days: Number of days to include
            figsize: Figure size (width, height) in inches
            output_file: Optional path to save the plot
            show_plot: Whether to display the plot
            
        Returns:
            matplotlib.figure.Figure or None if visualization not available
        """
        if not self.visualization_available:
            logging.warning("Visualization libraries not available. Cannot create plot.")
            return None
        
        try:
            # Get performance metrics
            performance = self.metrics.get_performance_metrics()
            hourly_trends = performance.get('hourly_trends', {})
            
            if not hourly_trends:
                logging.warning("No performance data available for plotting.")
                return None
            
            # Convert hourly data to series
            sorted_hours = sorted(hourly_trends.keys())
            timestamps = [datetime.datetime.strptime(h, '%Y-%m-%d %H:00') for h in sorted_hours]
            query_counts = [hourly_trends[h]['query_count'] for h in sorted_hours]
            durations = [hourly_trends[h]['avg_duration'] for h in sorted_hours]
            error_rates = [hourly_trends[h]['error_rate'] for h in sorted_hours]
            
            # Create figure with two subplots (counts and durations)
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=figsize, sharex=True)
            
            # Plot query counts
            ax1.plot(timestamps, query_counts, marker='o', linewidth=2, 
                    color='#5E81AC', markersize=6, label='Query Count')
            ax1.set_ylabel('Query Count', fontsize=12)
            ax1.set_title('RAG Query Volume Over Time', fontsize=14)
            ax1.grid(True, linestyle='--', alpha=0.7)
            
            # Plot error rate on secondary axis
            ax1_twin = ax1.twinx()
            ax1_twin.plot(timestamps, [r * 100 for r in error_rates], marker='s', 
                        linewidth=2, color='#BF616A', markersize=6, 
                        linestyle='--', label='Error Rate')
            ax1_twin.set_ylabel('Error Rate (%)', color='#BF616A', fontsize=12)
            ax1_twin.tick_params(axis='y', colors='#BF616A')
            
            # Add combined legend
            lines1, labels1 = ax1.get_legend_handles_labels()
            lines2, labels2 = ax1_twin.get_legend_handles_labels()
            ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')
            
            # Plot durations
            ax2.plot(timestamps, durations, marker='o', linewidth=2, 
                    color='#A3BE8C', markersize=6)
            ax2.set_xlabel('Time', fontsize=12)
            ax2.set_ylabel('Avg. Duration (s)', fontsize=12)
            ax2.set_title('RAG Query Average Duration', fontsize=14)
            ax2.grid(True, linestyle='--', alpha=0.7)
            
            # Format time axis
            ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
            fig.autofmt_xdate()
            
            # Adjust layout
            plt.tight_layout()
            
            # Save to file if output_file is specified
            if output_file:
                plt.savefig(output_file, dpi=100, bbox_inches='tight')
            
            # Show plot if requested
            if show_plot:
                plt.show()
            else:
                plt.close()
            
            return fig
        
        except Exception as e:
            logging.error(f"Error creating query performance plot: {str(e)}")
            import traceback
            logging.error(traceback.format_exc())
            return None
    
    def plot_query_term_frequency(self,
                                top_n: int = 15,
                                figsize: Tuple[int, int] = (10, 8),
                                output_file: Optional[str] = None,
                                show_plot: bool = False) -> Optional[Any]:
        """
        Create a bar chart of most frequent query terms.
        
        Args:
            top_n: Number of top terms to include
            figsize: Figure size (width, height) in inches
            output_file: Optional path to save the plot
            show_plot: Whether to display the plot
            
        Returns:
            matplotlib.figure.Figure or None if visualization not available
        """
        if not self.visualization_available:
            logging.warning("Visualization libraries not available. Cannot create plot.")
            return None
        
        try:
            # Get query patterns
            patterns = self.metrics.get_query_patterns()
            common_terms = patterns.get('common_terms', {})
            
            if not common_terms:
                logging.warning("No term frequency data available for plotting.")
                return None
            
            # Sort terms by frequency and get top N
            sorted_terms = sorted(common_terms.items(), key=lambda x: x[1], reverse=True)[:top_n]
            
            # Create figure
            fig, ax = plt.subplots(figsize=figsize)
            
            # Extract data for plotting
            terms = [term for term, _ in sorted_terms]
            counts = [count for _, count in sorted_terms]
            
            # Create horizontal bar chart
            bars = ax.barh(terms, counts, color='#5E81AC')
            
            # Add count labels
            for i, bar in enumerate(bars):
                width = bar.get_width()
                ax.text(width + 0.5, bar.get_y() + bar.get_height()/2,
                      str(int(width)), ha='left', va='center', fontsize=10)
            
            # Set labels and title
            ax.set_xlabel('Frequency', fontsize=12)
            ax.set_title('Most Common RAG Query Terms', fontsize=14)
            
            # Remove top and right spines
            ax.spines['right'].set_visible(False)
            ax.spines['top'].set_visible(False)
            
            # Add grid lines
            ax.grid(axis='x', linestyle='--', alpha=0.7)
            
            # Adjust layout
            plt.tight_layout()
            
            # Save to file if output_file is specified
            if output_file:
                plt.savefig(output_file, dpi=100, bbox_inches='tight')
            
            # Show plot if requested
            if show_plot:
                plt.show()
            else:
                plt.close()
            
            return fig
        
        except Exception as e:
            logging.error(f"Error creating query term frequency plot: {str(e)}")
            import traceback
            logging.error(traceback.format_exc())
            return None
    
    def plot_query_duration_distribution(self,
                                       figsize: Tuple[int, int] = (10, 6),
                                       output_file: Optional[str] = None,
                                       show_plot: bool = False) -> Optional[Any]:
        """
        Create a histogram of query durations.
        
        Args:
            figsize: Figure size (width, height) in inches
            output_file: Optional path to save the plot
            show_plot: Whether to display the plot
            
        Returns:
            matplotlib.figure.Figure or None if visualization not available
        """
        if not self.visualization_available:
            logging.warning("Visualization libraries not available. Cannot create plot.")
            return None
        
        try:
            # Extract query durations
            durations = [m.get('duration', 0) for m in self.metrics.query_metrics.values() 
                        if 'duration' in m]
            
            if not durations or len(durations) < 5:
                logging.warning("Not enough duration data available for plotting.")
                return None
            
            # Create figure
            fig, ax = plt.subplots(figsize=figsize)
            
            # Create histogram
            sns.histplot(durations, bins=20, kde=True, color='#5E81AC', ax=ax)
            
            # Add percentile lines
            durations.sort()
            p50 = durations[int(0.5 * len(durations))]
            p90 = durations[int(0.9 * len(durations))]
            p95 = durations[int(0.95 * len(durations))]
            
            ax.axvline(p50, color='green', linestyle='--', alpha=0.8, label=f'50th percentile ({p50:.2f}s)')
            ax.axvline(p90, color='orange', linestyle='--', alpha=0.8, label=f'90th percentile ({p90:.2f}s)')
            ax.axvline(p95, color='red', linestyle='--', alpha=0.8, label=f'95th percentile ({p95:.2f}s)')
            
            # Set labels and title
            ax.set_xlabel('Duration (seconds)', fontsize=12)
            ax.set_ylabel('Frequency', fontsize=12)
            ax.set_title('RAG Query Duration Distribution', fontsize=14)
            
            # Add legend
            ax.legend()
            
            # Adjust layout
            plt.tight_layout()
            
            # Save to file if output_file is specified
            if output_file:
                plt.savefig(output_file, dpi=100, bbox_inches='tight')
            
            # Show plot if requested
            if show_plot:
                plt.show()
            else:
                plt.close()
            
            return fig
        
        except Exception as e:
            logging.error(f"Error creating query duration distribution plot: {str(e)}")
            import traceback
            logging.error(traceback.format_exc())
            return None
    
    def generate_dashboard_html(self,
                              title: str = "RAG Query Performance Dashboard",
                              include_optimization: bool = True,
                              include_patterns: bool = True,
                              include_security_correlation: bool = True,
                              anomalies: List[Dict[str, Any]] = None,
                              audit_metrics = None) -> str:
        """
        Generate an HTML dashboard with query metrics and visualizations.
        
        Args:
            title: Dashboard title
            include_optimization: Whether to include optimization suggestions
            include_patterns: Whether to include query pattern analysis
            include_security_correlation: Whether to include security correlation visualization
            anomalies: Optional list of query anomalies to display
            audit_metrics: Optional AuditMetricsAggregator for integrated audit data
            
        Returns:
            str: HTML dashboard content
        """
        if not TEMPLATE_ENGINE_AVAILABLE:
            logging.warning("Template engine not available. Cannot generate HTML dashboard.")
            return "<html><body><h1>Template engine not available</h1></body></html>"
        
        # Get metrics data
        performance = self.metrics.get_performance_metrics()
        patterns = None
        optimization = None
        
        if include_patterns:
            patterns = self.metrics.get_query_patterns()
        
        if include_optimization:
            optimization = self.metrics.get_optimization_opportunities()
        
        # Generate chart images
        chart_paths = {}
        
        # Create temporary directory for charts
        import tempfile
        import shutil
        temp_dir = tempfile.mkdtemp()
        try:
            # Generate performance chart
            performance_chart = os.path.join(temp_dir, "performance.png")
            self.plot_query_performance(output_file=performance_chart)
            chart_paths['performance'] = performance_chart
            
            # Generate duration distribution chart
            duration_chart = os.path.join(temp_dir, "durations.png")
            self.plot_query_duration_distribution(output_file=duration_chart)
            chart_paths['durations'] = duration_chart
            
            # Generate audit visualization if requested and metrics are available
            if audit_metrics and hasattr(self, 'visualizer') and isinstance(self.visualizer, EnhancedQueryVisualizer):
                # Create security correlation chart
                security_chart = os.path.join(temp_dir, "security_correlation.png")
                try:
                    self.visualizer.visualize_query_performance_with_security_events(
                        audit_metrics_aggregator=audit_metrics,
                        output_file=security_chart,
                        hours_back=24,  # Last 24 hours
                        interval_minutes=15,  # 15-minute intervals
                        min_severity="WARNING",  # Only WARNING and above
                        interactive=False,
                        show_plot=False
                    )
                    if os.path.exists(security_chart) and os.path.getsize(security_chart) > 0:
                        chart_paths['security_correlation'] = security_chart
                except Exception as e:
                    logging.warning(f"Error generating security correlation visualization: {str(e)}")
            
            # Generate term frequency chart if patterns included
            if include_patterns:
                terms_chart = os.path.join(temp_dir, "terms.png")
                self.plot_query_term_frequency(output_file=terms_chart)
                chart_paths['terms'] = terms_chart
            
            # Generate query-audit timeline if audit metrics provided
            if audit_metrics:
                timeline_chart = os.path.join(temp_dir, "timeline.png")
                from ipfs_datasets_py.audit.audit_visualization import create_query_audit_timeline
                create_query_audit_timeline(
                    query_metrics_collector=self.metrics, 
                    audit_metrics=audit_metrics, 
                    output_file=timeline_chart
                )
                chart_paths['timeline'] = timeline_chart
            
            # Create HTML template
            dashboard_template = """
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>{{ title }}</title>
                <style>
                    body {
                        font-family: Arial, sans-serif;
                        margin: 0;
                        padding: 20px;
                        background-color: #f5f5f5;
                    }
                    .dashboard {
                        max-width: 1200px;
                        margin: 0 auto;
                        background-color: white;
                        padding: 20px;
                        border-radius: 5px;
                        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                    }
                    h1, h2, h3 {
                        color: #333;
                    }
                    .metric-card {
                        background-color: #f9f9f9;
                        border-radius: 5px;
                        padding: 15px;
                        margin-bottom: 15px;
                        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                    }
                    .metric-grid {
                        display: grid;
                        grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
                        gap: 15px;
                        margin-bottom: 20px;
                    }
                    .key-metric {
                        background-color: #e9f5ff;
                        padding: 10px;
                        border-radius: 5px;
                        text-align: center;
                    }
                    .key-metric h3 {
                        margin-top: 0;
                        font-size: 16px;
                    }
                    .key-metric p {
                        font-size: 24px;
                        font-weight: bold;
                        margin: 5px 0;
                    }
                    .chart-container {
                        margin-bottom: 20px;
                    }
                    .chart-container img {
                        max-width: 100%;
                        height: auto;
                        border: 1px solid #ddd;
                        border-radius: 5px;
                    }
                    .chart-description {
                        font-size: 0.9em;
                        color: #666;
                        margin-top: 5px;
                        font-style: italic;
                    }
                    table {
                        width: 100%;
                        border-collapse: collapse;
                        margin-bottom: 20px;
                    }
                    table th, table td {
                        padding: 8px;
                        text-align: left;
                        border-bottom: 1px solid #ddd;
                    }
                    table th {
                        background-color: #f2f2f2;
                    }
                    .footer {
                        text-align: center;
                        color: #777;
                        margin-top: 20px;
                        font-size: 12px;
                    }
                    .alert-section {
                        margin-top: 30px;
                        padding: 10px;
                        border-radius: 5px;
                    }
                    .alert-card {
                        border-left: 5px solid #ff9800;
                        padding: 10px;
                        margin-bottom: 10px;
                        background-color: #fff8e1;
                        border-radius: 3px;
                    }
                    .alert-card.critical {
                        border-left-color: #f44336;
                        background-color: #ffebee;
                    }
                    .alert-card.high {
                        border-left-color: #ff5722;
                        background-color: #fbe9e7;
                    }
                    .alert-card.medium {
                        border-left-color: #ff9800;
                        background-color: #fff8e1;
                    }
                    .alert-card.low {
                        border-left-color: #4caf50;
                        background-color: #e8f5e9;
                    }
                    .alert-header {
                        font-weight: bold;
                        margin-bottom: 5px;
                    }
                    .alert-body {
                        margin-bottom: 5px;
                    }
                    .alert-timestamp {
                        color: #777;
                        font-size: 12px;
                    }
                    .optimization-card {
                        border-left: 5px solid #2196f3;
                        padding: 10px;
                        margin-bottom: 10px;
                        background-color: #e3f2fd;
                        border-radius: 3px;
                    }
                    .optimization-header {
                        font-weight: bold;
                        margin-bottom: 5px;
                    }
                    .optimization-details {
                        font-size: 14px;
                        color: #555;
                        margin-bottom: 10px;
                    }
                    .optimization-examples {
                        font-family: monospace;
                        background-color: #f5f5f5;
                        padding: 8px;
                        border-radius: 3px;
                        margin-top: 5px;
                    }
                </style>
            </head>
            <body>
                <div class="dashboard">
                    <h1>{{ title }}</h1>
                    <p>Generated at {{ current_time }}</p>
                    
                    {% if anomalies %}
                    <div class="alert-section">
                        <h2>Query Anomalies</h2>
                        {% for anomaly in anomalies %}
                        <div class="alert-card {{ anomaly.severity }}">
                            <div class="alert-header">{{ anomaly.type }}</div>
                            <div class="alert-body">
                                {% if anomaly.type == 'performance_anomaly' %}
                                <p>Query took {{ anomaly.value|round(2) }}s, which is {{ anomaly.ratio|round(1) }}x the average time</p>
                                {% elif anomaly.type == 'empty_results_anomaly' %}
                                <p>Query returned zero results: "{{ anomaly.query_text }}"</p>
                                {% elif anomaly.type == 'relevance_anomaly' %}
                                <p>Average result score was {{ anomaly.value|round(2) }}, which is below threshold</p>
                                {% else %}
                                <p>{{ anomaly.type }}</p>
                                {% endif %}
                            </div>
                            <div class="alert-timestamp">{{ anomaly.timestamp }}</div>
                        </div>
                        {% endfor %}
                    </div>
                    {% endif %}
                    
                    <h2>Performance Summary</h2>
                    <div class="metric-grid">
                        <div class="key-metric">
                            <h3>Total Queries</h3>
                            <p>{{ performance.total_queries }}</p>
                        </div>
                        <div class="key-metric">
                            <h3>Avg. Duration</h3>
                            <p>{{ performance.avg_duration|round(2) }}s</p>
                        </div>
                        <div class="key-metric">
                            <h3>Success Rate</h3>
                            <p>{{ (performance.success_rate * 100)|round(1) }}%</p>
                        </div>
                        <div class="key-metric">
                            <h3>Error Rate</h3>
                            <p>{{ (performance.error_rate * 100)|round(1) }}%</p>
                        </div>
                    </div>
                    
                    <div class="chart-container">
                        <h3>Query Performance Over Time</h3>
                        {% if chart_data.performance %}
                        <img src="data:image/png;base64,{{ chart_data.performance }}" alt="Query Performance">
                        {% else %}
                        <p>No performance data available</p>
                        {% endif %}
                    </div>
                    
                    <div class="chart-container">
                        <h3>Query Duration Distribution</h3>
                        {% if chart_data.durations %}
                        <img src="data:image/png;base64,{{ chart_data.durations }}" alt="Query Durations">
                        {% else %}
                        <p>No duration data available</p>
                        {% endif %}
                    </div>
                    
                    {% if chart_data.timeline %}
                    <div class="chart-container">
                        <h3>Query and Audit Event Timeline</h3>
                        <img src="data:image/png;base64,{{ chart_data.timeline }}" alt="Query and Audit Timeline">
                    </div>
                    {% endif %}
                    
                    {% if chart_data.security_correlation %}
                    <div class="chart-container">
                        <h3>Query Performance & Security Event Correlation</h3>
                        <img src="data:image/png;base64,{{ chart_data.security_correlation }}" alt="Security Correlation">
                        <p class="chart-description">This visualization shows the correlation between query performance and security events, helping identify if security incidents impact query performance or if performance anomalies correlate with security events.</p>
                    </div>
                    {% endif %}
                    
                    {% if include_patterns and patterns %}
                    <h2>Query Patterns</h2>
                    
                    {% if chart_data.terms %}
                    <div class="chart-container">
                        <h3>Most Common Query Terms</h3>
                        <img src="data:image/png;base64,{{ chart_data.terms }}" alt="Term Frequency">
                    </div>
                    {% endif %}
                    
                    <div class="metric-card">
                        <h3>Top Query Terms</h3>
                        <table>
                            <thead>
                                <tr>
                                    <th>Term</th>
                                    <th>Frequency</th>
                                </tr>
                            </thead>
                            <tbody>
                                {% for term, count in patterns.common_terms.items() %}
                                <tr>
                                    <td>{{ term }}</td>
                                    <td>{{ count }}</td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                    {% endif %}
                    
                    {% if include_optimization and optimization and optimization.opportunities %}
                    <h2>Optimization Opportunities</h2>
                    
                    {% for opportunity in optimization.opportunities %}
                    <div class="optimization-card">
                        <div class="optimization-header">{{ opportunity.type }}</div>
                        <div class="optimization-details">{{ opportunity.description }}</div>
                        
                        {% if opportunity.queries %}
                        <h4>Example Queries:</h4>
                        {% for query in opportunity.queries %}
                        <div class="optimization-examples">
                            <div>{{ query.query_text }}</div>
                            <small>{{ query.timestamp }} - Duration: {{ query.duration|round(2) if query.duration else 'N/A' }}s</small>
                        </div>
                        {% endfor %}
                        {% endif %}
                    </div>
                    {% endfor %}
                    {% endif %}
                    
                    <div class="footer">
                        <p>Generated by RAGQueryVisualizer</p>
                    </div>
                </div>
            </body>
            </html>
            """
            
            # Convert chart images to base64 for embedding in HTML
            chart_data = {}
            for name, path in chart_paths.items():
                if os.path.exists(path):
                    with open(path, 'rb') as f:
                        import base64
                        chart_data[name] = base64.b64encode(f.read()).decode('utf-8')
            
            # Ensure anomalies is a list
            if anomalies is None:
                anomalies = []
            
            # Render template
            template = Template(dashboard_template)
            html = template.render(
                title=title,
                current_time=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                performance=performance,
                patterns=patterns,
                optimization=optimization,
                chart_data=chart_data,
                anomalies=anomalies,
                include_patterns=include_patterns,
                include_optimization=include_optimization
            )
            
            return html
            
        finally:
            # Clean up temporary directory
            shutil.rmtree(temp_dir)
    
    def export_metrics_report(self,
                            format: str = "html",
                            output_file: Optional[str] = None) -> Union[str, Dict[str, Any]]:
        """
        Export metrics report in the specified format.
        
        Args:
            format: Report format ("html" or "json")
            output_file: Optional path to save the report
            
        Returns:
            str or Dict: Report content
        """
        if format.lower() == "html":
            html = self.generate_dashboard_html()
            
            if output_file:
                with open(output_file, 'w') as f:
                    f.write(html)
            
            return html
            
        elif format.lower() == "json":
            # Get JSON representation of metrics
            json_data = self.metrics.to_json()
            
            if output_file:
                with open(output_file, 'w') as f:
                    json.dump(json_data, f, indent=2)
            
            return json_data
            
        else:
            raise ValueError(f"Unsupported format: {format}")


class OptimizerLearningMetricsCollector:
    """
    Collects and analyzes metrics from the RAG query optimizer's statistical learning process.
    
    This class provides visualization and analysis of the optimizer's learning performance,
    allowing monitoring of learning cycles, parameter adaptations, and optimization effectiveness.
    """
    
    def __init__(self, max_history_size=1000):
        """
        Initialize the learning metrics collector.
        
        Args:
            max_history_size (int): Maximum number of learning events to store
        """
        self.learning_events = []  # Learning events with timestamps
        self.learning_results = []  # Results from learning cycles
        self.parameter_adaptations = {}  # Track parameter changes over time
        self.optimization_strategies = {}  # Track strategy effectiveness
        self.circuit_breaker_events = []  # Circuit breaker activations/resets
        self.max_history_size = max_history_size
        self.audit_logger = None
        self._lock = threading.RLock()  # Thread safety
        
    def set_audit_logger(self, audit_logger):
        """
        Set the audit logger for recording learning events.
        
        Args:
            audit_logger: AuditLogger instance
        """
        self.audit_logger = audit_logger
        
    def record_learning_cycle(self, cycle_id, time_started, query_count, is_success=True, 
                             duration=None, results=None, error=None):
        """
        Record metrics from a learning cycle.
        
        Args:
            cycle_id: Unique identifier for the learning cycle
            time_started: When the cycle started (timestamp)
            query_count: Number of queries analyzed in this cycle
            is_success: Whether the cycle completed successfully
            duration: How long the cycle took (seconds)
            results: Dictionary of learning results
            error: Error message if the cycle failed
        """
        with self._lock:
            # Create learning event
            event = {
                'cycle_id': cycle_id,
                'timestamp': time_started,
                'datetime': datetime.datetime.fromtimestamp(time_started),
                'query_count': query_count,
                'is_success': is_success,
                'duration': duration,
                'error': error
            }
            
            # Add results if available
            if results and isinstance(results, dict):
                event.update({
                    'analyzed_queries': results.get('analyzed_queries', 0),
                    'rules_generated': results.get('rules_generated', 0),
                    'warning': results.get('error'),  # Non-critical error
                    'optimization_rules': results.get('optimization_rules', [])
                })
                
                # Track results separately for analysis
                self.learning_results.append({
                    'cycle_id': cycle_id,
                    'timestamp': time_started,
                    'results': results
                })
                
                # Record to audit log if configured
                if self.audit_logger:
                    try:
                        self.audit_logger.log(
                            "learning_cycle_completed",
                            f"Analyzed {results.get('analyzed_queries', 0)} queries, generated {results.get('rules_generated', 0)} rules",
                            severity="info" if is_success else "warning",
                            category="statistical_learning",
                            metadata={
                                'cycle_id': cycle_id,
                                'query_count': query_count,
                                'duration': duration,
                                'rules_generated': results.get('rules_generated', 0)
                            }
                        )
                    except Exception:
                        # Ignore errors in audit logging
                        pass
                
            # Add to learning events
            self.learning_events.append(event)
            
            # Limit history size
            if len(self.learning_events) > self.max_history_size:
                self.learning_events = self.learning_events[-self.max_history_size:]
                
    def record_parameter_adaptation(self, parameter_name, old_value, new_value, 
                                  confidence, cycle_id=None):
        """
        Record parameter adaptation from the learning process.
        
        Args:
            parameter_name: Name of the parameter that was adapted
            old_value: Previous parameter value
            new_value: New parameter value
            confidence: Confidence in this adaptation (0.0-1.0)
            cycle_id: Learning cycle that triggered this adaptation
        """
        with self._lock:
            # Create adaptation event
            now = time.time()
            adaptation = {
                'parameter': parameter_name,
                'old_value': old_value,
                'new_value': new_value,
                'change': self._calculate_change(old_value, new_value),
                'confidence': confidence,
                'timestamp': now,
                'datetime': datetime.datetime.fromtimestamp(now),
                'cycle_id': cycle_id
            }
            
            # Track in parameter history
            if parameter_name not in self.parameter_adaptations:
                self.parameter_adaptations[parameter_name] = []
                
            self.parameter_adaptations[parameter_name].append(adaptation)
            
            # Limit history size
            if len(self.parameter_adaptations[parameter_name]) > self.max_history_size:
                self.parameter_adaptations[parameter_name] = self.parameter_adaptations[parameter_name][-self.max_history_size:]
                
            # Record to audit log if configured
            if self.audit_logger:
                try:
                    self.audit_logger.log(
                        "parameter_adaptation",
                        f"Parameter '{parameter_name}' adapted from {old_value} to {new_value}",
                        severity="info",
                        category="statistical_learning",
                        metadata={
                            'parameter': parameter_name,
                            'old_value': str(old_value),
                            'new_value': str(new_value),
                            'confidence': confidence,
                            'cycle_id': cycle_id
                        }
                    )
                except Exception:
                    # Ignore errors in audit logging
                    pass
                    
    def record_circuit_breaker_event(self, event_type, reason, backoff_minutes=None):
        """
        Record circuit breaker activation or reset.
        
        Args:
            event_type: Type of event ('tripped' or 'reset')
            reason: Reason for the event
            backoff_minutes: Backoff period in minutes if tripped
        """
        with self._lock:
            # Create event
            now = time.time()
            event = {
                'event_type': event_type,
                'reason': reason,
                'timestamp': now,
                'datetime': datetime.datetime.fromtimestamp(now)
            }
            
            if event_type == 'tripped' and backoff_minutes is not None:
                retry_time = now + (backoff_minutes * 60)
                event['backoff_minutes'] = backoff_minutes
                event['retry_time'] = retry_time
                event['retry_datetime'] = datetime.datetime.fromtimestamp(retry_time)
                
            # Add to circuit breaker events
            self.circuit_breaker_events.append(event)
            
            # Limit history size
            if len(self.circuit_breaker_events) > self.max_history_size:
                self.circuit_breaker_events = self.circuit_breaker_events[-self.max_history_size:]
                
            # Record to audit log if configured
            if self.audit_logger:
                try:
                    severity = "warning" if event_type == "tripped" else "info"
                    message = f"Circuit breaker {event_type}: {reason}"
                    
                    metadata = {
                        'event_type': event_type,
                        'reason': reason
                    }
                    
                    if event_type == 'tripped' and backoff_minutes is not None:
                        metadata['backoff_minutes'] = backoff_minutes
                        metadata['retry_time'] = datetime.datetime.fromtimestamp(retry_time).isoformat()
                        
                    self.audit_logger.log(
                        f"circuit_breaker_{event_type}",
                        message,
                        severity=severity,
                        category="statistical_learning",
                        metadata=metadata
                    )
                except Exception:
                    # Ignore errors in audit logging
                    pass
                    
    def get_learning_performance_metrics(self, window_seconds=86400):
        """
        Get performance metrics for learning cycles within a time window.
        
        Args:
            window_seconds: Time window in seconds (default: 24 hours)
            
        Returns:
            dict: Learning performance metrics
        """
        with self._lock:
            now = time.time()
            window_start = now - window_seconds
            
            # Filter events in the time window
            recent_events = [event for event in self.learning_events 
                          if event['timestamp'] >= window_start]
                          
            # Calculate basic metrics
            total_cycles = len(recent_events)
            successful_cycles = sum(1 for event in recent_events if event.get('is_success', False))
            failed_cycles = total_cycles - successful_cycles
            success_rate = successful_cycles / max(1, total_cycles)
            
            # Calculate metrics from successful cycles
            analyzed_queries = sum(event.get('analyzed_queries', 0) for event in recent_events if event.get('is_success', False))
            rules_generated = sum(event.get('rules_generated', 0) for event in recent_events if event.get('is_success', False))
            
            # Calculate average durations
            durations = [event.get('duration', 0) for event in recent_events 
                      if event.get('duration') is not None]
            avg_duration = sum(durations) / max(1, len(durations)) if durations else 0
            
            # Calculate circuit breaker statistics
            recent_cb_events = [event for event in self.circuit_breaker_events 
                             if event['timestamp'] >= window_start]
            trips = sum(1 for event in recent_cb_events if event['event_type'] == 'tripped')
            resets = sum(1 for event in recent_cb_events if event['event_type'] == 'reset')
            
            # Parameter adaptation statistics
            param_adaptations = {}
            for param, adaptations in self.parameter_adaptations.items():
                recent_adaptations = [a for a in adaptations if a['timestamp'] >= window_start]
                if recent_adaptations:
                    param_adaptations[param] = len(recent_adaptations)
            
            # Create performance metrics
            return {
                'window_seconds': window_seconds,
                'total_cycles': total_cycles,
                'successful_cycles': successful_cycles,
                'failed_cycles': failed_cycles,
                'success_rate': success_rate,
                'analyzed_queries': analyzed_queries,
                'rules_generated': rules_generated,
                'avg_duration': avg_duration,
                'circuit_breaker_trips': trips,
                'circuit_breaker_resets': resets,
                'parameter_adaptations': param_adaptations,
                'is_active': self._check_if_active(recent_events)
            }
            
    def visualize_learning_performance(self, output_file=None, interactive=True):
        """
        Create visualization of learning performance metrics.
        
        Args:
            output_file: Optional file path to save the visualization
            interactive: Whether to create an interactive visualization
            
        Returns:
            matplotlib.Figure or plotly.Figure: The generated visualization
        """
        # Skip visualization if we don't have enough data
        if len(self.learning_events) < 2:
            if interactive and INTERACTIVE_VISUALIZATION_AVAILABLE:
                # Create empty plotly figure with message
                fig = go.Figure()
                fig.add_annotation(
                    text="Not enough learning cycles recorded yet",
                    xref="paper", yref="paper",
                    x=0.5, y=0.5,
                    showarrow=False,
                    font=dict(size=20)
                )
                
                if output_file:
                    fig.write_html(output_file)
                    
                return fig
            else:
                # Create empty matplotlib figure with message
                fig, ax = plt.subplots(figsize=(10, 6))
                ax.text(0.5, 0.5, "Not enough learning cycles recorded yet",
                       horizontalalignment='center',
                       verticalalignment='center',
                       transform=ax.transAxes,
                       fontsize=14)
                
                if output_file:
                    plt.savefig(output_file, dpi=100, bbox_inches='tight')
                    
                return fig
                
        # Create interactive visualization if requested and available
        if interactive and INTERACTIVE_VISUALIZATION_AVAILABLE:
            return self._create_interactive_learning_visualization(output_file)
        
        # Create static matplotlib visualization
        return self._create_static_learning_visualization(output_file)
    
    def _create_interactive_learning_visualization(self, output_file=None):
        """Create interactive Plotly visualization of learning metrics."""
        if not INTERACTIVE_VISUALIZATION_AVAILABLE:
            return None
            
        # Convert data for visualization
        cycle_times = []
        success_status = []
        analyzed_queries = []
        rules_generated = []
        durations = []
        
        for event in sorted(self.learning_events, key=lambda x: x['timestamp']):
            cycle_times.append(event['datetime'])
            success_status.append('Success' if event.get('is_success', False) else 'Failure')
            analyzed_queries.append(event.get('analyzed_queries', 0))
            rules_generated.append(event.get('rules_generated', 0))
            durations.append(event.get('duration', 0))
            
        # Create figure with subplots
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=(
                'Learning Cycle Status',
                'Queries Analyzed vs Rules Generated',
                'Cycle Duration',
                'Parameter Adaptations'
            ),
            specs=[
                [{"type": "scatter"}, {"type": "scatter"}],
                [{"type": "scatter"}, {"type": "bar"}]
            ]
        )
        
        # Add learning cycle status
        fig.add_trace(
            go.Scatter(
                x=cycle_times,
                y=[1 if status == 'Success' else 0 for status in success_status],
                mode='markers',
                name='Learning Cycles',
                marker=dict(
                    color=['green' if status == 'Success' else 'red' for status in success_status],
                    size=10
                ),
                hovertemplate='%{x}<br>Status: %{text}',
                text=success_status
            ),
            row=1, col=1
        )
        
        # Add queries analyzed vs rules generated
        fig.add_trace(
            go.Scatter(
                x=cycle_times,
                y=analyzed_queries,
                mode='lines+markers',
                name='Queries Analyzed',
                marker=dict(color='blue')
            ),
            row=1, col=2
        )
        
        fig.add_trace(
            go.Scatter(
                x=cycle_times,
                y=rules_generated,
                mode='lines+markers',
                name='Rules Generated',
                marker=dict(color='orange')
            ),
            row=1, col=2
        )
        
        # Add cycle duration
        fig.add_trace(
            go.Scatter(
                x=cycle_times,
                y=durations,
                mode='lines+markers',
                name='Cycle Duration (s)',
                marker=dict(color='purple')
            ),
            row=2, col=1
        )
        
        # Add parameter adaptations
        params = []
        adapt_counts = []
        
        for param, adaptations in self.parameter_adaptations.items():
            params.append(param)
            adapt_counts.append(len(adaptations))
            
        fig.add_trace(
            go.Bar(
                x=params,
                y=adapt_counts,
                name='Parameter Adaptations',
                marker=dict(color='teal')
            ),
            row=2, col=2
        )
        
        # Add circuit breaker events if available
        if self.circuit_breaker_events:
            cb_times = []
            cb_status = []
            
            for event in sorted(self.circuit_breaker_events, key=lambda x: x['timestamp']):
                cb_times.append(event['datetime'])
                cb_status.append(event['event_type'].capitalize())
                
            fig.add_trace(
                go.Scatter(
                    x=cb_times,
                    y=[1 if status == 'Tripped' else 0 for status in cb_status],
                    mode='markers',
                    name='Circuit Breaker',
                    marker=dict(
                        color=['red' if status == 'Tripped' else 'green' for status in cb_status],
                        size=12,
                        symbol='diamond'
                    ),
                    hovertemplate='%{x}<br>Status: %{text}',
                    text=cb_status
                ),
                row=1, col=1
            )
            
        # Update layout
        fig.update_layout(
            title='RAG Query Optimizer Learning Performance',
            height=800,
            showlegend=True
        )
        
        # Set y-axis ranges and titles
        fig.update_yaxes(title_text='Success (1) / Failure (0)', range=[-0.1, 1.1], row=1, col=1)
        fig.update_yaxes(title_text='Count', row=1, col=2)
        fig.update_yaxes(title_text='Duration (seconds)', row=2, col=1)
        fig.update_yaxes(title_text='Adaptation Count', row=2, col=2)
        
        # Save if output file is specified
        if output_file:
            fig.write_html(output_file)
            
        return fig
        
    def _create_static_learning_visualization(self, output_file=None):
        """Create static matplotlib visualization of learning metrics."""
        # Sort events by timestamp
        sorted_events = sorted(self.learning_events, key=lambda x: x['timestamp'])
        
        # Extract data for visualization
        cycle_times = [event['datetime'] for event in sorted_events]
        success_status = [event.get('is_success', False) for event in sorted_events]
        analyzed_queries = [event.get('analyzed_queries', 0) for event in sorted_events]
        rules_generated = [event.get('rules_generated', 0) for event in sorted_events]
        durations = [event.get('duration', 0) for event in sorted_events]
        
        # Create figure with subplots
        fig, axes = plt.subplots(2, 2, figsize=(12, 8))
        
        # Plot 1: Learning cycle success status
        ax = axes[0, 0]
        ax.scatter(
            cycle_times,
            [1 if s else 0 for s in success_status],
            c=['green' if s else 'red' for s in success_status],
            marker='o',
            s=50
        )
        
        # Add circuit breaker events if available
        if self.circuit_breaker_events:
            cb_sorted = sorted(self.circuit_breaker_events, key=lambda x: x['timestamp'])
            cb_times = [event['datetime'] for event in cb_sorted]
            cb_types = [event['event_type'] for event in cb_sorted]
            
            ax.scatter(
                cb_times,
                [1 if t == 'reset' else 0 for t in cb_types],
                c=['green' if t == 'reset' else 'red' for t in cb_types],
                marker='d',
                s=80,
                label='Circuit Breaker'
            )
            
        ax.set_ylim(-0.1, 1.1)
        ax.set_yticks([0, 1])
        ax.set_yticklabels(['Failure', 'Success'])
        ax.set_title('Learning Cycle Status')
        ax.set_xlabel('Time')
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
        
        # Plot 2: Queries analyzed vs rules generated
        ax = axes[0, 1]
        ax.plot(cycle_times, analyzed_queries, 'b-o', label='Queries Analyzed')
        ax.plot(cycle_times, rules_generated, 'orange', marker='o', linestyle='-', label='Rules Generated')
        ax.set_title('Queries Analyzed vs Rules Generated')
        ax.set_xlabel('Time')
        ax.set_ylabel('Count')
        ax.legend()
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
        
        # Plot 3: Cycle duration
        ax = axes[1, 0]
        ax.plot(cycle_times, durations, 'purple', marker='o', linestyle='-')
        ax.set_title('Cycle Duration')
        ax.set_xlabel('Time')
        ax.set_ylabel('Duration (seconds)')
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
        
        # Plot 4: Parameter adaptations
        ax = axes[1, 1]
        params = []
        adapt_counts = []
        
        for param, adaptations in self.parameter_adaptations.items():
            params.append(param)
            adapt_counts.append(len(adaptations))
            
        ax.bar(params, adapt_counts, color='teal')
        ax.set_title('Parameter Adaptations')
        ax.set_xlabel('Parameter')
        ax.set_ylabel('Adaptation Count')
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
        
        # Adjust layout
        plt.suptitle('RAG Query Optimizer Learning Performance', fontsize=16)
        plt.tight_layout()
        plt.subplots_adjust(top=0.9)
        
        # Save if output file is specified
        if output_file:
            plt.savefig(output_file, dpi=100, bbox_inches='tight')
            
        return fig
        
    def _calculate_change(self, old_value, new_value):
        """
        Calculate relative change between values.
        
        Args:
            old_value: Previous value
            new_value: New value
            
        Returns:
            float: Relative change or None if not calculable
        """
        try:
            # Handle different types
            if isinstance(old_value, (int, float)) and isinstance(new_value, (int, float)):
                # Don't divide by zero
                if old_value == 0:
                    return None
                return (new_value - old_value) / old_value
            
            # For lists, calculate length change
            if isinstance(old_value, list) and isinstance(new_value, list):
                old_len = len(old_value)
                new_len = len(new_value)
                
                # Don't divide by zero
                if old_len == 0:
                    return None
                    
                return (new_len - old_len) / old_len
                
            # For other types, return None
            return None
        except Exception:
            return None
            
    def _check_if_active(self, events):
        """
        Check if learning appears to be active based on recent events.
        
        Args:
            events: List of recent learning events
            
        Returns:
            bool: True if learning appears active, False otherwise
        """
        # If no events, learning is not active
        if not events:
            return False
            
        # Check circuit breaker status
        if self.circuit_breaker_events:
            latest_cb = max(self.circuit_breaker_events, key=lambda x: x['timestamp'])
            if latest_cb['event_type'] == 'tripped':
                # Check if we're past the retry time
                if 'retry_time' in latest_cb and time.time() < latest_cb['retry_time']:
                    return False
                    
        # Learning is active if there are recent events with at least one success
        return any(event.get('is_success', False) for event in events)


def integrate_with_audit_system(query_metrics: QueryMetricsCollector, 
                            audit_alert_manager: Any,
                            audit_logger: Any) -> None:
    """
    Integrate query metrics with the audit system.
    
    This function sets up bidirectional integration between the query metrics
    system and the audit logging/alerting system, allowing both systems to
    share information about anomalies.
    
    Args:
        query_metrics: QueryMetricsCollector instance
        audit_alert_manager: AuditAlertManager instance from audit system
        audit_logger: AuditLogger instance for logging query events
    """
    # Set up handlers to forward query anomalies to audit system
    def query_anomaly_to_audit(anomaly: Dict[str, Any]) -> None:
        try:
            # Log the anomaly to the audit system
            if audit_logger:
                # Determine audit level based on severity
                level = 'INFO'
                if anomaly.get('severity') == 'medium':
                    level = 'WARNING'
                elif anomaly.get('severity') == 'high':
                    level = 'ERROR'
                elif anomaly.get('severity') == 'critical':
                    level = 'CRITICAL'
                
                # Log with appropriate category
                audit_logger.log(
                    level=level,
                    category='RAG_QUERY',
                    action=anomaly.get('type', 'query_anomaly'),
                    status='alert',
                    details={
                        'anomaly_type': anomaly.get('type'),
                        'severity': anomaly.get('severity'),
                        'value': anomaly.get('value'),
                        'query_id': anomaly.get('query_id'),
                        'timestamp': anomaly.get('timestamp')
                    }
                )
            
            # Create security alert if it's a serious anomaly
            if audit_alert_manager and anomaly.get('severity') in ['high', 'critical']:
                # Convert query anomaly to audit anomaly format
                audit_anomaly = {
                    'type': anomaly.get('type', 'query_anomaly'),
                    'severity': anomaly.get('severity', 'low'),
                    'z_score': anomaly.get('ratio', 2.0),  # Use ratio as z-score estimate
                    'value': anomaly.get('value'),
                    'mean': anomaly.get('average') if 'average' in anomaly else None,
                    'timestamp': anomaly.get('timestamp'),
                }
                
                # Send to audit alert manager
                audit_alert_manager.handle_anomaly_alert(audit_anomaly)
                
        except Exception as e:
            logging.error(f"Error forwarding query anomaly to audit system: {str(e)}")
    
    # Register the handler with query metrics
    query_metrics.add_alert_handler(query_anomaly_to_audit)
    
    # Log integration status
    logging.info("Successfully integrated query metrics with audit system")


def create_dashboard(
    output_file: str,
    query_metrics: QueryMetricsCollector,
    audit_metrics = None,
    title: str = "RAG Query Dashboard",
    include_anomalies: bool = True
) -> str:
    """
    Generate a comprehensive dashboard for RAG query analysis.
    
    This function creates a dashboard HTML file with visualizations of query metrics,
    anomaly information, and integrated audit data if available.
    
    Args:
        output_file: Path to save the dashboard HTML file
        query_metrics: QueryMetricsCollector with query metrics
        audit_metrics: Optional AuditMetricsAggregator for integrated audit data
        title: Dashboard title
        include_anomalies: Whether to include anomaly information
        
    Returns:
        str: Path to the generated dashboard file
    """
    # Create visualizer
    visualizer = RAGQueryVisualizer(query_metrics)
    
    # Get anomalies if requested
    anomalies = []
    if include_anomalies:
        for metrics in query_metrics.query_metrics.values():
            # Look for anomaly data in the metrics
            if metrics.get('status') == 'anomaly' or 'anomaly_type' in metrics:
                anomaly = {
                    'type': metrics.get('anomaly_type', 'unknown_anomaly'),
                    'severity': metrics.get('severity', 'low'),
                    'timestamp': datetime.datetime.fromtimestamp(metrics.get('end_time', time.time())).isoformat(),
                    'query_id': metrics.get('query_id', 'unknown')
                }
                
                # Add specific information based on anomaly type
                if metrics.get('anomaly_type') == 'performance_anomaly':
                    anomaly['value'] = metrics.get('duration', 0)
                    anomaly['average'] = metrics.get('avg_duration', 0)
                    anomaly['ratio'] = metrics.get('duration_ratio', 1.0)
                elif metrics.get('anomaly_type') == 'empty_results_anomaly':
                    anomaly['query_text'] = metrics.get('query_params', {}).get('query_text', 'Unknown query')
                elif metrics.get('anomaly_type') == 'relevance_anomaly':
                    anomaly['value'] = metrics.get('avg_score', 0)
                
                anomalies.append(anomaly)
    
    # Generate dashboard HTML
    html = visualizer.generate_dashboard_html(
        title=title,
        include_optimization=True,
        include_patterns=True,
        anomalies=anomalies,
        audit_metrics=audit_metrics
    )
    
    # Create output directory if it doesn't exist
    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    
    # Write dashboard to file
    with open(output_file, 'w') as f:
        f.write(html)
    
    return output_file


class EnhancedQueryVisualizer(RAGQueryVisualizer):
    """
    Enhanced visualization tools for RAG query metrics with better audit integration.
    
    This class extends the base RAGQueryVisualizer with additional methods for creating
    more sophisticated visualizations and providing better integration with the audit
    visualization system. It provides comprehensive visualization of query performance,
    anomalies, and correlation with security events.
    """
    
    def visualize_query_performance_timeline(self, 
                                          hours_back: int = 24, 
                                          interval_minutes: int = 30,
                                          include_error_events: bool = True,
                                          output_file: Optional[str] = None,
                                          show_plot: bool = False) -> Any:
        """
        Create a timeline visualization of query performance.
        
        Args:
            hours_back: Number of hours to look back
            interval_minutes: Time interval in minutes for aggregation
            include_error_events: Whether to highlight error events
            output_file: Optional path to save the visualization
            show_plot: Whether to display the plot
            
        Returns:
            matplotlib.figure.Figure: The generated figure
        """
        if not VISUALIZATION_LIBS_AVAILABLE:
            logging.warning("Visualization libraries not available")
            return None
            
        try:
            # Get metrics data
            performance = self.metrics.get_performance_metrics()
            hourly_trends = performance.get('hourly_trends', {})
            
            if not hourly_trends:
                logging.warning("No performance data available for timeline")
                return None
                
            # Convert to pandas DataFrame for easier manipulation
            data = []
            for hour, stats in hourly_trends.items():
                hour_dt = datetime.datetime.strptime(hour, '%Y-%m-%d %H:00')
                data.append({
                    'timestamp': hour_dt,
                    'query_count': stats['query_count'],
                    'avg_duration': stats['avg_duration'],
                    'error_rate': stats['error_rate']
                })
                
            if not data:
                logging.warning("No timeline data available")
                return None
                
            df = pd.DataFrame(data)
            df = df.sort_values('timestamp')
            
            # Create figure with two subplots
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True, 
                                          gridspec_kw={'height_ratios': [3, 1]})
            
            # Plot query count and duration on top subplot
            color1 = '#3572C6'  # Blue for query count
            color2 = '#6AADA3'  # Teal for duration
            
            # Plot query count
            ax1.plot(df['timestamp'], df['query_count'], 'o-', color=color1, 
                    linewidth=2, markersize=6, label='Query Count')
            ax1.set_ylabel('Query Count', color=color1, fontsize=12)
            ax1.tick_params(axis='y', labelcolor=color1)
            
            # Plot duration on secondary y-axis
            ax3 = ax1.twinx()
            ax3.plot(df['timestamp'], df['avg_duration'], 'o-', color=color2, 
                   linewidth=2, markersize=6, label='Avg Duration (s)')
            ax3.set_ylabel('Avg Duration (s)', color=color2, fontsize=12)
            ax3.tick_params(axis='y', labelcolor=color2)
            
            # Add error rate on bottom subplot
            ax2.bar(df['timestamp'], df['error_rate'] * 100, color='#E57373', 
                   alpha=0.7, width=0.02, label='Error Rate (%)')
            ax2.set_ylabel('Error Rate (%)', fontsize=12)
            ax2.set_ylim(0, max(max(df['error_rate'] * 100) * 1.2, 1))
            
            # Format x-axis
            ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
            plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45, ha='right')
            
            # Add grid
            ax1.grid(True, linestyle='--', alpha=0.6)
            ax2.grid(True, linestyle='--', alpha=0.6)
            
            # Add legend
            lines1, labels1 = ax1.get_legend_handles_labels()
            lines2, labels2 = ax3.get_legend_handles_labels()
            ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')
            ax2.legend(loc='upper left')
            
            # Add title
            fig.suptitle('RAG Query Performance Timeline', fontsize=16)
            plt.tight_layout()
            
            # Save to file if output_file is specified
            if output_file:
                plt.savefig(output_file, dpi=100, bbox_inches='tight')
            
            # Show plot if requested
            if show_plot:
                plt.show()
            else:
                plt.close()
                
            return fig
            
        except Exception as e:
            logging.error(f"Error creating query performance timeline: {str(e)}")
            import traceback
            logging.error(traceback.format_exc())
            return None
    
    def visualize_query_performance_with_security_events(self,
                                               audit_metrics_aggregator,
                                               hours_back: int = 24,
                                               interval_minutes: int = 15,
                                               event_categories: List[str] = None,
                                               min_severity: str = "WARNING",
                                               output_file: Optional[str] = None,
                                               interactive: bool = True,
                                               show_plot: bool = False) -> Optional[Any]:
        """
        Create a specialized visualization showing query performance correlation with security events.
        
        This visualization highlights the relationship between RAG query performance and security
        events, helping identify if security incidents impact query performance or if performance
        anomalies correlate with security events.
        
        Args:
            audit_metrics_aggregator: AuditMetricsAggregator containing audit metrics
            hours_back: Number of hours to look back
            interval_minutes: Time interval in minutes for aggregation
            event_categories: List of audit event categories to include (None for all)
            min_severity: Minimum severity level to include ("INFO", "WARNING", "ERROR", "CRITICAL")
            output_file: Optional path to save the visualization
            interactive: Whether to create an interactive plot
            show_plot: Whether to display the plot
            
        Returns:
            matplotlib.figure.Figure or plotly.graph_objects.Figure: The generated figure
        """
        if not audit_metrics_aggregator:
            logging.warning("Audit metrics aggregator is required for security event correlation")
            return None
            
        # Use interactive visualization if available and requested
        if interactive and INTERACTIVE_VISUALIZATION_AVAILABLE:
            return self._create_interactive_security_correlation(
                audit_metrics_aggregator=audit_metrics_aggregator,
                hours_back=hours_back,
                interval_minutes=interval_minutes,
                event_categories=event_categories,
                min_severity=min_severity,
                output_file=output_file,
                show_plot=show_plot
            )
            
        if not VISUALIZATION_LIBS_AVAILABLE:
            logging.warning("Visualization libraries not available")
            return None
            
        try:
            # Define time boundaries
            end_time = datetime.datetime.now()
            start_time = end_time - datetime.timedelta(hours=hours_back)
            
            # Create figure with two subplots
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True, 
                                        gridspec_kw={'height_ratios': [3, 1]})
            
            # Plot #1: Query Performance Timeline
            # Extract query data
            query_data = []
            for query_id, metrics in self.metrics.query_metrics.items():
                if 'start_time' in metrics and 'duration' in metrics:
                    query_time = datetime.datetime.fromtimestamp(metrics['start_time'])
                    if query_time >= start_time:
                        query_data.append({
                            'timestamp': query_time,
                            'duration': metrics['duration'],
                            'status': metrics.get('status', 'unknown'),
                            'results_count': metrics.get('results_count', 0),
                            'query_id': query_id
                        })
            
            # Sort by timestamp
            query_data = sorted(query_data, key=lambda x: x['timestamp'])
            
            if query_data:
                # Extract data for plotting
                timestamps = [q['timestamp'] for q in query_data]
                durations = [q['duration'] * 1000 for q in query_data]  # Convert to ms
                statuses = [q['status'] for q in query_data]
                
                # Plot durations with color-coded points based on status
                normal_mask = [status == 'completed' for status in statuses]
                error_mask = [status == 'error' for status in statuses]
                anomaly_mask = [status == 'anomaly' for status in statuses]
                
                # Plot normal queries
                if any(normal_mask):
                    ax1.scatter(
                        [t for t, m in zip(timestamps, normal_mask) if m],
                        [d for d, m in zip(durations, normal_mask) if m],
                        color='#3572C6', s=50, alpha=0.7, label='Normal'
                    )
                    
                # Plot error queries
                if any(error_mask):
                    ax1.scatter(
                        [t for t, m in zip(timestamps, error_mask) if m],
                        [d for d, m in zip(durations, error_mask) if m],
                        color='#E57373', s=80, marker='x', label='Error'
                    )
                    
                # Plot anomaly queries
                if any(anomaly_mask):
                    ax1.scatter(
                        [t for t, m in zip(timestamps, anomaly_mask) if m],
                        [d for d, m in zip(durations, anomaly_mask) if m],
                        color='#FFD54F', s=80, marker='o', edgecolors='#FF8F00', linewidth=2, label='Anomaly'
                    )
                
                # Add trend line
                if len(durations) > 1:
                    try:
                        z = np.polyfit(range(len(durations)), durations, 1)
                        p = np.poly1d(z)
                        ax1.plot(timestamps, p(range(len(durations))), 
                               'r--', linewidth=2, alpha=0.7, label='Trend')
                    except Exception as e:
                        logging.warning(f"Error creating trend line: {str(e)}")
            else:
                ax1.text(0.5, 0.5, 'No query data in selected time period', 
                      horizontalalignment='center', verticalalignment='center',
                      transform=ax1.transAxes, fontsize=12)
            
            # Configure query plot
            ax1.set_title('RAG Query Performance Timeline', fontsize=14)
            ax1.set_ylabel('Duration (ms)', fontsize=12)
            ax1.grid(True, linestyle='--', alpha=0.6)
            if query_data:
                ax1.legend(loc='upper right', fontsize=10)
            
            # Plot #2: Security Events
            # Get security events from audit metrics
            security_events = []
            
            # Process event data from audit metrics aggregator
            # This requires access to the event data in the metrics aggregator
            try:
                # Get events from audit metrics
                raw_events = audit_metrics_aggregator.get_events_in_timeframe(
                    start_time=start_time.timestamp(),
                    end_time=end_time.timestamp(),
                    categories=event_categories,
                    min_level=min_severity
                )
                
                # Process events
                for event in raw_events:
                    event_time = datetime.datetime.fromtimestamp(event.get('timestamp', 0))
                    security_events.append({
                        'timestamp': event_time,
                        'level': event.get('level', 'UNKNOWN'),
                        'category': event.get('category', 'UNKNOWN'),
                        'action': event.get('action', 'UNKNOWN'),
                        'status': event.get('status', 'UNKNOWN')
                    })
            except Exception as e:
                logging.warning(f"Error retrieving security events: {str(e)}")
            
            # Sort events by timestamp
            security_events = sorted(security_events, key=lambda x: x['timestamp'])
            
            if security_events:
                # Create a scatter plot with color-coded points by level
                level_colors = {
                    'DEBUG': '#7FDBFF',
                    'INFO': '#2ECC40',
                    'WARNING': '#FFDC00',
                    'ERROR': '#FF4136',
                    'CRITICAL': '#B10DC9',
                    'EMERGENCY': '#85144b'
                }
                
                for level in ['CRITICAL', 'ERROR', 'WARNING', 'INFO']:
                    level_events = [e for e in security_events if e['level'] == level]
                    if level_events:
                        event_times = [e['timestamp'] for e in level_events]
                        # Use y=0 for all events since we're just marking their occurrence
                        event_y = [0] * len(event_times)
                        
                        ax2.scatter(
                            event_times, event_y,
                            s=100 if level in ['CRITICAL', 'ERROR'] else 60,
                            color=level_colors.get(level, '#AAAAAA'),
                            label=f"{level} ({len(level_events)})",
                            alpha=0.8,
                            edgecolors='white' if level in ['CRITICAL', 'ERROR'] else None,
                            linewidth=1 if level in ['CRITICAL', 'ERROR'] else 0
                        )
                
                # Add event counts by interval
                # Create time buckets
                bucket_size = datetime.timedelta(minutes=interval_minutes)
                buckets = {}
                current_bucket = start_time
                
                while current_bucket <= end_time:
                    buckets[current_bucket] = 0
                    current_bucket += bucket_size
                
                # Count events in each bucket
                for event in security_events:
                    for bucket_time in buckets:
                        if bucket_time <= event['timestamp'] < bucket_time + bucket_size:
                            buckets[bucket_time] += 1
                            break
                
                # Plot event counts as a step chart behind the points
                bucket_times = list(buckets.keys())
                bucket_counts = list(buckets.values())
                
                if any(bucket_counts):  # Only plot if there are events
                    # Normalize to the plot height (0 to 1)
                    max_count = max(bucket_counts) if bucket_counts else 1
                    norm_counts = [count / max_count for count in bucket_counts]
                    
                    ax2.step(
                        bucket_times, norm_counts,
                        where='post', color='#AAAAAA', alpha=0.3,
                        linewidth=1, zorder=0
                    )
                    
                    # Add a secondary y-axis for the counts
                    ax2_right = ax2.twinx()
                    ax2_right.set_ylim(0, max_count * 1.1)
                    ax2_right.set_ylabel('Event Count', fontsize=10)
                    ax2_right.tick_params(axis='y', labelsize=8)
                
                # Set axes properties
                ax2.set_ylim(-0.1, 1.1)
                ax2.set_yticks([])  # Hide the y-ticks since they're meaningless
                ax2.legend(loc='upper right', fontsize=9)
            else:
                ax2.text(0.5, 0.5, 'No security events in selected time period', 
                       horizontalalignment='center', verticalalignment='center',
                       transform=ax2.transAxes, fontsize=12)
            
            # Configure security event plot
            ax2.set_title('Security Events', fontsize=14)
            ax2.set_xlabel('Time', fontsize=12)
            ax2.grid(True, linestyle='--', alpha=0.6)
            
            # Format time axis
            ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
            plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45, ha='right')
            
            # Add overall title
            fig.suptitle('Query Performance & Security Event Correlation', fontsize=16)
            
            # Adjust layout
            plt.tight_layout()
            plt.subplots_adjust(top=0.9)
            
            # Save if output file is specified
            if output_file:
                plt.savefig(output_file, dpi=100, bbox_inches='tight')
            
            # Show if requested
            if show_plot:
                plt.show()
            else:
                plt.close()
                
            return fig
            
        except Exception as e:
            logging.error(f"Error creating security correlation visualization: {str(e)}")
            import traceback
            logging.error(traceback.format_exc())
            return None
            
    def visualize_query_audit_timeline(self, 
                                    audit_metrics_aggregator,
                                    hours_back: int = 24, 
                                    interval_minutes: int = 30,
                                    theme: str = 'light',
                                    title: str = "Query Performance & Audit Events Timeline",
                                    figsize: Tuple[int, int] = (12, 8),
                                    output_file: Optional[str] = None,
                                    interactive: bool = False,
                                    show_plot: bool = False) -> Optional[Any]:
        """
        Create an integrated timeline showing both RAG queries and audit events.
        
        Args:
            audit_metrics_aggregator: AuditMetricsAggregator containing audit metrics
            hours_back: Number of hours to look back
            interval_minutes: Time interval in minutes for aggregation
            theme: 'light' or 'dark' color theme
            title: Title for the visualization
            figsize: Figure size (width, height) in inches
            output_file: Optional path to save the visualization
            interactive: Whether to create an interactive plot (requires plotly)
            show_plot: Whether to display the plot
            
        Returns:
            matplotlib.figure.Figure or plotly.graph_objects.Figure: The generated figure
        """
        if interactive and INTERACTIVE_VISUALIZATION_AVAILABLE:
            return self._create_interactive_query_audit_timeline(
                audit_metrics_aggregator=audit_metrics_aggregator,
                hours_back=hours_back,
                interval_minutes=interval_minutes,
                theme=theme,
                title=title,
                output_file=output_file,
                show_plot=show_plot
            )
        
        try:
            # Import the create_query_audit_timeline function from audit_visualization
            from ipfs_datasets_py.audit.audit_visualization import create_query_audit_timeline
            
            # Create the timeline visualization
            fig = create_query_audit_timeline(
                query_metrics_collector=self.metrics,
                audit_metrics=audit_metrics_aggregator,
                hours_back=hours_back,
                interval_minutes=interval_minutes,
                theme=theme,
                figsize=figsize,
                output_file=output_file,
                show_plot=show_plot
            )
            
            return fig
            
        except ImportError:
            logging.error("Audit visualization module not available")
            return None
        except Exception as e:
            logging.error(f"Error creating query audit timeline: {str(e)}")
            import traceback
            logging.error(traceback.format_exc())
            return None
            
    def _create_interactive_security_correlation(self,
                                           audit_metrics_aggregator,
                                           hours_back: int = 24,
                                           interval_minutes: int = 15,
                                           event_categories: List[str] = None,
                                           min_severity: str = "WARNING",
                                           output_file: Optional[str] = None,
                                           show_plot: bool = False) -> Optional[Any]:
        """
        Create an interactive visualization of security events and query performance correlation.
        
        This advanced visualization combines query performance metrics with security events
        to help identify potential correlations between security incidents and query performance
        issues. The interactive plot allows drilling down into specific time periods and events
        to investigate anomalies and understand the relationship between security posture and
        system performance.
        
        Args:
            audit_metrics_aggregator: AuditMetricsAggregator containing audit metrics
            hours_back: Number of hours to look back
            interval_minutes: Time interval in minutes for aggregation
            event_categories: List of audit event categories to include (None for all)
            min_severity: Minimum severity level to include
            output_file: Optional path to save the visualization
            show_plot: Whether to display the plot
            
        Returns:
            plotly.graph_objects.Figure: The interactive figure
        """
        if not INTERACTIVE_VISUALIZATION_AVAILABLE:
            logging.error("Interactive visualization libraries not available")
            return None
            
        try:
            # Define time boundaries
            end_time = datetime.datetime.now()
            start_time = end_time - datetime.timedelta(hours=hours_back)
            
            # Extract query data
            query_data = []
            for query_id, metrics in self.metrics.query_metrics.items():
                if 'start_time' in metrics and 'duration' in metrics:
                    query_time = datetime.datetime.fromtimestamp(metrics['start_time'])
                    if query_time >= start_time:
                        query_data.append({
                            'timestamp': query_time,
                            'duration': metrics['duration'] * 1000,  # Convert to ms
                            'status': metrics.get('status', 'unknown'),
                            'results_count': metrics.get('results_count', 0),
                            'query_id': query_id,
                            'query_text': metrics.get('query_params', {}).get('query_text', 'Unknown query')
                        })
            
            # Sort by timestamp
            query_data = sorted(query_data, key=lambda x: x['timestamp'])
            
            # Get security events from audit metrics
            security_events = []
            
            try:
                # Get events from audit metrics
                raw_events = audit_metrics_aggregator.get_events_in_timeframe(
                    start_time=start_time.timestamp(),
                    end_time=end_time.timestamp(),
                    categories=event_categories,
                    min_level=min_severity
                )
                
                # Process events
                for event in raw_events:
                    event_time = datetime.datetime.fromtimestamp(event.get('timestamp', 0))
                    security_events.append({
                        'timestamp': event_time,
                        'level': event.get('level', 'UNKNOWN'),
                        'category': event.get('category', 'UNKNOWN'),
                        'action': event.get('action', 'UNKNOWN'),
                        'status': event.get('status', 'UNKNOWN'),
                        'details': event.get('details', {})
                    })
            except Exception as e:
                logging.warning(f"Error retrieving security events: {str(e)}")
            
            # Sort events by timestamp
            security_events = sorted(security_events, key=lambda x: x['timestamp'])
            
            # Create figure with subplots
            fig = make_subplots(
                rows=2, cols=1,
                shared_xaxes=True,
                vertical_spacing=0.1,
                subplot_titles=(
                    "RAG Query Performance",
                    "Security Events"
                ),
                row_heights=[0.7, 0.3]
            )
            
            # Add query performance data
            if query_data:
                # Group by status
                normal_queries = [q for q in query_data if q['status'] == 'completed']
                error_queries = [q for q in query_data if q['status'] == 'error']
                anomaly_queries = [q for q in query_data if q['status'] == 'anomaly']
                
                # Add normal queries
                if normal_queries:
                    fig.add_trace(
                        go.Scatter(
                            x=[q['timestamp'] for q in normal_queries],
                            y=[q['duration'] for q in normal_queries],
                            mode='markers',
                            name='Normal Queries',
                            marker=dict(color='#3572C6', size=8, opacity=0.7),
                            hovertemplate='<b>%{x}</b><br>Duration: %{y:.1f}ms<br>%{text}',
                            text=[q['query_text'][:50] for q in normal_queries]
                        ),
                        row=1, col=1
                    )
                
                # Add error queries
                if error_queries:
                    fig.add_trace(
                        go.Scatter(
                            x=[q['timestamp'] for q in error_queries],
                            y=[q['duration'] for q in error_queries],
                            mode='markers',
                            name='Error Queries',
                            marker=dict(
                                color='#E57373', 
                                size=10, 
                                symbol='x',
                                line=dict(width=2, color='#C62828')
                            ),
                            hovertemplate='<b>%{x}</b><br>Duration: %{y:.1f}ms<br>ERROR: %{text}',
                            text=[q['query_text'][:50] for q in error_queries]
                        ),
                        row=1, col=1
                    )
                
                # Add anomaly queries
                if anomaly_queries:
                    fig.add_trace(
                        go.Scatter(
                            x=[q['timestamp'] for q in anomaly_queries],
                            y=[q['duration'] for q in anomaly_queries],
                            mode='markers',
                            name='Anomaly Queries',
                            marker=dict(
                                color='#FFD54F', 
                                size=10, 
                                symbol='circle',
                                line=dict(width=2, color='#FF8F00')
                            ),
                            hovertemplate='<b>%{x}</b><br>Duration: %{y:.1f}ms<br>ANOMALY: %{text}',
                            text=[q['query_text'][:50] for q in anomaly_queries]
                        ),
                        row=1, col=1
                    )
                
                # Add trend line if we have multiple points
                if len(query_data) > 1:
                    # Calculate trend
                    x_values = list(range(len(query_data)))
                    y_values = [q['duration'] for q in query_data]
                    
                    try:
                        z = np.polyfit(x_values, y_values, 1)
                        p = np.poly1d(z)
                        
                        fig.add_trace(
                            go.Scatter(
                                x=[q['timestamp'] for q in query_data],
                                y=p(x_values),
                                mode='lines',
                                name='Trend',
                                line=dict(color='red', width=2, dash='dash'),
                                opacity=0.7
                            ),
                            row=1, col=1
                        )
                    except Exception as e:
                        logging.warning(f"Error creating trend line: {str(e)}")
            
            # Add security events
            if security_events:
                # Group by level
                level_groups = {}
                for level in ['CRITICAL', 'ERROR', 'WARNING', 'INFO']:
                    level_groups[level] = [e for e in security_events if e['level'] == level]
                
                # Level colors
                level_colors = {
                    'DEBUG': '#7FDBFF',
                    'INFO': '#2ECC40',
                    'WARNING': '#FFDC00',
                    'ERROR': '#FF4136',
                    'CRITICAL': '#B10DC9',
                    'EMERGENCY': '#85144b'
                }
                
                # Add each level as a separate trace
                for level, events in level_groups.items():
                    if events:
                        hover_texts = []
                        for event in events:
                            # Create hover text with important details
                            text = f"Level: {event['level']}<br>"
                            text += f"Category: {event['category']}<br>"
                            text += f"Action: {event['action']}<br>"
                            text += f"Status: {event['status']}"
                            
                            # Add additional details if available
                            if event.get('details'):
                                text += "<br>Details:<br>"
                                for k, v in event['details'].items()[:3]:  # Limit to 3 details
                                    text += f"- {k}: {str(v)[:50]}<br>"
                                
                            hover_texts.append(text)
                        
                        # Add scatter plot with all points at y=0
                        fig.add_trace(
                            go.Scatter(
                                x=[e['timestamp'] for e in events],
                                y=[0] * len(events),  # All at y=0
                                mode='markers',
                                name=f"{level} Events ({len(events)})",
                                marker=dict(
                                    color=level_colors.get(level, '#AAAAAA'),
                                    size=12 if level in ['CRITICAL', 'ERROR'] else 8,
                                    symbol='diamond' if level in ['CRITICAL', 'ERROR'] else 'circle',
                                    line=dict(width=1, color='white') if level in ['CRITICAL', 'ERROR'] else None
                                ),
                                hovertemplate='<b>%{x}</b><br>%{text}',
                                text=hover_texts
                            ),
                            row=2, col=1
                        )
                
                # Add event density
                # Create time buckets for histogram
                bucket_size = datetime.timedelta(minutes=interval_minutes)
                bucket_starts = []
                current_bucket = start_time
                
                while current_bucket <= end_time:
                    bucket_starts.append(current_bucket)
                    current_bucket += bucket_size
                
                # Count events in each bucket
                bucket_counts = [0] * len(bucket_starts)
                for event in security_events:
                    for i, bucket_time in enumerate(bucket_starts):
                        if i < len(bucket_starts) - 1:
                            next_bucket = bucket_starts[i + 1]
                        else:
                            next_bucket = bucket_time + bucket_size
                            
                        if bucket_time <= event['timestamp'] < next_bucket:
                            bucket_counts[i] += 1
                            break
                
                if any(bucket_counts):  # Only add if we have events
                    fig.add_trace(
                        go.Bar(
                            x=bucket_starts,
                            y=bucket_counts,
                            name='Event Density',
                            marker_color='rgba(55, 83, 109, 0.3)',
                            opacity=0.5,
                            hovertemplate='<b>%{x}</b><br>Events: %{y}'
                        ),
                        row=2, col=1
                    )
            
            # Update layout and axes
            fig.update_layout(
                title='Query Performance & Security Event Correlation',
                showlegend=True,
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
                hovermode='closest',
                template='plotly_white',
                height=800,
                margin=dict(t=100, b=50, l=80, r=80)
            )
            
            # Update y-axes
            fig.update_yaxes(title_text='Duration (ms)', row=1, col=1)
            
            # For security events, hide the y-axis ticks/labels as they're not meaningful
            fig.update_yaxes(
                showticklabels=False, 
                range=[-0.1, 1], 
                title_text='', 
                zeroline=True,
                row=2, col=1
            )
            
            # Update x-axes
            fig.update_xaxes(
                title_text='Time',
                rangebreaks=[dict(bounds=["sat", "mon"])],  # hide weekends
                row=2, col=1
            )
            
            # Add shapes to highlight security events periods
            # Find clusters of security events
            if security_events and len(security_events) > 1:
                event_clusters = []
                current_cluster = []
                cluster_window = datetime.timedelta(minutes=interval_minutes)
                
                for event in security_events:
                    if not current_cluster:
                        current_cluster = [event]
                    else:
                        last_event = current_cluster[-1]
                        time_diff = event['timestamp'] - last_event['timestamp']
                        
                        if time_diff <= cluster_window:
                            current_cluster.append(event)
                        else:
                            if len(current_cluster) >= 3:  # Only highlight clusters with 3+ events
                                event_clusters.append(current_cluster)
                            current_cluster = [event]
                
                # Don't forget to add the last cluster
                if current_cluster and len(current_cluster) >= 3:
                    event_clusters.append(current_cluster)
                
                # Add shapes for each cluster
                for i, cluster in enumerate(event_clusters):
                    cluster_start = min(e['timestamp'] for e in cluster)
                    cluster_end = max(e['timestamp'] for e in cluster)
                    
                    # Extend by half the cluster window on each side
                    cluster_start -= cluster_window / 2
                    cluster_end += cluster_window / 2
                    
                    # Check security event severity
                    has_critical = any(e['level'] == 'CRITICAL' for e in cluster)
                    has_error = any(e['level'] == 'ERROR' for e in cluster)
                    
                    # Choose color based on severity
                    if has_critical:
                        color = 'rgba(177, 13, 201, 0.2)'  # Purple for critical
                    elif has_error:
                        color = 'rgba(255, 65, 54, 0.2)'   # Red for error
                    else:
                        color = 'rgba(255, 220, 0, 0.2)'   # Yellow for warning/info
                    
                    # Add rectangle spanning both subplots
                    fig.add_shape(
                        type="rect",
                        xref="x",
                        yref="paper",
                        x0=cluster_start,
                        x1=cluster_end,
                        y0=0,
                        y1=1,
                        line=dict(width=0),
                        fillcolor=color,
                        layer="below",
                        opacity=0.5
                    )
                    
                    # Add annotation for event cluster
                    fig.add_annotation(
                        x=cluster_start + (cluster_end - cluster_start) / 2,
                        y=1,
                        xref="x",
                        yref="paper",
                        text=f"Event Cluster {i+1}",
                        showarrow=True,
                        arrowhead=2,
                        arrowcolor=color.replace('0.2', '0.6'),
                        arrowwidth=2,
                        arrowsize=1,
                        bgcolor=color.replace('0.2', '0.6'),
                        font=dict(size=10, color="white")
                    )
            
            # Save to file if specified
            if output_file:
                fig.write_html(output_file)
                
            # Show if requested
            if show_plot:
                fig.show()
                
            return fig
            
        except Exception as e:
            logging.error(f"Error creating interactive security correlation visualization: {str(e)}")
            import traceback
            logging.error(traceback.format_exc())
            return None
            
    def _create_interactive_query_audit_timeline(self,
                                              audit_metrics_aggregator,
                                              hours_back: int = 24,
                                              interval_minutes: int = 30,
                                              theme: str = 'light',
                                              title: str = "Interactive Query & Audit Timeline",
                                              output_file: Optional[str] = None,
                                              show_plot: bool = False) -> Optional[Any]:
        """
        Create an interactive timeline visualization with plotly.
        
        Args:
            audit_metrics_aggregator: AuditMetricsAggregator with audit metrics
            hours_back: Number of hours to look back
            interval_minutes: Time interval in minutes for aggregation 
            theme: 'light' or 'dark' color theme
            title: Title for the visualization
            output_file: Optional path to save the interactive HTML
            show_plot: Whether to display the plot
            
        Returns:
            plotly.graph_objects.Figure: The interactive figure object
        """
        if not INTERACTIVE_VISUALIZATION_AVAILABLE:
            logging.error("Interactive visualization libraries not available")
            return None
            
        try:
            # Define time boundaries
            end_time = datetime.datetime.now()
            start_time = end_time - datetime.timedelta(hours=hours_back)
            
            # Setup theme colors
            if theme == 'dark':
                bg_color = '#1a1a1a'
                text_color = '#f5f5f5'
                grid_color = '#444444'
                query_color = '#5E81AC'
                error_color = '#BF616A'
                warning_color = '#EBCB8B'
                info_color = '#A3BE8C'
                plot_template = 'plotly_dark'
            else:
                bg_color = '#ffffff'
                text_color = '#333333'
                grid_color = '#dddddd'
                query_color = '#3572C6'
                error_color = '#E57373'
                warning_color = '#FFD54F'
                info_color = '#81C784'
                plot_template = 'plotly_white'
            
            # Get metrics data
            performance = self.metrics.get_performance_metrics()
            
            # Create figure with subplots
            fig = make_subplots(
                rows=3, cols=1,
                shared_xaxes=True,
                vertical_spacing=0.05,
                subplot_titles=(
                    "RAG Query Performance",
                    "Audit Events by Category",
                    "Audit Events by Level"
                ),
                row_heights=[0.4, 0.3, 0.3]
            )
            
            # Plot #1: Query Performance
            # Extract query data from the collector
            query_data = []
            for query_id, metrics in self.metrics.query_metrics.items():
                if 'start_time' in metrics and 'duration' in metrics:
                    query_time = datetime.datetime.fromtimestamp(metrics['start_time'])
                    if query_time >= start_time:
                        query_data.append({
                            'timestamp': query_time,
                            'duration': metrics['duration'] * 1000,  # Convert to ms
                            'status': metrics.get('status', 'unknown'),
                            'results_count': metrics.get('results_count', 0),
                            'query_text': metrics.get('query_params', {}).get('query_text', 'Unknown query'),
                            'query_id': query_id
                        })
            
            # Sort by timestamp
            query_data = sorted(query_data, key=lambda x: x['timestamp'])
            
            # Extract timestamps and durations
            if query_data:
                timestamps = [q['timestamp'] for q in query_data]
                durations = [q['duration'] for q in query_data]
                
                # Add query duration bars with hover information
                hover_texts = [
                    f"Query ID: {q['query_id']}<br>"
                    f"Duration: {q['duration']:.2f} ms<br>"
                    f"Status: {q['status']}<br>"
                    f"Results: {q['results_count']}<br>"
                    f"Query: {q['query_text'][:50] + '...' if len(q['query_text']) > 50 else q['query_text']}"
                    for q in query_data
                ]
                
                fig.add_trace(
                    go.Bar(
                        x=timestamps,
                        y=durations,
                        name='Query Duration (ms)',
                        marker_color=query_color,
                        opacity=0.7,
                        hovertext=hover_texts,
                        hoverinfo='text'
                    ),
                    row=1, col=1
                )
                
                # Add markers for error queries
                error_queries = [q for q in query_data if q['status'] == 'error']
                if error_queries:
                    error_timestamps = [q['timestamp'] for q in error_queries]
                    error_durations = [q['duration'] for q in error_queries]
                    error_texts = [
                        f"ERROR!<br>"
                        f"Query ID: {q['query_id']}<br>"
                        f"Duration: {q['duration']:.2f} ms<br>"
                        f"Query: {q['query_text'][:50] + '...' if len(q['query_text']) > 50 else q['query_text']}"
                        for q in error_queries
                    ]
                    
                    fig.add_trace(
                        go.Scatter(
                            x=error_timestamps,
                            y=error_durations,
                            mode='markers',
                            name='Query Errors',
                            marker=dict(
                                color=error_color,
                                size=10,
                                symbol='x'
                            ),
                            hovertext=error_texts,
                            hoverinfo='text'
                        ),
                        row=1, col=1
                    )
                
                # Create running average if we have enough data
                if len(durations) >= 3:
                    window_size = min(5, len(durations))
                    running_avg = np.convolve(durations, np.ones(window_size)/window_size, mode='valid')
                    avg_timestamps = timestamps[window_size-1:]
                    
                    fig.add_trace(
                        go.Scatter(
                            x=avg_timestamps,
                            y=running_avg,
                            mode='lines',
                            name=f'{window_size}-point Avg',
                            line=dict(
                                color='white' if theme == 'dark' else 'black', 
                                width=2, 
                                dash='dash'
                            )
                        ),
                        row=1, col=1
                    )
                
                # Add performance metrics as annotations
                if 'avg_duration' in performance:
                    avg_duration = performance['avg_duration'] * 1000  # Convert to ms
                    success_rate = performance['success_rate'] * 100  # Convert to percentage
                    
                    fig.add_annotation(
                        x=0.02,
                        y=0.95,
                        xref="paper",
                        yref="paper",
                        text=f"Avg: {avg_duration:.2f}ms | Success: {success_rate:.1f}%",
                        showarrow=False,
                        font=dict(
                            family="Arial",
                            size=12,
                            color=text_color
                        ),
                        align="left",
                        bgcolor="rgba(0,0,0,0.3)" if theme == 'dark' else "rgba(255,255,255,0.7)",
                        bordercolor=grid_color,
                        borderwidth=1,
                        borderpad=4,
                        row=1,
                        col=1
                    )
            
            # Plot #2 & #3: Audit Events
            # Get audit data if available
            if audit_metrics_aggregator:
                audit_time_series = audit_metrics_aggregator.get_time_series_data()
                
                # Process category-based time series data
                categories_data = {}
                for category_action, time_series in audit_time_series.get('by_category_action', {}).items():
                    category = category_action.split('_')[0] if '_' in category_action else category_action
                    
                    if category not in categories_data:
                        categories_data[category] = []
                    
                    # Extract timestamps and counts
                    for item in time_series:
                        event_time = datetime.datetime.fromisoformat(item['timestamp'].replace('Z', '+00:00'))
                        if start_time <= event_time <= end_time:
                            categories_data[category].append({
                                'timestamp': event_time,
                                'count': item['count']
                            })
                
                # Plot each category as a separate trace
                category_colors = {
                    'AUTHENTICATION': '#8C9EFF',
                    'AUTHORIZATION': '#82B1FF',
                    'DATA_ACCESS': '#80D8FF',
                    'DATA_MODIFICATION': '#84FFFF',
                    'SYSTEM': '#A7FFEB',
                    'COMPLIANCE': '#B9F6CA',
                    'SECURITY': '#FFD180',
                    'APPLICATION': '#FFFF8D',
                    'RESOURCE': '#FF8A80',
                    'RAG_QUERY': '#FFCC80'  # Add color for RAG query category
                }
                
                for category, data_points in categories_data.items():
                    if data_points:
                        # Sort by timestamp
                        data_points = sorted(data_points, key=lambda x: x['timestamp'])
                        cat_timestamps = [d['timestamp'] for d in data_points]
                        cat_counts = [d['count'] for d in data_points]
                        
                        fig.add_trace(
                            go.Scatter(
                                x=cat_timestamps,
                                y=cat_counts,
                                mode='lines+markers',
                                name=f'{category}',
                                marker=dict(
                                    color=category_colors.get(category, '#AAAAAA'),
                                    size=6
                                ),
                                line=dict(
                                    width=2,
                                    color=category_colors.get(category, '#AAAAAA')
                                ),
                                fill='tozeroy',
                                opacity=0.7
                            ),
                            row=2, col=1
                        )
                
                # Process level-based time series data
                levels_data = {}
                for level, time_series in audit_time_series.get('by_level', {}).items():
                    if level not in levels_data:
                        levels_data[level] = []
                    
                    # Extract timestamps and counts
                    for item in time_series:
                        event_time = datetime.datetime.fromisoformat(item['timestamp'].replace('Z', '+00:00'))
                        if start_time <= event_time <= end_time:
                            levels_data[level].append({
                                'timestamp': event_time,
                                'count': item['count']
                            })
                
                # Plot each level as a separate trace
                level_colors = {
                    'DEBUG': '#7FDBFF',
                    'INFO': info_color,
                    'WARNING': warning_color,
                    'ERROR': error_color,
                    'CRITICAL': '#B10DC9',
                    'EMERGENCY': '#85144b'
                }
                
                for level, data_points in levels_data.items():
                    if data_points:
                        # Sort by timestamp
                        data_points = sorted(data_points, key=lambda x: x['timestamp'])
                        level_timestamps = [d['timestamp'] for d in data_points]
                        level_counts = [d['count'] for d in data_points]
                        
                        fig.add_trace(
                            go.Scatter(
                                x=level_timestamps,
                                y=level_counts,
                                mode='lines+markers',
                                name=f'{level}',
                                marker=dict(
                                    color=level_colors.get(level, '#AAAAAA'),
                                    size=6
                                ),
                                line=dict(
                                    width=2,
                                    color=level_colors.get(level, '#AAAAAA')
                                )
                            ),
                            row=3, col=1
                        )
            
            # Update layout
            fig.update_layout(
                title=title,
                template=plot_template,
                showlegend=True,
                legend=dict(
                    orientation='h',
                    yanchor='bottom',
                    y=1.02,
                    xanchor='right',
                    x=1
                ),
                height=800,
                margin=dict(t=100, l=50, r=50, b=50),
                hovermode='closest'
            )
            
            # Update axes
            fig.update_xaxes(
                title_text='Time',
                showgrid=True,
                gridcolor=grid_color,
                gridwidth=1,
                zeroline=False,
                rangeselector=dict(
                    buttons=list([
                        dict(count=1, label="1h", step="hour", stepmode="backward"),
                        dict(count=6, label="6h", step="hour", stepmode="backward"),
                        dict(count=12, label="12h", step="hour", stepmode="backward"),
                        dict(count=24, label="1d", step="hour", stepmode="backward"),
                        dict(step="all")
                    ])
                )
            )
            
            fig.update_yaxes(
                title_text='Duration (ms)',
                row=1, col=1,
                showgrid=True,
                gridcolor=grid_color,
                gridwidth=1,
                zeroline=False
            )
            
            fig.update_yaxes(
                title_text='Event Count',
                row=2, col=1,
                showgrid=True,
                gridcolor=grid_color,
                gridwidth=1,
                zeroline=False
            )
            
            fig.update_yaxes(
                title_text='Event Count',
                row=3, col=1,
                showgrid=True,
                gridcolor=grid_color,
                gridwidth=1,
                zeroline=False
            )
            
            # Save if output_file provided
            if output_file:
                fig.write_html(output_file)
            
            # Show plot if requested
            if show_plot:
                fig.show()
            
            return fig
            
        except Exception as e:
            logging.error(f"Error creating interactive query audit timeline: {str(e)}")
            import traceback
            logging.error(traceback.format_exc())
            return None


class PerformanceMetricsVisualizer:
    """
    Specialized visualizer for query performance metrics analysis.
    
    This class focuses on visualizing the detailed performance metrics of RAG queries,
    including processing time breakdowns, component contributions to latency,
    throughput analysis, and resource utilization patterns.
    """
    
    def __init__(self, metrics_collector: QueryMetricsCollector):
        """
        Initialize the performance metrics visualizer.
        
        Args:
            metrics_collector: QueryMetricsCollector instance with query metrics
        """
        self.metrics_collector = metrics_collector
        self.default_figsize = (10, 6)
        
    def visualize_processing_time_breakdown(self, output_file: Optional[str] = None, 
                                          top_n: int = 10, theme: str = "light") -> Union[plt.Figure, None]:
        """
        Create a visualization of processing time breakdown by component.
        
        Shows the relative contribution of different processing phases (vector search,
        graph traversal, result ranking, etc.) to total query execution time.
        
        Args:
            output_file: Optional path to save the visualization
            top_n: Number of most recent queries to include
            theme: 'light' or 'dark' theme for visualization
            
        Returns:
            Matplotlib figure or None if visualization libraries not available
        """
        if not VISUALIZATION_LIBS_AVAILABLE:
            return None
            
        # Set style based on theme
        plt.style.use('default')
        if theme == "dark":
            plt.style.use('dark_background')
            
        # Prepare data
        phase_times = {}
        phase_counts = {}
        
        # Get recent queries, sorted by timestamp (most recent first)
        recent_queries = sorted(
            self.metrics_collector.query_metrics.items(),
            key=lambda x: x[1].get('end_time', 0) if x[1].get('status') == 'completed' else 0,
            reverse=True
        )[:top_n]
        
        # Extract phase timing information
        for query_id, query_data in recent_queries:
            if query_data.get('status') != 'completed':
                continue
                
            # Extract all phase timings
            for key, value in query_data.items():
                if key.endswith('_time') and key != 'start_time' and key != 'end_time' and key != 'duration':
                    phase = key.replace('_time', '')
                    if phase not in phase_times:
                        phase_times[phase] = []
                        phase_counts[phase] = 0
                    phase_times[phase].append(value)
                    phase_counts[phase] += 1
        
        # If no phase data, return
        if not phase_times:
            if output_file:
                # Create a simple figure explaining no data available
                fig, ax = plt.subplots(figsize=self.default_figsize)
                ax.text(0.5, 0.5, "No phase timing data available", 
                      ha='center', va='center', fontsize=14)
                ax.set_axis_off()
                fig.savefig(output_file, bbox_inches='tight')
                return fig
            return None
            
        # Calculate average times for each phase
        avg_phase_times = {phase: sum(times)/len(times) for phase, times in phase_times.items()}
        
        # Create the figure
        fig, ax = plt.subplots(figsize=self.default_figsize)
        
        # Plot the breakdown
        phases = sorted(avg_phase_times.keys(), key=lambda x: avg_phase_times[x], reverse=True)
        values = [avg_phase_times[p] for p in phases]
        
        # Normalize to show percentage of total time
        total_time = sum(values)
        normalized_values = [v/total_time*100 for v in values] if total_time > 0 else values
        
        # Create bar chart
        bars = ax.bar(phases, normalized_values)
        
        # Add labels
        ax.set_title('Query Processing Time Breakdown by Component', fontsize=14)
        ax.set_xlabel('Processing Component', fontsize=12)
        ax.set_ylabel('% of Processing Time', fontsize=12)
        
        # Add value labels on top of each bar
        for bar, value, norm_value in zip(bars, values, normalized_values):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height + 1,
                  f'{value:.3f}s\n({norm_value:.1f}%)',
                  ha='center', va='bottom', fontsize=9)
        
        # Adjust layout and styling
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        
        # Save if output file specified
        if output_file:
            plt.savefig(output_file, bbox_inches='tight')
        
        return fig
        
    def visualize_latency_distribution(self, output_file: Optional[str] = None,
                                     bins: int = 20, theme: str = "light") -> Union[plt.Figure, None]:
        """
        Create a visualization of query latency distribution.
        
        Shows the distribution of query execution times with outlier detection.
        
        Args:
            output_file: Optional path to save the visualization
            bins: Number of bins for histogram
            theme: 'light' or 'dark' theme for visualization
            
        Returns:
            Matplotlib figure or None if visualization libraries not available
        """
        if not VISUALIZATION_LIBS_AVAILABLE:
            return None
            
        # Set style based on theme
        plt.style.use('default')
        if theme == "dark":
            plt.style.use('dark_background')
            
        # Collect query durations
        durations = []
        for query_id, query_data in self.metrics_collector.query_metrics.items():
            if query_data.get('status') == 'completed' and 'duration' in query_data:
                durations.append(query_data['duration'])
        
        # If no duration data, return
        if not durations:
            if output_file:
                # Create a simple figure explaining no data available
                fig, ax = plt.subplots(figsize=self.default_figsize)
                ax.text(0.5, 0.5, "No query duration data available", 
                      ha='center', va='center', fontsize=14)
                ax.set_axis_off()
                fig.savefig(output_file, bbox_inches='tight')
                return fig
            return None
        
        # Create the figure
        fig, ax = plt.subplots(figsize=self.default_figsize)
        
        # Plot histogram with KDE
        sns.histplot(durations, bins=bins, kde=True, ax=ax)
        
        # Calculate statistics
        mean_duration = np.mean(durations)
        median_duration = np.median(durations)
        p95_duration = np.percentile(durations, 95)
        
        # Add vertical lines for statistics
        ax.axvline(mean_duration, color='r', linestyle='--', 
                  label=f'Mean: {mean_duration:.3f}s')
        ax.axvline(median_duration, color='g', linestyle='--', 
                  label=f'Median: {median_duration:.3f}s')
        ax.axvline(p95_duration, color='purple', linestyle='--', 
                  label=f'95th Percentile: {p95_duration:.3f}s')
        
        # Add labels and title
        ax.set_title('Query Latency Distribution', fontsize=14)
        ax.set_xlabel('Execution Time (seconds)', fontsize=12)
        ax.set_ylabel('Frequency', fontsize=12)
        ax.legend()
        
        # Save if output file specified
        if output_file:
            plt.savefig(output_file, bbox_inches='tight')
        
        return fig
    
    def visualize_throughput_over_time(self, output_file: Optional[str] = None,
                                     interval_minutes: int = 10, hours: int = 24,
                                     theme: str = "light") -> Union[plt.Figure, None]:
        """
        Create a visualization of query throughput over time.
        
        Shows query throughput (queries per minute) over a time window.
        
        Args:
            output_file: Optional path to save the visualization
            interval_minutes: Size of time buckets in minutes
            hours: Number of hours to look back
            theme: 'light' or 'dark' theme for visualization
            
        Returns:
            Matplotlib figure or None if visualization libraries not available
        """
        if not VISUALIZATION_LIBS_AVAILABLE:
            return None
            
        # Set style based on theme
        plt.style.use('default')
        if theme == "dark":
            plt.style.use('dark_background')
            
        # Calculate time bounds
        end_time = time.time()
        start_time = end_time - (hours * 3600)
        
        # Collect query timestamps
        query_times = []
        for query_id, query_data in self.metrics_collector.query_metrics.items():
            query_start = query_data.get('start_time')
            if query_start and query_start >= start_time:
                query_times.append(query_start)
        
        # If no query data in the timeframe, return
        if not query_times:
            if output_file:
                # Create a simple figure explaining no data available
                fig, ax = plt.subplots(figsize=self.default_figsize)
                ax.text(0.5, 0.5, f"No query data available in the last {hours} hours", 
                      ha='center', va='center', fontsize=14)
                ax.set_axis_off()
                fig.savefig(output_file, bbox_inches='tight')
                return fig
            return None
        
        # Create time buckets
        bucket_size = interval_minutes * 60  # seconds
        buckets = {}
        
        current_bucket = start_time
        while current_bucket <= end_time:
            buckets[current_bucket] = 0
            current_bucket += bucket_size
        
        # Count queries in each bucket
        for query_time in query_times:
            bucket = start_time + (int((query_time - start_time) / bucket_size) * bucket_size)
            if bucket in buckets:
                buckets[bucket] += 1
        
        # Create the figure
        fig, ax = plt.subplots(figsize=self.default_figsize)
        
        # Create x-axis with datetime objects
        bucket_times = [datetime.datetime.fromtimestamp(timestamp) for timestamp in sorted(buckets.keys())]
        query_counts = [buckets[timestamp] for timestamp in sorted(buckets.keys())]
        
        # Calculate queries per minute
        queries_per_minute = [count / interval_minutes for count in query_counts]
        
        # Plot the throughput
        ax.plot(bucket_times, queries_per_minute, marker='o', linestyle='-')
        
        # Add labels and title
        ax.set_title(f'Query Throughput (Last {hours} Hours)', fontsize=14)
        ax.set_xlabel('Time', fontsize=12)
        ax.set_ylabel('Queries per Minute', fontsize=12)
        
        # Format x-axis as time
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        fig.autofmt_xdate()
        
        # Save if output file specified
        if output_file:
            plt.savefig(output_file, bbox_inches='tight')
        
        return fig
    
    def visualize_performance_by_query_complexity(self, output_file: Optional[str] = None,
                                               theme: str = "light") -> Union[plt.Figure, None]:
        """
        Create a scatter plot of query performance vs complexity.
        
        Shows how execution time correlates with query complexity measures.
        
        Args:
            output_file: Optional path to save the visualization
            theme: 'light' or 'dark' theme for visualization
            
        Returns:
            Matplotlib figure or None if visualization libraries not available
        """
        if not VISUALIZATION_LIBS_AVAILABLE:
            return None
            
        # Set style based on theme
        plt.style.use('default')
        if theme == "dark":
            plt.style.use('dark_background')
            
        # Collect complexity metrics and durations
        complexity_data = []
        
        for query_id, query_data in self.metrics_collector.query_metrics.items():
            if query_data.get('status') != 'completed' or 'duration' not in query_data:
                continue
            
            # Extract complexity measures
            params = query_data.get('query_params', {})
            traversal = params.get('traversal', {})
            
            max_depth = traversal.get('max_depth', 0)
            graph_nodes = query_data.get('graph_traversal_nodes', 0)
            vector_results = params.get('max_vector_results', 0)
            
            # Use max_depth as primary complexity measure
            # If not available, use other metrics
            if max_depth > 0:
                complexity = max_depth
                complexity_type = 'max_depth'
            elif graph_nodes > 0:
                complexity = graph_nodes
                complexity_type = 'graph_nodes'
            elif vector_results > 0:
                complexity = vector_results
                complexity_type = 'vector_results'
            else:
                continue  # Skip if no complexity measures available
            
            complexity_data.append({
                'duration': query_data['duration'],
                'complexity': complexity,
                'complexity_type': complexity_type,
                'query_id': query_id
            })
        
        # If no complexity data, return
        if not complexity_data:
            if output_file:
                # Create a simple figure explaining no data available
                fig, ax = plt.subplots(figsize=self.default_figsize)
                ax.text(0.5, 0.5, "No query complexity data available", 
                      ha='center', va='center', fontsize=14)
                ax.set_axis_off()
                fig.savefig(output_file, bbox_inches='tight')
                return fig
            return None
        
        # Convert to DataFrame for easier plotting
        df = pd.DataFrame(complexity_data)
        
        # Create the figure
        fig, ax = plt.subplots(figsize=self.default_figsize)
        
        # Plot with different colors by complexity type
        for ctype in df['complexity_type'].unique():
            subset = df[df['complexity_type'] == ctype]
            ax.scatter(subset['complexity'], subset['duration'], 
                     label=ctype, alpha=0.7)
        
        # Add regression line if enough data points
        if len(df) >= 5:
            for ctype in df['complexity_type'].unique():
                subset = df[df['complexity_type'] == ctype]
                if len(subset) >= 5:
                    x = subset['complexity']
                    y = subset['duration']
                    z = np.polyfit(x, y, 1)
                    p = np.poly1d(z)
                    ax.plot(x, p(x), linestyle='--', 
                          label=f"{ctype} trend (y={z[0]:.2f}x+{z[1]:.2f})")
        
        # Add labels and title
        ax.set_title('Query Performance vs Complexity', fontsize=14)
        ax.set_xlabel('Complexity Measure', fontsize=12)
        ax.set_ylabel('Execution Time (seconds)', fontsize=12)
        ax.legend()
        
        # Save if output file specified
        if output_file:
            plt.savefig(output_file, bbox_inches='tight')
        
        return fig
    
    def create_interactive_performance_dashboard(self, output_file: Optional[str] = None) -> Optional[str]:
        """
        Create an interactive HTML dashboard with plotly visualizations.
        
        Args:
            output_file: Path to save the HTML dashboard
            
        Returns:
            Path to the saved dashboard or None if required libraries not available
        """
        if not INTERACTIVE_VISUALIZATION_AVAILABLE or not TEMPLATE_ENGINE_AVAILABLE:
            return None
            
        # Prepare data for visualizations
        data = {
            'processing_breakdown': self._get_processing_breakdown_data(),
            'latency_distribution': self._get_latency_distribution_data(),
            'throughput': self._get_throughput_data(),
            'complexity': self._get_complexity_data()
        }
        
        # Create subplots
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=(
                'Processing Time Breakdown', 
                'Query Latency Distribution',
                'Throughput Over Time',
                'Performance vs Complexity'
            ),
            specs=[[{'type': 'bar'}, {'type': 'histogram'}],
                  [{'type': 'scatter'}, {'type': 'scatter'}]]
        )
        
        # Add processing breakdown plot
        if data['processing_breakdown']:
            phases = list(data['processing_breakdown'].keys())
            values = list(data['processing_breakdown'].values())
            
            fig.add_trace(
                go.Bar(x=phases, y=values, name='Processing Time'),
                row=1, col=1
            )
        
        # Add latency distribution plot
        if data['latency_distribution']:
            fig.add_trace(
                go.Histogram(
                    x=data['latency_distribution'],
                    name='Query Latency',
                    nbinsx=20
                ),
                row=1, col=2
            )
            
            # Add mean and median lines
            if len(data['latency_distribution']) > 0:
                mean_val = np.mean(data['latency_distribution'])
                median_val = np.median(data['latency_distribution'])
                
                fig.add_vline(
                    x=mean_val, line_dash="dash", line_color="red",
                    annotation_text=f"Mean: {mean_val:.3f}s",
                    annotation_position="top right",
                    row=1, col=2
                )
                
                fig.add_vline(
                    x=median_val, line_dash="dash", line_color="green",
                    annotation_text=f"Median: {median_val:.3f}s",
                    annotation_position="top left",
                    row=1, col=2
                )
        
        # Add throughput plot
        if data['throughput']:
            times = [entry['time'] for entry in data['throughput']]
            counts = [entry['count'] for entry in data['throughput']]
            
            fig.add_trace(
                go.Scatter(
                    x=times,
                    y=counts,
                    mode='lines+markers',
                    name='Queries per Minute'
                ),
                row=2, col=1
            )
        
        # Add complexity plot
        if data['complexity']:
            fig.add_trace(
                go.Scatter(
                    x=[entry['complexity'] for entry in data['complexity']],
                    y=[entry['duration'] for entry in data['complexity']],
                    mode='markers',
                    marker=dict(
                        size=10,
                        color=[entry['duration'] for entry in data['complexity']],
                        colorscale='Viridis',
                        showscale=True,
                        colorbar=dict(title='Duration (s)')
                    ),
                    text=[entry.get('complexity_type', '') for entry in data['complexity']],
                    name='Query Complexity'
                ),
                row=2, col=2
            )
        
        # Update layout
        fig.update_layout(
            title_text="RAG Query Performance Dashboard",
            height=800,
            showlegend=False
        )
        
        # Create HTML from template
        html_content = self._create_dashboard_html(
            plotly_figure=fig.to_html(full_html=False, include_plotlyjs='cdn'),
            title="RAG Query Performance Dashboard"
        )
        
        # Save dashboard if output_file provided
        if output_file:
            os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
        return output_file
    
    def _get_processing_breakdown_data(self) -> Dict[str, float]:
        """Get data for processing time breakdown visualization."""
        phase_times = {}
        
        # Get completed queries
        completed_queries = [
            query_data for query_id, query_data in self.metrics_collector.query_metrics.items()
            if query_data.get('status') == 'completed'
        ]
        
        # Extract phase timing information
        for query_data in completed_queries:
            # Extract all phase timings
            for key, value in query_data.items():
                if key.endswith('_time') and key != 'start_time' and key != 'end_time' and key != 'duration':
                    phase = key.replace('_time', '')
                    if phase not in phase_times:
                        phase_times[phase] = []
                    phase_times[phase].append(value)
        
        # Calculate average times for each phase
        return {phase: sum(times)/len(times) for phase, times in phase_times.items()}
    
    def _get_latency_distribution_data(self) -> List[float]:
        """Get data for latency distribution visualization."""
        durations = []
        for query_id, query_data in self.metrics_collector.query_metrics.items():
            if query_data.get('status') == 'completed' and 'duration' in query_data:
                durations.append(query_data['duration'])
        return durations
    
    def _get_throughput_data(self, hours: int = 24, interval_minutes: int = 10) -> List[Dict[str, Any]]:
        """Get data for throughput visualization."""
        # Calculate time bounds
        end_time = time.time()
        start_time = end_time - (hours * 3600)
        
        # Collect query timestamps
        query_times = []
        for query_id, query_data in self.metrics_collector.query_metrics.items():
            query_start = query_data.get('start_time')
            if query_start and query_start >= start_time:
                query_times.append(query_start)
        
        # Create time buckets
        bucket_size = interval_minutes * 60  # seconds
        buckets = {}
        
        current_bucket = start_time
        while current_bucket <= end_time:
            buckets[current_bucket] = 0
            current_bucket += bucket_size
        
        # Count queries in each bucket
        for query_time in query_times:
            bucket = start_time + (int((query_time - start_time) / bucket_size) * bucket_size)
            if bucket in buckets:
                buckets[bucket] += 1
        
        # Convert to list of dicts with datetime objects
        return [
            {
                'time': datetime.datetime.fromtimestamp(timestamp),
                'count': count / interval_minutes  # queries per minute
            }
            for timestamp, count in sorted(buckets.items())
        ]
    
    def _get_complexity_data(self) -> List[Dict[str, Any]]:
        """Get data for complexity visualization."""
        complexity_data = []
        
        for query_id, query_data in self.metrics_collector.query_metrics.items():
            if query_data.get('status') != 'completed' or 'duration' not in query_data:
                continue
            
            # Extract complexity measures
            params = query_data.get('query_params', {})
            traversal = params.get('traversal', {})
            
            max_depth = traversal.get('max_depth', 0)
            graph_nodes = query_data.get('graph_traversal_nodes', 0)
            vector_results = params.get('max_vector_results', 0)
            
            # Use max_depth as primary complexity measure
            # If not available, use other metrics
            if max_depth > 0:
                complexity = max_depth
                complexity_type = 'max_depth'
            elif graph_nodes > 0:
                complexity = graph_nodes
                complexity_type = 'graph_nodes'
            elif vector_results > 0:
                complexity = vector_results
                complexity_type = 'vector_results'
            else:
                continue  # Skip if no complexity measures available
            
            complexity_data.append({
                'duration': query_data['duration'],
                'complexity': complexity,
                'complexity_type': complexity_type,
                'query_id': query_id
            })
            
        return complexity_data
    
    def _create_dashboard_html(self, plotly_figure: str, title: str) -> str:
        """Create HTML dashboard from template."""
        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>{{ title }}</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body {
                    font-family: Arial, sans-serif;
                    margin: 0;
                    padding: 20px;
                    background-color: #f5f5f5;
                }
                .dashboard-container {
                    background-color: white;
                    border-radius: 5px;
                    box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                    padding: 20px;
                    margin-bottom: 20px;
                }
                h1, h2 {
                    color: #333;
                }
                .timestamp {
                    color: #666;
                    font-size: 0.8em;
                    margin-bottom: 20px;
                }
            </style>
        </head>
        <body>
            <div class="dashboard-container">
                <h1>{{ title }}</h1>
                <div class="timestamp">Generated on: {{ timestamp }}</div>
                <div id="plotly-dashboard">
                    {{ plotly_figure }}
                </div>
            </div>
        </body>
        </html>
        """
        
        template = Template(html_template)
        return template.render(
            title=title,
            plotly_figure=plotly_figure,
            timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )


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
    
    def __init__(self):
        """Initialize the metrics collector."""
        self.learning_cycles = []
        self.parameter_adaptations = []
        self.strategy_effectiveness = defaultdict(list)
        self.query_patterns = defaultdict(int)
        self.learning_start_time = time.time()
        self.total_analyzed_queries = 0
        self.total_optimized_queries = 0
        self.optimization_improvements = []
        self.lock = threading.RLock()
    
    def record_learning_cycle(self, 
                             cycle_id: str,
                             start_time: float,
                             end_time: float,
                             analyzed_queries: int,
                             learned_patterns: Dict[str, Any],
                             parameter_changes: Dict[str, Tuple[float, float]],
                             success: bool = True,
                             error: Optional[str] = None) -> None:
        """
        Record metrics for a completed learning cycle.
        
        Args:
            cycle_id: Unique identifier for the learning cycle
            start_time: Start timestamp of the cycle
            end_time: End timestamp of the cycle
            analyzed_queries: Number of queries analyzed in this cycle
            learned_patterns: Patterns identified during learning
            parameter_changes: Parameter values before and after learning
            success: Whether the learning cycle was successful
            error: Optional error message if the cycle failed
        """
        with self.lock:
            self.learning_cycles.append({
                'cycle_id': cycle_id,
                'start_time': start_time,
                'end_time': end_time,
                'duration': end_time - start_time,
                'analyzed_queries': analyzed_queries,
                'learned_patterns': learned_patterns,
                'parameter_changes': parameter_changes,
                'success': success,
                'error': error,
                'timestamp': datetime.datetime.now().isoformat()
            })
            
            self.total_analyzed_queries += analyzed_queries
    
    def record_parameter_adaptation(self,
                                  parameter_name: str,
                                  old_value: float,
                                  new_value: float,
                                  adaptation_reason: str,
                                  confidence: float,
                                  affected_strategies: List[str],
                                  timestamp: Optional[float] = None) -> None:
        """
        Record a parameter adaptation event.
        
        Args:
            parameter_name: Name of the parameter that was adapted
            old_value: Parameter value before adaptation
            new_value: Parameter value after adaptation
            adaptation_reason: Reason for the adaptation
            confidence: Confidence level in the adaptation (0.0-1.0)
            affected_strategies: List of strategies affected by this parameter
            timestamp: Optional timestamp for the adaptation (defaults to now)
        """
        with self.lock:
            self.parameter_adaptations.append({
                'parameter': parameter_name,
                'old_value': old_value,
                'new_value': new_value,
                'change': new_value - old_value,
                'percent_change': ((new_value - old_value) / old_value) * 100 if old_value != 0 else float('inf'),
                'reason': adaptation_reason,
                'confidence': confidence,
                'affected_strategies': affected_strategies,
                'timestamp': timestamp if timestamp is not None else time.time(),
                'datetime': datetime.datetime.now().isoformat()
            })
    
    def record_strategy_effectiveness(self,
                                    strategy_name: str,
                                    query_count: int,
                                    success_rate: float,
                                    avg_performance_score: float,
                                    improvement_over_baseline: float) -> None:
        """
        Record effectiveness metrics for an optimization strategy.
        
        Args:
            strategy_name: Name of the optimization strategy
            query_count: Number of queries using this strategy
            success_rate: Success rate of the strategy (0.0-1.0)
            avg_performance_score: Average performance score
            improvement_over_baseline: Improvement compared to baseline strategy
        """
        with self.lock:
            self.strategy_effectiveness[strategy_name].append({
                'timestamp': time.time(),
                'datetime': datetime.datetime.now().isoformat(),
                'query_count': query_count,
                'success_rate': success_rate,
                'avg_performance_score': avg_performance_score,
                'improvement_over_baseline': improvement_over_baseline
            })
    
    def record_query_pattern(self, pattern_type: str, pattern_details: Dict[str, Any]) -> None:
        """
        Record an identified query pattern.
        
        Args:
            pattern_type: Type of the identified pattern
            pattern_details: Details about the pattern
        """
        with self.lock:
            # Create a pattern signature for counting
            pattern_signature = f"{pattern_type}:{json.dumps(pattern_details, sort_keys=True)}"
            self.query_patterns[pattern_signature] += 1
    
    def record_optimization_improvement(self, 
                                      query_id: str,
                                      before_metrics: Dict[str, Any],
                                      after_metrics: Dict[str, Any]) -> None:
        """
        Record improvement metrics for an optimized query.
        
        Args:
            query_id: Unique identifier for the query
            before_metrics: Performance metrics before optimization
            after_metrics: Performance metrics after optimization
        """
        with self.lock:
            self.optimization_improvements.append({
                'query_id': query_id,
                'timestamp': time.time(),
                'datetime': datetime.datetime.now().isoformat(),
                'before': before_metrics,
                'after': after_metrics,
                'duration_improvement': before_metrics.get('duration', 0) - after_metrics.get('duration', 0),
                'duration_improvement_percent': 
                    ((before_metrics.get('duration', 0) - after_metrics.get('duration', 0)) / 
                     before_metrics.get('duration', 1)) * 100 if before_metrics.get('duration', 0) > 0 else 0,
                'quality_improvement': after_metrics.get('quality', 0) - before_metrics.get('quality', 0),
                'strategy': after_metrics.get('strategy', 'unknown')
            })
            
            self.total_optimized_queries += 1
    
    def get_learning_metrics(self) -> Dict[str, Any]:
        """
        Get summary metrics about the learning process.
        
        Returns:
            Dict containing learning metrics and statistics
        """
        with self.lock:
            # Calculate basic stats
            total_learning_cycles = len(self.learning_cycles)
            successful_cycles = sum(1 for cycle in self.learning_cycles if cycle['success'])
            
            # Calculate parameter adaptation stats
            parameter_changes = defaultdict(list)
            for adaptation in self.parameter_adaptations:
                parameter_changes[adaptation['parameter']].append(adaptation['change'])
            
            avg_parameter_changes = {
                param: sum(changes) / len(changes) 
                for param, changes in parameter_changes.items()
                if changes
            }
            
            # Calculate strategy effectiveness
            strategy_success_rates = {}
            for strategy, metrics in self.strategy_effectiveness.items():
                if metrics:
                    # Get the most recent effectiveness data
                    latest = max(metrics, key=lambda x: x['timestamp'])
                    strategy_success_rates[strategy] = latest['success_rate']
            
            # Calculate learning rate (cycles per hour)
            learning_duration = time.time() - self.learning_start_time
            learning_rate = (total_learning_cycles / learning_duration) * 3600 if learning_duration > 0 else 0
            
            # Calculate optimization improvement metrics
            avg_duration_improvement = 0
            avg_quality_improvement = 0
            if self.optimization_improvements:
                avg_duration_improvement = sum(
                    imp.get('duration_improvement', 0) for imp in self.optimization_improvements
                ) / len(self.optimization_improvements)
                
                avg_quality_improvement = sum(
                    imp.get('quality_improvement', 0) for imp in self.optimization_improvements
                ) / len(self.optimization_improvements)
            
            # Identify top patterns
            top_patterns = Counter(self.query_patterns).most_common(5)
            
            return {
                'total_learning_cycles': total_learning_cycles,
                'successful_cycles': successful_cycles,
                'success_rate': (successful_cycles / total_learning_cycles) if total_learning_cycles > 0 else 0,
                'total_analyzed_queries': self.total_analyzed_queries,
                'total_optimized_queries': self.total_optimized_queries,
                'optimization_rate': (self.total_optimized_queries / self.total_analyzed_queries) 
                                    if self.total_analyzed_queries > 0 else 0,
                'avg_parameter_changes': avg_parameter_changes,
                'strategy_success_rates': strategy_success_rates,
                'learning_rate': learning_rate,
                'avg_duration_improvement': avg_duration_improvement,
                'avg_quality_improvement': avg_quality_improvement,
                'top_patterns': top_patterns,
                'learning_duration': learning_duration
            }
    
    def visualize_learning_cycles(self, 
                                output_file: Optional[str] = None, 
                                interactive: bool = False,
                                theme: str = 'light') -> Any:
        """
        Visualize learning cycles over time.
        
        Args:
            output_file: Optional path to save the visualization
            interactive: Whether to generate an interactive visualization
            theme: Visualization theme ('light' or 'dark')
            
        Returns:
            The visualization figure object
        """
        if not self.learning_cycles:
            logging.warning("No learning cycles data available for visualization")
            return None
        
        # Prepare data
        timestamps = [cycle['start_time'] for cycle in self.learning_cycles]
        durations = [cycle['duration'] for cycle in self.learning_cycles]
        analyzed_queries = [cycle['analyzed_queries'] for cycle in self.learning_cycles]
        success = [cycle['success'] for cycle in self.learning_cycles]
        
        # Convert timestamps to datetime objects
        dates = [datetime.datetime.fromtimestamp(ts) for ts in timestamps]
        
        if interactive and INTERACTIVE_VISUALIZATION_AVAILABLE:
            # Create interactive plot with plotly
            fig = make_subplots(
                rows=2, cols=1,
                subplot_titles=("Learning Cycle Duration", "Queries Analyzed per Cycle"),
                vertical_spacing=0.3
            )
            
            # Add duration trace
            fig.add_trace(
                go.Scatter(
                    x=dates,
                    y=durations,
                    mode='lines+markers',
                    name='Cycle Duration',
                    marker=dict(
                        color=[('green' if s else 'red') for s in success],
                        size=8
                    )
                ),
                row=1, col=1
            )
            
            # Add analyzed queries trace
            fig.add_trace(
                go.Scatter(
                    x=dates,
                    y=analyzed_queries,
                    mode='lines+markers',
                    name='Queries Analyzed',
                    marker=dict(
                        color='rgba(0, 120, 200, 0.8)',
                        size=8
                    )
                ),
                row=2, col=1
            )
            
            # Update layout
            fig.update_layout(
                title='Learning Cycles Over Time',
                template='plotly_dark' if theme == 'dark' else 'plotly_white',
                height=800,
                showlegend=True
            )
            
            # Update yaxis titles
            fig.update_yaxes(title_text="Duration (seconds)", row=1, col=1)
            fig.update_yaxes(title_text="Query Count", row=2, col=1)
            
            # Save if output file provided
            if output_file:
                fig.write_html(output_file)
                
            return fig
            
        elif VISUALIZATION_LIBS_AVAILABLE:
            # Create static plot with matplotlib
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), sharex=True)
            
            # Set background colors based on theme
            if theme == 'dark':
                plt.style.use('dark_background')
            
            # Plot durations
            success_dates = [dates[i] for i in range(len(dates)) if success[i]]
            success_durations = [durations[i] for i in range(len(durations)) if success[i]]
            
            fail_dates = [dates[i] for i in range(len(dates)) if not success[i]]
            fail_durations = [durations[i] for i in range(len(durations)) if not success[i]]
            
            ax1.plot(dates, durations, 'b-', alpha=0.5)
            ax1.scatter(success_dates, success_durations, color='green', label='Success')
            ax1.scatter(fail_dates, fail_durations, color='red', label='Failed')
            
            ax1.set_title('Learning Cycle Duration')
            ax1.set_ylabel('Duration (seconds)')
            ax1.grid(True, alpha=0.3)
            ax1.legend()
            
            # Plot analyzed queries
            ax2.plot(dates, analyzed_queries, 'b-', marker='o')
            ax2.set_title('Queries Analyzed per Learning Cycle')
            ax2.set_xlabel('Time')
            ax2.set_ylabel('Query Count')
            ax2.grid(True, alpha=0.3)
            
            # Format x-axis
            fig.autofmt_xdate()
            
            plt.tight_layout()
            
            # Save if output file provided
            if output_file:
                plt.savefig(output_file, dpi=300, bbox_inches='tight')
                plt.close(fig)
            
            return fig
            
        else:
            logging.warning("Visualization libraries not available")
            return None
    
    def visualize_parameter_adaptations(self, 
                                      output_file: Optional[str] = None, 
                                      interactive: bool = False,
                                      parameters: Optional[List[str]] = None,
                                      theme: str = 'light') -> Any:
        """
        Visualize parameter adaptations over time.
        
        Args:
            output_file: Optional path to save the visualization
            interactive: Whether to generate an interactive visualization
            parameters: Optional list of parameters to include (None for all)
            theme: Visualization theme ('light' or 'dark')
            
        Returns:
            The visualization figure object
        """
        if not self.parameter_adaptations:
            logging.warning("No parameter adaptation data available for visualization")
            return None
        
        # Group adaptations by parameter
        param_data = defaultdict(list)
        for adaptation in sorted(self.parameter_adaptations, key=lambda x: x['timestamp']):
            param_data[adaptation['parameter']].append(adaptation)
        
        # Filter parameters if specified
        if parameters:
            param_data = {k: v for k, v in param_data.items() if k in parameters}
        
        # Limit to top 5 parameters if more than 5 and no specific parameters requested
        if len(param_data) > 5 and not parameters:
            # Determine top 5 by number of adaptations
            top_params = sorted(param_data.keys(), key=lambda x: len(param_data[x]), reverse=True)[:5]
            param_data = {k: param_data[k] for k in top_params}
        
        if interactive and INTERACTIVE_VISUALIZATION_AVAILABLE:
            # Create interactive plot with plotly
            fig = go.Figure()
            
            # Add traces for each parameter
            for param, adaptations in param_data.items():
                times = [adpt['timestamp'] for adpt in adaptations]
                dates = [datetime.datetime.fromtimestamp(t) for t in times]
                values = [adpt['new_value'] for adpt in adaptations]
                confidences = [adpt['confidence'] for adpt in adaptations]
                
                # Size marker based on confidence
                sizes = [max(5, min(20, c * 20)) for c in confidences]
                
                fig.add_trace(go.Scatter(
                    x=dates,
                    y=values,
                    mode='lines+markers',
                    name=param,
                    marker=dict(size=sizes),
                    hovertemplate=(
                        "<b>%{x}</b><br>" +
                        "Value: %{y:.4f}<br>" +
                        "Confidence: %{text:.2f}" 
                    ),
                    text=confidences
                ))
            
            # Update layout
            fig.update_layout(
                title='Parameter Adaptations Over Time',
                xaxis_title='Time',
                yaxis_title='Parameter Value',
                template='plotly_dark' if theme == 'dark' else 'plotly_white',
                hovermode='closest',
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1
                )
            )
            
            # Save if output file provided
            if output_file:
                fig.write_html(output_file)
                
            return fig
            
        elif VISUALIZATION_LIBS_AVAILABLE:
            # Create static plot with matplotlib
            fig, ax = plt.subplots(figsize=(12, 8))
            
            # Set background colors based on theme
            if theme == 'dark':
                plt.style.use('dark_background')
            
            # Plot each parameter
            for param, adaptations in param_data.items():
                times = [adpt['timestamp'] for adpt in adaptations]
                dates = [datetime.datetime.fromtimestamp(t) for t in times]
                values = [adpt['new_value'] for adpt in adaptations]
                
                ax.plot(dates, values, marker='o', label=param)
            
            ax.set_title('Parameter Adaptations Over Time')
            ax.set_xlabel('Time')
            ax.set_ylabel('Parameter Value')
            ax.grid(True, alpha=0.3)
            ax.legend()
            
            # Format x-axis
            fig.autofmt_xdate()
            
            plt.tight_layout()
            
            # Save if output file provided
            if output_file:
                plt.savefig(output_file, dpi=300, bbox_inches='tight')
                plt.close(fig)
            
            return fig
            
        else:
            logging.warning("Visualization libraries not available")
            return None
    
    def visualize_strategy_effectiveness(self, 
                                       output_file: Optional[str] = None, 
                                       interactive: bool = False,
                                       theme: str = 'light') -> Any:
        """
        Visualize the effectiveness of different optimization strategies.
        
        Args:
            output_file: Optional path to save the visualization
            interactive: Whether to generate an interactive visualization
            theme: Visualization theme ('light' or 'dark')
            
        Returns:
            The visualization figure object
        """
        if not self.strategy_effectiveness:
            logging.warning("No strategy effectiveness data available for visualization")
            return None
        
        # Prepare data for visualization
        strategies = []
        success_rates = []
        improvements = []
        query_counts = []
        
        # Get the latest metrics for each strategy
        for strategy, metrics in self.strategy_effectiveness.items():
            if not metrics:
                continue
                
            # Sort by timestamp and get the latest
            latest = max(metrics, key=lambda x: x['timestamp'])
            
            strategies.append(strategy)
            success_rates.append(latest['success_rate'])
            improvements.append(latest['improvement_over_baseline'])
            query_counts.append(latest['query_count'])
        
        if not strategies:
            logging.warning("No strategy metrics available for visualization")
            return None
        
        if interactive and INTERACTIVE_VISUALIZATION_AVAILABLE:
            # Create interactive plot with plotly
            fig = make_subplots(
                rows=1, cols=2,
                subplot_titles=("Strategy Success Rates", "Improvement Over Baseline"),
                specs=[[{"type": "bar"}, {"type": "bar"}]]
            )
            
            # Sort by success rate for the first chart
            sorted_indices = sorted(range(len(success_rates)), key=lambda i: success_rates[i], reverse=True)
            sorted_strategies = [strategies[i] for i in sorted_indices]
            sorted_rates = [success_rates[i] for i in sorted_indices]
            
            # Add success rate bars
            fig.add_trace(
                go.Bar(
                    x=sorted_strategies,
                    y=sorted_rates,
                    name='Success Rate',
                    marker_color='rgba(50, 171, 96, 0.7)',
                    hovertemplate='Success Rate: %{y:.1%}<extra></extra>'
                ),
                row=1, col=1
            )
            
            # Sort by improvement for the second chart
            sorted_indices = sorted(range(len(improvements)), key=lambda i: improvements[i], reverse=True)
            sorted_strategies = [strategies[i] for i in sorted_indices]
            sorted_improvements = [improvements[i] for i in sorted_indices]
            
            # Add improvement bars
            fig.add_trace(
                go.Bar(
                    x=sorted_strategies,
                    y=sorted_improvements,
                    name='Improvement',
                    marker_color='rgba(50, 120, 200, 0.7)',
                    hovertemplate='Improvement: %{y:.2f}<extra></extra>'
                ),
                row=1, col=2
            )
            
            # Update layout
            fig.update_layout(
                title='Optimization Strategy Effectiveness',
                template='plotly_dark' if theme == 'dark' else 'plotly_white',
                height=500,
                showlegend=False,
                yaxis=dict(tickformat='.0%')
            )
            
            # Save if output file provided
            if output_file:
                fig.write_html(output_file)
                
            return fig
            
        elif VISUALIZATION_LIBS_AVAILABLE:
            # Create static plot with matplotlib
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))
            
            # Set background colors based on theme
            if theme == 'dark':
                plt.style.use('dark_background')
            
            # Sort by success rate for first chart
            sorted_indices = sorted(range(len(success_rates)), key=lambda i: success_rates[i], reverse=True)
            sorted_strategies = [strategies[i] for i in sorted_indices]
            sorted_rates = [success_rates[i] for i in sorted_indices]
            
            # Plot success rates
            bars1 = ax1.bar(sorted_strategies, sorted_rates, color='green', alpha=0.7)
            ax1.set_title('Strategy Success Rates')
            ax1.set_xlabel('Strategy')
            ax1.set_ylabel('Success Rate')
            ax1.set_ylim(0, 1.0)
            ax1.grid(axis='y', alpha=0.3)
            
            # Add data labels
            for bar in bars1:
                height = bar.get_height()
                ax1.text(bar.get_x() + bar.get_width()/2., height + 0.01,
                        f'{height:.0%}', ha='center', va='bottom')
            
            # Sort by improvement for second chart
            sorted_indices = sorted(range(len(improvements)), key=lambda i: improvements[i], reverse=True)
            sorted_strategies = [strategies[i] for i in sorted_indices]
            sorted_improvements = [improvements[i] for i in sorted_indices]
            
            # Plot improvements
            bars2 = ax2.bar(sorted_strategies, sorted_improvements, color='blue', alpha=0.7)
            ax2.set_title('Improvement Over Baseline')
            ax2.set_xlabel('Strategy')
            ax2.set_ylabel('Improvement Factor')
            ax2.grid(axis='y', alpha=0.3)
            
            # Add data labels
            for bar in bars2:
                height = bar.get_height()
                ax2.text(bar.get_x() + bar.get_width()/2., height + 0.01,
                        f'{height:.2f}x', ha='center', va='bottom')
            
            plt.tight_layout()
            
            # Save if output file provided
            if output_file:
                plt.savefig(output_file, dpi=300, bbox_inches='tight')
                plt.close(fig)
            
            return fig
            
        else:
            logging.warning("Visualization libraries not available")
            return None
    
    def visualize_query_patterns(self, 
                               output_file: Optional[str] = None, 
                               interactive: bool = False,
                               theme: str = 'light') -> Any:
        """
        Visualize discovered query patterns.
        
        Args:
            output_file: Optional path to save the visualization
            interactive: Whether to generate an interactive visualization
            theme: Visualization theme ('light' or 'dark')
            
        Returns:
            The visualization figure object
        """
        if not self.query_patterns:
            logging.warning("No query pattern data available for visualization")
            return None
        
        # Get top patterns
        top_patterns = Counter(self.query_patterns).most_common(10)
        
        # Format pattern names
        pattern_names = []
        for pattern, _ in top_patterns:
            try:
                parts = pattern.split(':', 1)
                if len(parts) == 2:
                    pattern_type, details_json = parts
                    # Try to extract a meaningful label from the details
                    details = json.loads(details_json)
                    if 'name' in details:
                        name = f"{pattern_type}: {details['name']}"
                    elif 'type' in details:
                        name = f"{pattern_type}: {details['type']}"
                    else:
                        # Create a short hash for the details to distinguish patterns
                        import hashlib
                        short_hash = hashlib.md5(details_json.encode()).hexdigest()[:6]
                        name = f"{pattern_type}: {short_hash}"
                else:
                    name = pattern
            except:
                name = pattern
                
            # Truncate if too long
            if len(name) > 30:
                name = name[:27] + '...'
                
            pattern_names.append(name)
        
        pattern_counts = [count for _, count in top_patterns]
        
        if interactive and INTERACTIVE_VISUALIZATION_AVAILABLE:
            # Create interactive plot with plotly
            fig = go.Figure(
                go.Bar(
                    x=pattern_counts[::-1],
                    y=pattern_names[::-1],
                    orientation='h'
                )
            )
            
            # Update layout
            fig.update_layout(
                title='Top Query Patterns Detected',
                xaxis_title='Count',
                yaxis_title='Pattern',
                template='plotly_dark' if theme == 'dark' else 'plotly_white',
                height=500,
                margin=dict(l=200)  # Add more left margin for pattern names
            )
            
            # Save if output file provided
            if output_file:
                fig.write_html(output_file)
                
            return fig
            
        elif VISUALIZATION_LIBS_AVAILABLE:
            # Create static plot with matplotlib
            fig, ax = plt.subplots(figsize=(12, 8))
            
            # Set background colors based on theme
            if theme == 'dark':
                plt.style.use('dark_background')
            
            # Create horizontal bar chart (reversed to show highest on top)
            bars = ax.barh(pattern_names[::-1], pattern_counts[::-1], color='purple', alpha=0.7)
            
            ax.set_title('Top Query Patterns Detected')
            ax.set_xlabel('Count')
            ax.set_ylabel('Pattern')
            ax.grid(axis='x', alpha=0.3)
            
            # Add data labels
            for bar in bars:
                width = bar.get_width()
                ax.text(width + 0.5, bar.get_y() + bar.get_height()/2.,
                       f'{width}', ha='left', va='center')
            
            plt.tight_layout()
            
            # Save if output file provided
            if output_file:
                plt.savefig(output_file, dpi=300, bbox_inches='tight')
                plt.close(fig)
            
            return fig
            
        else:
            logging.warning("Visualization libraries not available")
            return None
    
    def visualize_learning_performance(self, 
                                     output_file: Optional[str] = None, 
                                     interactive: bool = False,
                                     theme: str = 'light') -> Any:
        """
        Visualize overall learning performance improvements.
        
        Args:
            output_file: Optional path to save the visualization
            interactive: Whether to generate an interactive visualization
            theme: Visualization theme ('light' or 'dark')
            
        Returns:
            The visualization figure object
        """
        if not self.optimization_improvements:
            logging.warning("No optimization improvement data available for visualization")
            return None
        
        # Prepare data
        improvements = sorted(self.optimization_improvements, key=lambda x: x['timestamp'])
        timestamps = [imp['timestamp'] for imp in improvements]
        dates = [datetime.datetime.fromtimestamp(ts) for ts in timestamps]
        duration_improvements = [imp['duration_improvement'] for imp in improvements]
        quality_improvements = [imp['quality_improvement'] for imp in improvements]
        
        # Calculate cumulative average improvements
        cumulative_duration_improvements = []
        cumulative_quality_improvements = []
        
        for i in range(len(improvements)):
            avg_duration = sum(duration_improvements[:i+1]) / (i+1)
            avg_quality = sum(quality_improvements[:i+1]) / (i+1)
            cumulative_duration_improvements.append(avg_duration)
            cumulative_quality_improvements.append(avg_quality)
        
        if interactive and INTERACTIVE_VISUALIZATION_AVAILABLE:
            # Create interactive plot with plotly
            fig = make_subplots(
                rows=2, cols=1,
                subplot_titles=("Cumulative Duration Improvement", "Cumulative Quality Improvement"),
                vertical_spacing=0.3
            )
            
            # Add duration improvement trace
            fig.add_trace(
                go.Scatter(
                    x=dates,
                    y=cumulative_duration_improvements,
                    mode='lines',
                    name='Duration Improvement',
                    line=dict(width=3, color='green')
                ),
                row=1, col=1
            )
            
            # Add quality improvement trace
            fig.add_trace(
                go.Scatter(
                    x=dates,
                    y=cumulative_quality_improvements,
                    mode='lines',
                    name='Quality Improvement',
                    line=dict(width=3, color='blue')
                ),
                row=2, col=1
            )
            
            # Update layout
            fig.update_layout(
                title='Cumulative Optimization Performance',
                template='plotly_dark' if theme == 'dark' else 'plotly_white',
                height=800,
                showlegend=True
            )
            
            # Update yaxis titles
            fig.update_yaxes(title_text="Average Duration Reduction (ms)", row=1, col=1)
            fig.update_yaxes(title_text="Average Quality Improvement", row=2, col=1)
            
            # Save if output file provided
            if output_file:
                fig.write_html(output_file)
                
            return fig
            
        elif VISUALIZATION_LIBS_AVAILABLE:
            # Create static plot with matplotlib
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), sharex=True)
            
            # Set background colors based on theme
            if theme == 'dark':
                plt.style.use('dark_background')
            
            # Plot duration improvements
            ax1.plot(dates, cumulative_duration_improvements, 'g-', linewidth=2)
            ax1.set_title('Cumulative Duration Improvement')
            ax1.set_ylabel('Average Duration Reduction (ms)')
            ax1.grid(True, alpha=0.3)
            
            # Add linear trend line
            if len(dates) > 1 and PANDAS_AVAILABLE:
                try:
                    # Convert to pandas for trend analysis
                    import pandas as pd
                    import numpy as np
                    from scipy import stats
                    
                    # Convert timestamps to numeric values for linear regression
                    timestamps_numeric = mdates.date2num(dates)
                    slope, intercept, r_value, p_value, std_err = stats.linregress(
                        timestamps_numeric, cumulative_duration_improvements
                    )
                    
                    # Create trend line
                    trend_line = slope * timestamps_numeric + intercept
                    ax1.plot(dates, trend_line, 'r--', linewidth=1, 
                            label=f'Trend (r²={r_value**2:.2f})')
                    ax1.legend()
                except:
                    # Skip trend line if calculation fails
                    pass
            
            # Plot quality improvements
            ax2.plot(dates, cumulative_quality_improvements, 'b-', linewidth=2)
            ax2.set_title('Cumulative Quality Improvement')
            ax2.set_xlabel('Time')
            ax2.set_ylabel('Average Quality Improvement')
            ax2.grid(True, alpha=0.3)
            
            # Add linear trend line
            if len(dates) > 1 and PANDAS_AVAILABLE:
                try:
                    # Convert to pandas for trend analysis
                    import pandas as pd
                    import numpy as np
                    from scipy import stats
                    
                    # Convert timestamps to numeric values for linear regression
                    timestamps_numeric = mdates.date2num(dates)
                    slope, intercept, r_value, p_value, std_err = stats.linregress(
                        timestamps_numeric, cumulative_quality_improvements
                    )
                    
                    # Create trend line
                    trend_line = slope * timestamps_numeric + intercept
                    ax2.plot(dates, trend_line, 'r--', linewidth=1, 
                            label=f'Trend (r²={r_value**2:.2f})')
                    ax2.legend()
                except:
                    # Skip trend line if calculation fails
                    pass
            
            # Format x-axis
            fig.autofmt_xdate()
            
            plt.tight_layout()
            
            # Save if output file provided
            if output_file:
                plt.savefig(output_file, dpi=300, bbox_inches='tight')
                plt.close(fig)
            
            return fig
            
        else:
            logging.warning("Visualization libraries not available")
            return None
    
    def create_interactive_learning_dashboard(self, output_file: str, theme: str = 'light') -> Optional[str]:
        """
        Create an interactive HTML dashboard for all learning metrics.
        
        Args:
            output_file: Path to save the HTML dashboard
            theme: Visualization theme ('light' or 'dark')
            
        Returns:
            Path to the saved dashboard file or None if creation failed
        """
        if not INTERACTIVE_VISUALIZATION_AVAILABLE or not TEMPLATE_ENGINE_AVAILABLE:
            logging.warning("Interactive dashboard requires plotly and jinja2")
            return None
        
        # Create temp directory for visualization components
        import tempfile
        temp_dir = tempfile.mkdtemp(prefix="learning_dashboard_")
        
        try:
            # Generate individual visualizations
            cycles_file = os.path.join(temp_dir, "learning_cycles.html")
            params_file = os.path.join(temp_dir, "parameter_adaptations.html")
            strategy_file = os.path.join(temp_dir, "strategy_effectiveness.html")
            patterns_file = os.path.join(temp_dir, "query_patterns.html")
            performance_file = os.path.join(temp_dir, "learning_performance.html")
            
            # Generate visualizations with plotly
            self.visualize_learning_cycles(output_file=cycles_file, interactive=True, theme=theme)
            self.visualize_parameter_adaptations(output_file=params_file, interactive=True, theme=theme)
            self.visualize_strategy_effectiveness(output_file=strategy_file, interactive=True, theme=theme)
            self.visualize_query_patterns(output_file=patterns_file, interactive=True, theme=theme)
            self.visualize_learning_performance(output_file=performance_file, interactive=True, theme=theme)
            
            # Get summary metrics
            metrics = self.get_learning_metrics()
            
            # Create dashboard HTML
            dashboard_html = self._create_dashboard_html(
                metrics=metrics,
                visualizations=[
                    {"title": "Learning Cycles", "file": cycles_file},
                    {"title": "Parameter Adaptations", "file": params_file},
                    {"title": "Strategy Effectiveness", "file": strategy_file},
                    {"title": "Query Patterns", "file": patterns_file},
                    {"title": "Learning Performance", "file": performance_file}
                ],
                theme=theme
            )
            
            # Write dashboard HTML to output file
            with open(output_file, 'w') as f:
                f.write(dashboard_html)
            
            return output_file
            
        except Exception as e:
            logging.error(f"Error creating learning dashboard: {str(e)}")
            return None
            
        finally:
            # Clean up temp files
            import shutil
            shutil.rmtree(temp_dir)
    
    def _create_dashboard_html(self, metrics: Dict[str, Any], 
                             visualizations: List[Dict[str, str]], 
                             theme: str = 'light') -> str:
        """
        Create HTML for the learning dashboard.
        
        Args:
            metrics: Dictionary of learning metrics
            visualizations: List of visualization details
            theme: Dashboard theme ('light' or 'dark')
            
        Returns:
            HTML content for the dashboard
        """
        # Define dashboard template
        template_str = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>RAG Optimizer Learning Dashboard</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    margin: 0;
                    padding: 0;
                    background-color: {{ 'rgba(0,0,0,0.9)' if theme == 'dark' else '#f5f5f5' }};
                    color: {{ '#eee' if theme == 'dark' else '#333' }};
                }
                .container {
                    width: 95%;
                    margin: 0 auto;
                    padding: 20px 0;
                }
                header {
                    background-color: {{ '#333' if theme == 'dark' else '#fff' }};
                    padding: 20px;
                    box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                    margin-bottom: 20px;
                    border-radius: 5px;
                }
                h1, h2, h3 {
                    margin: 0;
                    color: {{ '#fff' if theme == 'dark' else '#333' }};
                }
                .metrics-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
                    gap: 15px;
                    margin-bottom: 30px;
                }
                .metric-card {
                    background-color: {{ '#333' if theme == 'dark' else '#fff' }};
                    border-radius: 5px;
                    box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                    padding: 20px;
                }
                .metric-title {
                    font-size: 14px;
                    font-weight: bold;
                    margin-bottom: 10px;
                    color: {{ '#ccc' if theme == 'dark' else '#666' }};
                }
                .metric-value {
                    font-size: 24px;
                    font-weight: bold;
                    color: {{ '#4CAF50' if theme == 'dark' else '#2196F3' }};
                }
                .visualization-section {
                    background-color: {{ '#333' if theme == 'dark' else '#fff' }};
                    border-radius: 5px;
                    box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                    margin-bottom: 20px;
                    padding: 20px;
                }
                .visualization-title {
                    font-size: 18px;
                    margin-bottom: 15px;
                    padding-bottom: 10px;
                    border-bottom: 1px solid {{ '#444' if theme == 'dark' else '#eee' }};
                }
                iframe {
                    border: none;
                    width: 100%;
                    height: 500px;
                }
                .footer {
                    text-align: center;
                    margin-top: 40px;
                    padding: 20px;
                    font-size: 12px;
                    color: {{ '#999' if theme == 'dark' else '#999' }};
                }
                .key-metric {
                    color: {{ '#8BC34A' if theme == 'dark' else '#4CAF50' }};
                }
                .warning-metric {
                    color: {{ '#FFC107' if theme == 'dark' else '#FF9800' }};
                }
                .danger-metric {
                    color: {{ '#F44336' if theme == 'dark' else '#F44336' }};
                }
            </style>
        </head>
        <body>
            <div class="container">
                <header>
                    <h1>RAG Optimizer Learning Dashboard</h1>
                    <p>Statistical learning metrics and performance visualization</p>
                </header>
                
                <section class="metrics-overview">
                    <h2>Learning Metrics Summary</h2>
                    <div class="metrics-grid">
                        <div class="metric-card">
                            <div class="metric-title">Learning Cycles</div>
                            <div class="metric-value">{{ metrics.total_learning_cycles }}</div>
                        </div>
                        <div class="metric-card">
                            <div class="metric-title">Success Rate</div>
                            <div class="metric-value {{ 'key-metric' if metrics.success_rate >= 0.9 else 'warning-metric' if metrics.success_rate >= 0.7 else 'danger-metric' }}">
                                {{ "%.1f"|format(metrics.success_rate * 100) }}%
                            </div>
                        </div>
                        <div class="metric-card">
                            <div class="metric-title">Analyzed Queries</div>
                            <div class="metric-value">{{ metrics.total_analyzed_queries }}</div>
                        </div>
                        <div class="metric-card">
                            <div class="metric-title">Optimized Queries</div>
                            <div class="metric-value">{{ metrics.total_optimized_queries }}</div>
                        </div>
                        <div class="metric-card">
                            <div class="metric-title">Optimization Rate</div>
                            <div class="metric-value {{ 'key-metric' if metrics.optimization_rate >= 0.8 else 'warning-metric' if metrics.optimization_rate >= 0.5 else 'danger-metric' }}">
                                {{ "%.1f"|format(metrics.optimization_rate * 100) }}%
                            </div>
                        </div>
                        <div class="metric-card">
                            <div class="metric-title">Learning Rate (cycles/hr)</div>
                            <div class="metric-value">{{ "%.2f"|format(metrics.learning_rate) }}</div>
                        </div>
                        <div class="metric-card">
                            <div class="metric-title">Avg Duration Improvement</div>
                            <div class="metric-value {{ 'key-metric' if metrics.avg_duration_improvement >= 100 else 'warning-metric' if metrics.avg_duration_improvement > 0 else 'danger-metric' }}">
                                {{ "%.0f"|format(metrics.avg_duration_improvement) }} ms
                            </div>
                        </div>
                        <div class="metric-card">
                            <div class="metric-title">Avg Quality Improvement</div>
                            <div class="metric-value {{ 'key-metric' if metrics.avg_quality_improvement >= 0.1 else 'warning-metric' if metrics.avg_quality_improvement > 0 else 'danger-metric' }}">
                                {{ "%.2f"|format(metrics.avg_quality_improvement) }}
                            </div>
                        </div>
                    </div>
                </section>
                
                {% for viz in visualizations %}
                <section class="visualization-section">
                    <h2 class="visualization-title">{{ viz.title }}</h2>
                    <iframe src="{{ viz.file }}" frameborder="0"></iframe>
                </section>
                {% endfor %}
                
                <div class="footer">
                    <p>Generated on {{ timestamp }}</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Create template and render HTML
        from jinja2 import Template
        template = Template(template_str)
        
        return template.render(
            metrics=metrics,
            visualizations=visualizations,
            theme=theme,
            timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )


class RAGQueryDashboard:
    """
    Comprehensive dashboard for RAG queries with integrated audit and learning metrics.
    
    This class provides a unified dashboard that combines RAG query metrics
    with audit metrics and statistical learning metrics to provide a complete picture 
    of system performance, optimization effectiveness, and security behavior.
    """
    
    def __init__(self, metrics_collector: QueryMetricsCollector, audit_metrics=None, 
                 learning_metrics=None, dashboard_dir=None, refresh_interval=60):
        """
        Initialize the dashboard with enhanced monitoring capabilities.
        
        Args:
            metrics_collector: QueryMetricsCollector with query metrics
            audit_metrics: Optional AuditMetricsAggregator instance
            learning_metrics: Optional OptimizerLearningMetricsCollector instance
            dashboard_dir: Directory to store dashboard files
            refresh_interval: Dashboard refresh interval in seconds for auto-refresh
        """
        self.metrics = metrics_collector  # Main reference as self.metrics for consistency
        self.query_metrics = metrics_collector  # Also keep as query_metrics for backward compatibility
        self.audit_metrics = audit_metrics
        self.learning_metrics = learning_metrics
        self.dashboard_dir = dashboard_dir
        self.refresh_interval = refresh_interval
        
        # Create dashboard directory if specified and doesn't exist
        if dashboard_dir:
            os.makedirs(dashboard_dir, exist_ok=True)
        
        # Initialize performance metrics visualizer for detailed performance analysis
        self.performance_visualizer = PerformanceMetricsVisualizer(metrics_collector)
        
        # Try to use enhanced visualizer if available
        try:
            from ipfs_datasets_py.enhanced_rag_visualization import EnhancedQueryAuditVisualizer
            self.visualizer = EnhancedQueryAuditVisualizer(metrics_collector)
            self.enhanced_vis_available = True
        except ImportError:
            self.visualizer = EnhancedQueryVisualizer(metrics_collector)
            self.enhanced_vis_available = False
    
    def generate_dashboard(self, 
                         output_file: str,
                         title: str = "RAG Query Analytics Dashboard",
                         include_audit_metrics: bool = True,
                         include_performance_metrics: bool = True) -> str:
        """
        Generate a combined dashboard with query and audit metrics.
        
        Args:
            output_file: Path to save the dashboard HTML
            title: Dashboard title
            include_audit_metrics: Whether to include audit metrics
            include_performance_metrics: Whether to include detailed performance metrics
            
        Returns:
            str: Path to the generated dashboard
        """
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
        
        # Generate charts
        chart_paths = {}
        
        # Create temporary directory for charts
        import tempfile
        temp_dir = tempfile.mkdtemp()
        
        try:
            # Generate query performance chart
            performance_chart = os.path.join(temp_dir, "performance.png")
            self.visualizer.plot_query_performance(output_file=performance_chart)
            chart_paths['performance'] = performance_chart
            
            # Generate performance timeline
            timeline_chart = os.path.join(temp_dir, "timeline.png")
            self.visualizer.visualize_query_performance_timeline(output_file=timeline_chart)
            chart_paths['timeline'] = timeline_chart
            
            # Generate query term frequency chart
            terms_chart = os.path.join(temp_dir, "terms.png")
            self.visualizer.plot_query_term_frequency(output_file=terms_chart)
            chart_paths['terms'] = terms_chart
            
            # Generate duration distribution chart
            duration_chart = os.path.join(temp_dir, "durations.png")
            self.visualizer.plot_query_duration_distribution(output_file=duration_chart)
            chart_paths['durations'] = duration_chart
            
            # Get anomalies if any
            anomalies = []
            for metrics in self.query_metrics.query_metrics.values():
                if 'anomaly_type' in metrics:
                    anomaly = {
                        'type': metrics.get('anomaly_type', 'unknown_anomaly'),
                        'severity': metrics.get('severity', 'low'),
                        'timestamp': datetime.datetime.fromtimestamp(metrics.get('end_time', time.time())).isoformat(),
                        'query_id': metrics.get('query_id', 'unknown')
                    }
                    
                    # Add specific information based on anomaly type
                    if metrics.get('anomaly_type') == 'performance_anomaly':
                        anomaly['value'] = metrics.get('duration', 0)
                        anomaly['average'] = metrics.get('avg_duration', 0)
                        anomaly['ratio'] = metrics.get('duration_ratio', 1.0)
                    elif metrics.get('anomaly_type') == 'empty_results_anomaly':
                        anomaly['query_text'] = metrics.get('query_params', {}).get('query_text', 'Unknown query')
                    elif metrics.get('anomaly_type') == 'relevance_anomaly':
                        anomaly['value'] = metrics.get('avg_score', 0)
                    
                    anomalies.append(anomaly)
                    
            # Generate dashboard HTML using the visualizer
            html = self.visualizer.generate_dashboard_html(
                title=title,
                include_optimization=True,
                include_patterns=True,
                anomalies=anomalies,
                audit_metrics=self.audit_metrics if include_audit_metrics else None,
                learning_metrics=self.learning_metrics if hasattr(self, 'learning_metrics') else None
            )
            
            # Write dashboard to file
            with open(output_file, 'w') as f:
                f.write(html)
                
            return output_file
            
        finally:
            # Clean up temporary directory
            import shutil
            shutil.rmtree(temp_dir)
    
    def generate_integrated_dashboard(self,
                                   output_file: str,
                                   audit_metrics_aggregator=None,
                                   learning_metrics_collector=None,
                                   title: str = "Integrated Query Performance & Security Dashboard",
                                   include_performance: bool = True,
                                   include_security: bool = True,
                                   include_security_correlation: bool = True,
                                   include_query_audit_timeline: bool = True,
                                   include_learning_metrics: bool = True,
                                   interactive: bool = True,
                                   theme: str = 'light') -> str:
        """
        Generate a comprehensive dashboard integrating RAG query metrics with audit security and learning metrics.
        
        This dashboard provides a unified view of performance, security, and learning aspects,
        enabling correlation analysis between performance issues, security events, and
        optimization learning statistics.
        
        Args:
            output_file: Path to save the dashboard HTML
            audit_metrics_aggregator: Optional metrics aggregator (uses self.audit_metrics if None)
            learning_metrics_collector: Optional learning metrics collector (uses self.learning_metrics if None)
            title: Dashboard title
            include_performance: Whether to include performance metrics
            include_security: Whether to include security metrics
            include_security_correlation: Whether to include security correlation visualization
            include_query_audit_timeline: Whether to include combined timeline
            include_learning_metrics: Whether to include optimizer learning metrics
            interactive: Whether to generate interactive visualizations
            theme: 'light' or 'dark' color theme
            
        Returns:
            str: Path to the generated dashboard
        """
        # Use provided metrics or fall back to instance metrics
        audit_metrics = audit_metrics_aggregator or self.audit_metrics
        learning_metrics = learning_metrics_collector or getattr(self, 'learning_metrics', None)
        
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
        
        # Create a temporary directory for static charts
        temp_dir = tempfile.mkdtemp()
        
        try:
            # Create HTML template
            if not TEMPLATE_ENGINE_AVAILABLE:
                logging.warning("Template engine not available. Using basic HTML template.")
                with open(output_file, 'w') as f:
                    f.write(f"<html><body><h1>{title}</h1><p>Template engine not available.</p></body></html>")
                return output_file
            
            # Create dashboard template
            dashboard_template = """
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>{{ title }}</title>
                <style>
                    :root {
                        {% if theme == 'dark' %}
                        --bg-color: #2E3440;
                        --card-bg: #3B4252;
                        --text-color: #ECEFF4;
                        --border-color: #4C566A;
                        --highlight-color: #88C0D0;
                        --accent-color: #5E81AC;
                        --error-color: #BF616A;
                        --warning-color: #EBCB8B;
                        --success-color: #A3BE8C;
                        {% else %}
                        --bg-color: #F8F9FA;
                        --card-bg: #FFFFFF;
                        --text-color: #212529;
                        --border-color: #DEE2E6;
                        --highlight-color: #0D6EFD;
                        --accent-color: #6610F2;
                        --error-color: #DC3545;
                        --warning-color: #FFC107;
                        --success-color: #198754;
                        {% endif %}
                    }
                    
                    body {
                        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                        margin: 0;
                        padding: 0;
                        background-color: var(--bg-color);
                        color: var(--text-color);
                    }
                    
                    .dashboard-container {
                        max-width: 1200px;
                        margin: 0 auto;
                        padding: 2rem;
                    }
                    
                    .dashboard-header {
                        margin-bottom: 2rem;
                        border-bottom: 1px solid var(--border-color);
                        padding-bottom: 1rem;
                    }
                    
                    .dashboard-header h1 {
                        margin: 0;
                        font-size: 2rem;
                        color: var(--text-color);
                    }
                    
                    .dashboard-header p {
                        margin: 0.5rem 0 0;
                        font-size: 1rem;
                        color: var(--text-color);
                        opacity: 0.8;
                    }
                    
                    .dashboard-section {
                        margin-bottom: 2rem;
                        padding: 1.5rem;
                        background-color: var(--card-bg);
                        border-radius: 0.5rem;
                        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                    }
                    
                    .dashboard-section h2 {
                        margin-top: 0;
                        margin-bottom: 1rem;
                        font-size: 1.5rem;
                        color: var(--text-color);
                    }
                    
                    .metrics-grid {
                        display: grid;
                        grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
                        gap: 1rem;
                        margin-bottom: 1.5rem;
                    }
                    
                    .metric-card {
                        background-color: var(--card-bg);
                        padding: 1.25rem;
                        border-radius: 0.375rem;
                        border-left: 4px solid var(--highlight-color);
                        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
                    }
                    
                    .metric-card.error {
                        border-left-color: var(--error-color);
                    }
                    
                    .metric-card.warning {
                        border-left-color: var(--warning-color);
                    }
                    
                    .metric-card.success {
                        border-left-color: var(--success-color);
                    }
                    
                    .metric-title {
                        font-size: 0.875rem;
                        font-weight: 600;
                        margin: 0 0 0.5rem 0;
                        color: var(--text-color);
                        opacity: 0.8;
                    }
                    
                    .metric-value {
                        font-size: 1.5rem;
                        font-weight: 700;
                        margin: 0;
                        color: var(--text-color);
                    }
                    
                    .metric-trend {
                        display: flex;
                        align-items: center;
                        font-size: 0.75rem;
                        margin-top: 0.5rem;
                    }
                    
                    .trend-up {
                        color: var(--success-color);
                    }
                    
                    .trend-down {
                        color: var(--error-color);
                    }
                    
                    .visualization-container {
                        margin-top: 1.5rem;
                        width: 100%;
                        border: 1px solid var(--border-color);
                        border-radius: 0.375rem;
                        overflow: hidden;
                    }
                    
                    .visualization-container iframe {
                        width: 100%;
                        height: 600px;
                        border: none;
                    }
                    
                    .visualization-container img {
                        width: 100%;
                        height: auto;
                        display: block;
                    }
                    
                    .visualization-section {
                        margin-top: 2rem;
                        border-top: 1px solid var(--border-color);
                        padding-top: 1.5rem;
                    }
                    
                    .visualization-section h3 {
                        margin-top: 0;
                        margin-bottom: 1rem;
                        font-size: 1.3rem;
                        color: var(--text-color);
                    }
                    
                    /* Tabs for learning metrics */
                    .visualization-tabs {
                        width: 100%;
                        margin-top: 20px;
                    }
                    
                    .tab-buttons {
                        display: flex;
                        overflow-x: auto;
                        border-bottom: 1px solid var(--border-color);
                        margin-bottom: 15px;
                    }
                    
                    .tab-button {
                        background-color: transparent;
                        border: none;
                        padding: 10px 20px;
                        font-size: 14px;
                        cursor: pointer;
                        transition: background-color 0.3s;
                        border-bottom: 2px solid transparent;
                        color: var(--text-color);
                    }
                    
                    .tab-button:hover {
                        background-color: rgba(0,0,0,0.05);
                    }
                    
                    .tab-button.active {
                        border-bottom: 2px solid var(--primary-color);
                        color: var(--primary-color);
                        font-weight: bold;
                    }
                    
                    .tab-content {
                        display: none;
                        padding: 15px 0;
                    }
                    
                    .tab-content.active {
                        display: block;
                    }
                    
                    .visualization-grid {
                        display: grid;
                        grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
                        gap: 20px;
                        margin-top: 20px;
                    }
                    
                    .visualization-description {
                        margin-top: 1rem;
                        padding: 0.8rem;
                        background-color: rgba(0,0,0,0.03);
                        border-left: 3px solid var(--highlight-color);
                        font-size: 0.9rem;
                        color: var(--text-color);
                    }
                    
                    .tabs {
                        display: flex;
                        border-bottom: 1px solid var(--border-color);
                        margin-bottom: 1.5rem;
                    }
                    
                    .tab {
                        padding: 0.75rem 1rem;
                        cursor: pointer;
                        border-bottom: 2px solid transparent;
                        font-weight: 500;
                    }
                    
                    .tab.active {
                        border-bottom-color: var(--highlight-color);
                        color: var(--highlight-color);
                    }
                    
                    .tab-content {
                        display: none;
                    }
                    
                    .tab-content.active {
                        display: block;
                    }
                    
                    .anomaly-list {
                        margin-top: 1.5rem;
                    }
                    
                    .anomaly-item {
                        padding: 1rem;
                        margin-bottom: 0.75rem;
                        border-radius: 0.375rem;
                        border-left: 4px solid var(--error-color);
                        background-color: {{  'rgba(191, 97, 106, 0.1)' if theme == 'dark' else 'rgba(220, 53, 69, 0.1)' }};
                    }
                    
                    .anomaly-item-header {
                        display: flex;
                        justify-content: space-between;
                        margin-bottom: 0.5rem;
                    }
                    
                    .anomaly-type {
                        font-weight: 600;
                    }
                    
                    .anomaly-timestamp {
                        font-size: 0.75rem;
                        opacity: 0.8;
                    }
                    
                    .anomaly-details {
                        font-size: 0.875rem;
                    }
                    
                    .footer {
                        margin-top: 2rem;
                        padding-top: 1rem;
                        border-top: 1px solid var(--border-color);
                        text-align: center;
                        font-size: 0.875rem;
                        opacity: 0.7;
                    }
                </style>
                <script>
                    document.addEventListener('DOMContentLoaded', function() {
                        // Tab functionality
                        const tabs = document.querySelectorAll('.tab');
                        const tabContents = document.querySelectorAll('.tab-content');
                        
                        tabs.forEach(tab => {
                            tab.addEventListener('click', () => {
                                // Remove active class from all tabs and contents
                                tabs.forEach(t => t.classList.remove('active'));
                                tabContents.forEach(c => c.classList.remove('active'));
                                
                                // Add active class to clicked tab and corresponding content
                                tab.classList.add('active');
                                const contentId = tab.getAttribute('data-tab');
                                document.getElementById(contentId).classList.add('active');
                            });
                        });
                    });
                </script>
            </head>
            <body>
                <div class="dashboard-container">
                    <div class="dashboard-header">
                        <h1>{{ title }}</h1>
                        <p>Generated at {{ current_time }}</p>
                    </div>
                    
                    {% if include_performance %}
                    <div class="dashboard-section">
                        <h2>Performance Metrics</h2>
                        <div class="metrics-grid">
                            <div class="metric-card {{ 'success' if performance.success_rate > 0.95 else 'warning' if performance.success_rate > 0.8 else 'error' }}">
                                <div class="metric-title">Success Rate</div>
                                <div class="metric-value">{{ (performance.success_rate * 100)|round(1) }}%</div>
                            </div>
                            
                            <div class="metric-card">
                                <div class="metric-title">Average Duration</div>
                                <div class="metric-value">{{ performance.avg_duration|round(3) }}s</div>
                            </div>
                            
                            <div class="metric-card">
                                <div class="metric-title">Total Queries</div>
                                <div class="metric-value">{{ performance.total_queries }}</div>
                            </div>
                            
                            <div class="metric-card {{ 'error' if performance.error_rate > 0.1 else 'warning' if performance.error_rate > 0.05 else 'success' }}">
                                <div class="metric-title">Error Rate</div>
                                <div class="metric-value">{{ (performance.error_rate * 100)|round(1) }}%</div>
                            </div>
                        </div>
                        
                        <div class="tabs">
                            <div class="tab active" data-tab="tab-performance-timeline">Timeline</div>
                            <div class="tab" data-tab="tab-performance-distribution">Duration Distribution</div>
                            <div class="tab" data-tab="tab-query-patterns">Query Patterns</div>
                        </div>
                        
                        <div id="tab-performance-timeline" class="tab-content active">
                            <div class="visualization-container">
                                {% if visualizations.timeline_html %}
                                <iframe srcdoc="{{ visualizations.timeline_html }}" title="Performance Timeline"></iframe>
                                {% elif visualizations.timeline_img %}
                                <img src="data:image/png;base64,{{ visualizations.timeline_img }}" alt="Performance Timeline">
                                {% else %}
                                <p>No timeline visualization available.</p>
                                {% endif %}
                            </div>
                        </div>
                        
                        <div id="tab-performance-distribution" class="tab-content">
                            <div class="visualization-container">
                                {% if visualizations.duration_html %}
                                <iframe srcdoc="{{ visualizations.duration_html }}" title="Duration Distribution"></iframe>
                                {% elif visualizations.duration_img %}
                                <img src="data:image/png;base64,{{ visualizations.duration_img }}" alt="Duration Distribution">
                                {% else %}
                                <p>No duration distribution visualization available.</p>
                                {% endif %}
                            </div>
                        </div>
                        
                        <div id="tab-query-patterns" class="tab-content">
                            <div class="visualization-container">
                                {% if visualizations.terms_html %}
                                <iframe srcdoc="{{ visualizations.terms_html }}" title="Query Patterns"></iframe>
                                {% elif visualizations.terms_img %}
                                <img src="data:image/png;base64,{{ visualizations.terms_img }}" alt="Query Patterns">
                                {% else %}
                                <p>No query pattern visualization available.</p>
                                {% endif %}
                            </div>
                        </div>
                    </div>
                    {% endif %}
                    
                    {% if include_query_audit_timeline and visualizations.query_audit_html %}
                    <div class="dashboard-section">
                        <h2>Query-Audit Correlation Timeline</h2>
                        <div class="visualization-container">
                            <iframe srcdoc="{{ visualizations.query_audit_html }}" title="Query-Audit Timeline"></iframe>
                        </div>
                    </div>
                    {% endif %}
                    
                    {% if include_security and audit_metrics %}
                    <div class="dashboard-section">
                        <h2>Security Metrics</h2>
                        
                        <div class="metrics-grid">
                            {% for level, count in audit_metrics.totals.by_level.items() %}
                            <div class="metric-card {{ 'error' if level in ['CRITICAL', 'ERROR'] else 'warning' if level == 'WARNING' else 'success' }}">
                                <div class="metric-title">{{ level }} Events</div>
                                <div class="metric-value">{{ count }}</div>
                            </div>
                            {% endfor %}
                        </div>
                        
                        {% if include_security_correlation %}
                        <div class="visualization-section">
                            <h3>Security Event Correlation with Query Performance</h3>
                            <div class="visualization-container">
                                {% if visualizations.security_correlation_html %}
                                <iframe srcdoc="{{ visualizations.security_correlation_html }}" title="Security Correlation" style="width:100%; height:600px; border:none;"></iframe>
                                {% elif visualizations.security_correlation_img %}
                                <img src="data:image/png;base64,{{ visualizations.security_correlation_img }}" alt="Security Correlation Visualization" style="max-width:100%;">
                                {% else %}
                                <p>No security correlation visualization available.</p>
                                {% endif %}
                            </div>
                            <div class="visualization-description">
                                <p>This visualization shows the correlation between query performance and security events, highlighting potential relationships between performance anomalies and security incidents.</p>
                            </div>
                        </div>
                        {% endif %}
                        
                        <div class="tabs">
                            <div class="tab active" data-tab="tab-security-trends">Security Trends</div>
                            <div class="tab" data-tab="tab-anomalies">Anomalies</div>
                        </div>
                        
                        <div id="tab-security-trends" class="tab-content active">
                            <div class="visualization-container">
                                {% if visualizations.security_trends_html %}
                                <iframe srcdoc="{{ visualizations.security_trends_html }}" title="Security Trends"></iframe>
                                {% else %}
                                <p>No security trends visualization available.</p>
                                {% endif %}
                            </div>
                        </div>
                        
                        <div id="tab-anomalies" class="tab-content">
                            <div class="anomaly-list">
                                {% if anomalies %}
                                {% for anomaly in anomalies %}
                                <div class="anomaly-item">
                                    <div class="anomaly-item-header">
                                        <span class="anomaly-type">{{ anomaly.type }}</span>
                                        <span class="anomaly-timestamp">{{ anomaly.timestamp }}</span>
                                    </div>
                                    <div class="anomaly-details">
                                        {% if anomaly.type == 'performance_anomaly' %}
                                        Query took {{ anomaly.value|round(2) }}s, which is {{ anomaly.ratio|round(1) }}x the average time.
                                        {% elif anomaly.type == 'empty_results_anomaly' %}
                                        Query returned zero results: "{{ anomaly.query_text }}"
                                        {% elif anomaly.type == 'relevance_anomaly' %}
                                        Average result score was {{ anomaly.value|round(2) }}, which is below threshold.
                                        {% else %}
                                        Anomaly details not available.
                                        {% endif %}
                                    </div>
                                </div>
                                {% endfor %}
                                {% else %}
                                <p>No anomalies detected.</p>
                                {% endif %}
                            </div>
                        </div>
                    </div>
                    {% endif %}
                    
                    {% if include_learning_metrics and learning_metrics %}
                    <div class="dashboard-section">
                        <h2>Optimizer Learning Metrics</h2>
                        
                        <div class="metrics-grid">
                            <div class="metric-card">
                                <div class="metric-title">Learning Cycles</div>
                                <div class="metric-value">{{ learning_metrics.get_learning_metrics().total_learning_cycles }}</div>
                            </div>
                            
                            <div class="metric-card">
                                <div class="metric-title">Success Rate</div>
                                <div class="metric-value {{ 'success-value' if learning_metrics.get_learning_metrics().success_rate >= 0.9 else 'warning-value' if learning_metrics.get_learning_metrics().success_rate >= 0.7 else 'error-value' }}">
                                    {{ "%.1f"|format(learning_metrics.get_learning_metrics().success_rate * 100) }}%
                                </div>
                            </div>
                            
                            <div class="metric-card">
                                <div class="metric-title">Analyzed Queries</div>
                                <div class="metric-value">{{ learning_metrics.get_learning_metrics().total_analyzed_queries }}</div>
                            </div>
                            
                            <div class="metric-card">
                                <div class="metric-title">Optimized Queries</div>
                                <div class="metric-value">{{ learning_metrics.get_learning_metrics().total_optimized_queries }}</div>
                            </div>
                            
                            <div class="metric-card">
                                <div class="metric-title">Avg Duration Improvement</div>
                                <div class="metric-value">{{ "%.0f"|format(learning_metrics.get_learning_metrics().avg_duration_improvement) }} ms</div>
                            </div>
                            
                            <div class="metric-card">
                                <div class="metric-title">Tracked Parameters</div>
                                <div class="metric-value">{{ learning_metrics.get_learning_metrics().tracked_parameters }}</div>
                            </div>
                        </div>
                        
                        <div class="visualization-container">
                            {% if interactive %}
                                <div class="visualization-tabs">
                                    <div class="tab-buttons">
                                        <button class="tab-button active" onclick="openTab(event, 'cycles-tab')">Learning Cycles</button>
                                        <button class="tab-button" onclick="openTab(event, 'params-tab')">Parameter Adaptations</button>
                                        <button class="tab-button" onclick="openTab(event, 'strategies-tab')">Strategy Effectiveness</button>
                                        <button class="tab-button" onclick="openTab(event, 'performance-tab')">Learning Performance</button>
                                    </div>
                                    
                                    <div id="cycles-tab" class="tab-content active">
                                        {% if visualizations.learning_cycles_html %}
                                        <iframe srcdoc="{{ visualizations.learning_cycles_html }}" title="Learning Cycles" style="width:100%; height:500px; border:none;"></iframe>
                                        {% endif %}
                                    </div>
                                    
                                    <div id="params-tab" class="tab-content">
                                        {% if visualizations.learning_params_html %}
                                        <iframe srcdoc="{{ visualizations.learning_params_html }}" title="Parameter Adaptations" style="width:100%; height:500px; border:none;"></iframe>
                                        {% endif %}
                                    </div>
                                    
                                    <div id="strategies-tab" class="tab-content">
                                        {% if visualizations.learning_strategies_html %}
                                        <iframe srcdoc="{{ visualizations.learning_strategies_html }}" title="Strategy Effectiveness" style="width:100%; height:500px; border:none;"></iframe>
                                        {% endif %}
                                    </div>
                                    
                                    <div id="performance-tab" class="tab-content">
                                        {% if visualizations.learning_performance_html %}
                                        <iframe srcdoc="{{ visualizations.learning_performance_html }}" title="Learning Performance" style="width:100%; height:500px; border:none;"></iframe>
                                        {% endif %}
                                    </div>
                                </div>
                                
                                <script>
                                function openTab(evt, tabName) {
                                    var i, tabcontent, tabbuttons;
                                    tabcontent = document.getElementsByClassName("tab-content");
                                    for (i = 0; i < tabcontent.length; i++) {
                                        tabcontent[i].classList.remove("active");
                                    }
                                    tabbuttons = document.getElementsByClassName("tab-button");
                                    for (i = 0; i < tabbuttons.length; i++) {
                                        tabbuttons[i].classList.remove("active");
                                    }
                                    document.getElementById(tabName).classList.add("active");
                                    evt.currentTarget.classList.add("active");
                                }
                                </script>
                                
                            {% else %}
                                <div class="visualization-grid">
                                    {% if visualizations.learning_cycles_img %}
                                    <div class="visualization-section">
                                        <h3>Learning Cycles</h3>
                                        <img src="data:image/png;base64,{{ visualizations.learning_cycles_img }}" alt="Learning Cycles" style="max-width:100%;">
                                    </div>
                                    {% endif %}
                                    
                                    {% if visualizations.learning_params_img %}
                                <div class="visualization-section">
                                    <h3>Parameter Adaptations</h3>
                                    <img src="data:image/png;base64,{{ visualizations.learning_params_img }}" alt="Parameter Adaptations" style="max-width:100%;">
                                </div>
                                {% endif %}
                                
                                {% if visualizations.learning_strategies_img %}
                                <div class="visualization-section">
                                    <h3>Strategy Effectiveness</h3>
                                    <img src="data:image/png;base64,{{ visualizations.learning_strategies_img }}" alt="Strategy Effectiveness" style="max-width:100%;">
                                </div>
                                {% endif %}
                                
                                {% if visualizations.learning_performance_img %}
                                <div class="visualization-section">
                                    <h3>Learning Performance</h3>
                                    <img src="data:image/png;base64,{{ visualizations.learning_performance_img }}" alt="Learning Performance" style="max-width:100%;">
                                </div>
                                {% endif %}
                                
                            {% endif %}
                        </div>
                        
                        <div class="visualization-description">
                            <p>This section shows metrics related to the statistical learning process of the RAG query optimizer, including learning cycles, parameter adaptations over time, and strategy effectiveness.</p>
                        </div>
                    </div>
                    {% endif %}
                    
                    <div class="footer">
                        <p>Generated by RAGQueryDashboard | IPFS Datasets Python</p>
                    </div>
                </div>
            </body>
            </html>
            """
            
            # Collect performance metrics
            performance = self.metrics.get_performance_metrics()
            
            # Get anomalies
            anomalies = []
            for query_id, metrics in self.metrics.query_metrics.items():
                if 'status' == 'anomaly' or 'anomaly_type' in metrics:
                    anomaly = {
                        'type': metrics.get('anomaly_type', 'unknown_anomaly'),
                        'severity': metrics.get('severity', 'low'),
                        'timestamp': datetime.datetime.fromtimestamp(metrics.get('end_time', time.time())).isoformat(),
                        'query_id': query_id
                    }
                    
                    # Add specific information based on anomaly type
                    if metrics.get('anomaly_type') == 'performance_anomaly':
                        anomaly['value'] = metrics.get('duration', 0)
                        anomaly['average'] = metrics.get('avg_duration', 0)
                        anomaly['ratio'] = metrics.get('duration_ratio', 1.0)
                    elif metrics.get('anomaly_type') == 'empty_results_anomaly':
                        anomaly['query_text'] = metrics.get('query_params', {}).get('query_text', 'Unknown query')
                    elif metrics.get('anomaly_type') == 'relevance_anomaly':
                        anomaly['value'] = metrics.get('avg_score', 0)
                    
                    anomalies.append(anomaly)
            
            # Generate visualizations
            visualizations = {}
            
            # Create static visualizations
            if include_performance and not interactive:
                # Generate performance timeline image
                timeline_path = os.path.join(temp_dir, "timeline.png")
                self.visualizer.visualize_query_performance_timeline(output_file=timeline_path)
                if os.path.exists(timeline_path):
                    with open(timeline_path, 'rb') as f:
                        import base64
                        visualizations['timeline_img'] = base64.b64encode(f.read()).decode('utf-8')
                
                # Generate duration distribution image
                duration_path = os.path.join(temp_dir, "durations.png")
                self.visualizer.plot_query_duration_distribution(output_file=duration_path)
                if os.path.exists(duration_path):
                    with open(duration_path, 'rb') as f:
                        import base64
                        visualizations['duration_img'] = base64.b64encode(f.read()).decode('utf-8')
                        
            # Generate security correlation visualization if requested and audit metrics available
            if include_security_correlation and audit_metrics:
                if interactive and INTERACTIVE_VISUALIZATION_AVAILABLE:
                    # Create interactive security correlation visualization
                    security_correlation_path = os.path.join(temp_dir, "security_correlation.html")
                    fig = self.visualizer.visualize_query_performance_with_security_events(
                        audit_metrics_aggregator=audit_metrics,
                        hours_back=24,
                        interval_minutes=15,
                        min_severity="WARNING",
                        interactive=True,
                        output_file=security_correlation_path,
                        show_plot=False
                    )
                    
                    if os.path.exists(security_correlation_path):
                        with open(security_correlation_path, 'r') as f:
                            visualizations['security_correlation_html'] = f.read()
                else:
                    # Create static security correlation visualization
                    security_correlation_path = os.path.join(temp_dir, "security_correlation.png")
                    self.visualizer.visualize_query_performance_with_security_events(
                        audit_metrics_aggregator=audit_metrics,
                        hours_back=24,
                        interval_minutes=15,
                        min_severity="WARNING",
                        interactive=False,
                        output_file=security_correlation_path,
                        show_plot=False
                    )
            
            # Generate learning metrics visualizations if requested and learning metrics available
            if include_learning_metrics and learning_metrics:
                if interactive and INTERACTIVE_VISUALIZATION_AVAILABLE:
                    # Create interactive learning metrics visualizations
                    try:
                        learning_cycles_path = os.path.join(temp_dir, "learning_cycles.html")
                        learning_params_path = os.path.join(temp_dir, "parameter_adaptations.html")
                        learning_strategies_path = os.path.join(temp_dir, "strategy_effectiveness.html")
                        learning_performance_path = os.path.join(temp_dir, "learning_performance.html")
                        
                        # Generate each visualization
                        cycles_fig = learning_metrics.visualize_learning_cycles(
                            output_file=learning_cycles_path,
                            interactive=True,
                            theme=theme
                        )
                        
                        params_fig = learning_metrics.visualize_parameter_adaptations(
                            output_file=learning_params_path,
                            interactive=True,
                            theme=theme
                        )
                        
                        strategies_fig = learning_metrics.visualize_strategy_effectiveness(
                            output_file=learning_strategies_path,
                            interactive=True,
                            theme=theme
                        )
                        
                        performance_fig = learning_metrics.visualize_learning_performance(
                            output_file=learning_performance_path,
                            interactive=True,
                            theme=theme
                        )
                        
                        # Add to visualizations
                        if os.path.exists(learning_cycles_path):
                            with open(learning_cycles_path, 'r') as f:
                                visualizations['learning_cycles_html'] = f.read()
                        
                        if os.path.exists(learning_params_path):
                            with open(learning_params_path, 'r') as f:
                                visualizations['learning_params_html'] = f.read()
                                
                        if os.path.exists(learning_strategies_path):
                            with open(learning_strategies_path, 'r') as f:
                                visualizations['learning_strategies_html'] = f.read()
                                
                        if os.path.exists(learning_performance_path):
                            with open(learning_performance_path, 'r') as f:
                                visualizations['learning_performance_html'] = f.read()
                        
                    except Exception as e:
                        logging.error(f"Error generating learning visualizations: {e}")
                
                else:
                    # Create static learning metrics visualizations
                    try:
                        learning_cycles_path = os.path.join(temp_dir, "learning_cycles.png")
                        learning_params_path = os.path.join(temp_dir, "parameter_adaptations.png")
                        learning_strategies_path = os.path.join(temp_dir, "strategy_effectiveness.png")
                        learning_performance_path = os.path.join(temp_dir, "learning_performance.png")
                        
                        # Generate each visualization
                        learning_metrics.visualize_learning_cycles(
                            output_file=learning_cycles_path,
                            interactive=False,
                            theme=theme
                        )
                        
                        learning_metrics.visualize_parameter_adaptations(
                            output_file=learning_params_path,
                            interactive=False,
                            theme=theme
                        )
                        
                        learning_metrics.visualize_strategy_effectiveness(
                            output_file=learning_strategies_path,
                            interactive=False,
                            theme=theme
                        )
                        
                        learning_metrics.visualize_learning_performance(
                            output_file=learning_performance_path,
                            interactive=False,
                            theme=theme
                        )
                        
                        # Encode images to base64 for embedding
                        visualizations['learning_cycles_img'] = self._encode_image(learning_cycles_path)
                        visualizations['learning_params_img'] = self._encode_image(learning_params_path)
                        visualizations['learning_strategies_img'] = self._encode_image(learning_strategies_path)
                        visualizations['learning_performance_img'] = self._encode_image(learning_performance_path)
                        
                    except Exception as e:
                        logging.error(f"Error generating learning visualizations: {e}")
                    
                    strategy_effectiveness_path = os.path.join(temp_dir, "strategy_effectiveness.png")
                    learning_metrics.visualize_strategy_effectiveness(
                        output_file=strategy_effectiveness_path,
                        show_plot=False
                    )
                    
                    # Add learning metrics visualizations to the visualization dictionary
                    if os.path.exists(learning_cycles_path):
                        with open(learning_cycles_path, 'rb') as f:
                            import base64
                            visualizations['learning_cycles_img'] = base64.b64encode(f.read()).decode('utf-8')
                    
                    if os.path.exists(param_adaptations_path):
                        with open(param_adaptations_path, 'rb') as f:
                            import base64
                            visualizations['parameter_adaptations_img'] = base64.b64encode(f.read()).decode('utf-8')
                    
                    if os.path.exists(strategy_effectiveness_path):
                        with open(strategy_effectiveness_path, 'rb') as f:
                            import base64
                            visualizations['strategy_effectiveness_img'] = base64.b64encode(f.read()).decode('utf-8')
                            
                    # Also add security correlation if it exists
                    if os.path.exists(security_correlation_path):
                        with open(security_correlation_path, 'rb') as f:
                            import base64
                            visualizations['security_correlation_img'] = base64.b64encode(f.read()).decode('utf-8')
                
                # Generate terms chart
                terms_path = os.path.join(temp_dir, "terms.png")
                self.visualizer.plot_query_term_frequency(output_file=terms_path)
                if os.path.exists(terms_path):
                    with open(terms_path, 'rb') as f:
                        import base64
                        visualizations['terms_img'] = base64.b64encode(f.read()).decode('utf-8')
            
            # Create interactive visualizations if requested
            if INTERACTIVE_VISUALIZATION_AVAILABLE and interactive:
                # Check if we're using the enhanced visualizer
                if hasattr(self.visualizer, '_create_interactive_query_audit_timeline'):
                    # Generate interactive performance timeline
                    try:
                        timeline_fig = self.visualizer.visualize_query_performance_timeline(
                            output_file=None,
                            interactive=True,
                            show_plot=False
                        )
                        if timeline_fig:
                            visualizations['timeline_html'] = timeline_fig.to_html(
                                full_html=False,
                                include_plotlyjs='cdn'
                            )
                    except Exception as e:
                        logging.error(f"Error creating interactive performance timeline: {str(e)}")
                    
                    # Generate interactive query-audit timeline if requested
                    if include_query_audit_timeline and audit_metrics:
                        try:
                            query_audit_fig = self.visualizer.visualize_query_audit_timeline(
                                audit_metrics_aggregator=audit_metrics,
                                interactive=True,
                                theme=theme,
                                show_plot=False
                            )
                            if query_audit_fig:
                                visualizations['query_audit_html'] = query_audit_fig.to_html(
                                    full_html=False,
                                    include_plotlyjs='cdn'
                                )
                        except Exception as e:
                            logging.error(f"Error creating interactive query-audit timeline: {str(e)}")
                    
                    # Generate security trends visualization if requested
                    if include_security and audit_metrics:
                        try:
                            security_fig = self.generate_interactive_audit_trends(
                                output_file=None,
                                audit_metrics_aggregator=audit_metrics,
                                theme=theme,
                                show_plot=False
                            )
                            if security_fig:
                                visualizations['security_trends_html'] = security_fig.to_html(
                                    full_html=False,
                                    include_plotlyjs='cdn'
                                )
                        except Exception as e:
                            logging.error(f"Error creating interactive security trends: {str(e)}")
            
            # Render template
            template = Template(dashboard_template)
            html = template.render(
                title=title,
                current_time=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                performance=performance,
                theme=theme,
                visualizations=visualizations,
                include_performance=include_performance,
                include_security=include_security,
                include_query_audit_timeline=include_query_audit_timeline,
                include_learning_metrics=include_learning_metrics,
                anomalies=anomalies,
                audit_metrics=audit_metrics.metrics if audit_metrics else None,
                learning_metrics=learning_metrics
            )
            
            # Write the HTML to file
            with open(output_file, 'w') as f:
                f.write(html)
            
            return output_file
            
        except Exception as e:
            logging.error(f"Error generating integrated dashboard: {str(e)}")
            import traceback
            logging.error(traceback.format_exc())
            
            # Create a simple error page
            with open(output_file, 'w') as f:
                f.write(f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Dashboard Error</title>
                </head>
                <body>
                    <h1>Error Generating Dashboard</h1>
                    <p>{str(e)}</p>
                    <pre>{traceback.format_exc()}</pre>
                </body>
                </html>
                """)
            
            return output_file
            
        finally:
            # Clean up temporary directory
            shutil.rmtree(temp_dir)
    
    def generate_performance_dashboard(self, output_file: str) -> Optional[str]:
        """
        Generate a comprehensive performance metrics dashboard.
        
        This dashboard focuses on detailed performance analysis of RAG queries,
        including processing time breakdowns, latency distributions, throughput
        analysis, and complexity correlations.
        
        Args:
            output_file: Path to save the dashboard HTML
            
        Returns:
            str: Path to the generated dashboard or None if failure
        """
        try:
            # Create the interactive performance dashboard
            if INTERACTIVE_VISUALIZATION_AVAILABLE:
                # Use the interactive dashboard
                return self.performance_visualizer.create_interactive_performance_dashboard(output_file)
            else:
                # Create a directory for static images if interactive dashboard not available
                dashboard_dir = os.path.dirname(os.path.abspath(output_file))
                os.makedirs(dashboard_dir, exist_ok=True)
                
                # Generate individual visualizations
                processing_chart = os.path.join(dashboard_dir, "processing_breakdown.png")
                self.performance_visualizer.visualize_processing_time_breakdown(output_file=processing_chart)
                
                latency_chart = os.path.join(dashboard_dir, "latency_distribution.png")
                self.performance_visualizer.visualize_latency_distribution(output_file=latency_chart)
                
                throughput_chart = os.path.join(dashboard_dir, "throughput.png")
                self.performance_visualizer.visualize_throughput_over_time(output_file=throughput_chart)
                
                complexity_chart = os.path.join(dashboard_dir, "complexity.png")
                self.performance_visualizer.visualize_performance_by_query_complexity(output_file=complexity_chart)
                
                # Create a simple HTML dashboard with the static images
                html_content = self._create_static_performance_dashboard(
                    title="RAG Query Performance Analysis",
                    processing_chart=processing_chart,
                    latency_chart=latency_chart,
                    throughput_chart=throughput_chart,
                    complexity_chart=complexity_chart
                )
                
                # Save the HTML
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                
                return output_file
                
        except Exception as e:
            logging.error(f"Error generating performance dashboard: {str(e)}")
            import traceback
            logging.error(traceback.format_exc())
            return None
            
    def _create_static_performance_dashboard(self, title: str, processing_chart: str, 
                                         latency_chart: str, throughput_chart: str,
                                         complexity_chart: str) -> str:
        """
        Create a static HTML dashboard from image files.
        
        Args:
            title: Dashboard title
            processing_chart: Path to processing breakdown chart
            latency_chart: Path to latency distribution chart
            throughput_chart: Path to throughput chart
            complexity_chart: Path to complexity chart
            
        Returns:
            str: HTML content for the dashboard
        """
        # Method body will be restored by the next edit
        
    def visualize_learning_metrics(self, output_file=None, interactive=True, **kwargs):
        """
        Visualize statistical learning metrics from the optimizer.
        
        Creates a comprehensive visualization of the learning process metrics,
        including cycle performance, parameter adaptations, and circuit breaker status.
        
        Args:
            output_file: File to save visualization to
            interactive: Whether to create interactive visualization
            **kwargs: Additional arguments for the visualization
            
        Returns:
            Figure or path to saved file
        """
        # Check if we have learning metrics
        if not self.learning_metrics:
            logging.warning("No learning metrics available for visualization")
            # Create a placeholder visualization
            if interactive and INTERACTIVE_VISUALIZATION_AVAILABLE:
                fig = go.Figure()
                fig.add_annotation(
                    text="No statistical learning metrics available",
                    xref="paper", yref="paper",
                    x=0.5, y=0.5,
                    showarrow=False,
                    font=dict(size=20)
                )
                
                if output_file:
                    fig.write_html(output_file)
                    
                return fig
            else:
                # Create placeholder matplotlib figure
                fig, ax = plt.subplots(figsize=(10, 6))
                ax.text(0.5, 0.5, "No statistical learning metrics available",
                       horizontalalignment='center',
                       verticalalignment='center',
                       transform=ax.transAxes,
                       fontsize=14)
                
                if output_file:
                    plt.savefig(output_file, dpi=100, bbox_inches='tight')
                    
                return fig
            
        # Call the visualization method on learning metrics collector
        try:
            return self.learning_metrics.visualize_learning_performance(
                output_file=output_file,
                interactive=interactive,
                **kwargs
            )
        except Exception as e:
            logging.error(f"Error creating learning metrics visualization: {str(e)}")
            # Return a simple error visualization
            if interactive and INTERACTIVE_VISUALIZATION_AVAILABLE:
                fig = go.Figure()
                fig.add_annotation(
                    text=f"Error generating learning metrics visualization: {str(e)}",
                    xref="paper", yref="paper",
                    x=0.5, y=0.5,
                    showarrow=False,
                    font=dict(size=16)
                )
                
                if output_file:
                    fig.write_html(output_file)
                    
                return fig
            else:
                # Create error matplotlib figure
                fig, ax = plt.subplots(figsize=(10, 6))
                ax.text(0.5, 0.5, f"Error generating learning metrics visualization: {str(e)}",
                       horizontalalignment='center',
                       verticalalignment='center',
                       transform=ax.transAxes,
                       fontsize=12,
                       wrap=True)
                
                if output_file:
                    plt.savefig(output_file, dpi=100, bbox_inches='tight')
                    
                return fig
        """
        Create a static HTML dashboard from image files.
        
        Args:
            title: Dashboard title
            processing_chart: Path to processing breakdown chart
            latency_chart: Path to latency distribution chart
            throughput_chart: Path to throughput chart
            complexity_chart: Path to complexity chart
            
        Returns:
            str: HTML content for the dashboard
        """
        # Convert image paths to relative paths for the HTML
        def get_relative_path(path):
            return os.path.basename(path)
        
        processing_rel = get_relative_path(processing_chart)
        latency_rel = get_relative_path(latency_chart)
        throughput_rel = get_relative_path(throughput_chart)
        complexity_rel = get_relative_path(complexity_chart)
        
        # Create HTML template
        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>{{ title }}</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    margin: 0;
                    padding: 20px;
                    background-color: #f5f5f5;
                }
                .dashboard-container {
                    max-width: 1200px;
                    margin: 0 auto;
                    background-color: white;
                    border-radius: 5px;
                    box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                    padding: 20px;
                }
                h1 {
                    color: #333;
                    border-bottom: 1px solid #eee;
                    padding-bottom: 10px;
                }
                .chart-row {
                    display: flex;
                    flex-wrap: wrap;
                    margin: 0 -10px;
                }
                .chart-container {
                    flex: 1 0 45%;
                    margin: 10px;
                    min-width: 500px;
                    background-color: white;
                    border-radius: 5px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                    padding: 15px;
                }
                .chart-title {
                    font-size: 16px;
                    font-weight: bold;
                    margin-bottom: 10px;
                    color: #444;
                }
                img {
                    max-width: 100%;
                    height: auto;
                    display: block;
                    margin: 0 auto;
                }
                .timestamp {
                    color: #666;
                    font-size: 0.8em;
                    margin-top: 20px;
                    text-align: center;
                }
                @media (max-width: 1100px) {
                    .chart-container {
                        flex: 1 0 100%;
                    }
                }
            </style>
        </head>
        <body>
            <div class="dashboard-container">
                <h1>{{ title }}</h1>
                
                <div class="chart-row">
                    <div class="chart-container">
                        <div class="chart-title">Processing Time Breakdown</div>
                        <img src="{{ processing_chart }}" alt="Processing Time Breakdown">
                    </div>
                    
                    <div class="chart-container">
                        <div class="chart-title">Query Latency Distribution</div>
                        <img src="{{ latency_chart }}" alt="Query Latency Distribution">
                    </div>
                </div>
                
                <div class="chart-row">
                    <div class="chart-container">
                        <div class="chart-title">Query Throughput Over Time</div>
                        <img src="{{ throughput_chart }}" alt="Query Throughput">
                    </div>
                    
                    <div class="chart-container">
                        <div class="chart-title">Performance vs Complexity</div>
                        <img src="{{ complexity_chart }}" alt="Performance vs Complexity">
                    </div>
                </div>
                
                <div class="timestamp">Generated on: {{ timestamp }}</div>
            </div>
        </body>
        </html>
        """
        
        # Render the template
        if TEMPLATE_ENGINE_AVAILABLE:
            template = Template(html_template)
            return template.render(
                title=title,
                processing_chart=processing_rel,
                latency_chart=latency_rel,
                throughput_chart=throughput_rel,
                complexity_chart=complexity_rel,
                timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
        else:
            # Simple string replacement if Jinja2 is not available
            return html_template.replace("{{ title }}", title) \
                .replace("{{ processing_chart }}", processing_rel) \
                .replace("{{ latency_chart }}", latency_rel) \
                .replace("{{ throughput_chart }}", throughput_rel) \
                .replace("{{ complexity_chart }}", complexity_rel) \
                .replace("{{ timestamp }}", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    
    def visualize_query_audit_metrics(self, 
                                    output_file: str,
                                    hours_back: int = 24) -> str:
        """
        Generate a visualization combining query metrics with audit metrics.
        
        Args:
            output_file: Path to save the visualization
            hours_back: Number of hours to look back
            
        Returns:
            str: Path to the generated visualization
        """
        if not self.audit_metrics:
            logging.warning("No audit metrics available for combined visualization")
            return self.visualizer.visualize_query_performance_timeline(
                hours_back=hours_back,
                output_file=output_file
            )
            
        # Generate integrated timeline with both query and audit metrics
        if hasattr(self.visualizer, 'visualize_query_audit_timeline'):
            # Use enhanced method if available
            fig = self.visualizer.visualize_query_audit_timeline(
                audit_metrics=self.audit_metrics,
                hours_back=hours_back,
                output_file=output_file
            )
        else:
            # Call the standard timeline creation function
            from ipfs_datasets_py.audit.audit_visualization import create_query_audit_timeline
            fig = create_query_audit_timeline(
                query_metrics_collector=self.query_metrics,
                audit_metrics=self.audit_metrics,
                hours_back=hours_back,
                output_file=output_file
            )
            
        return output_file
    
    def generate_interactive_audit_trends(self,
                                       output_file: str,
                                       audit_metrics_aggregator=None,
                                       period: str = 'daily',
                                       lookback_days: int = 7,
                                       categories: List[str] = None,
                                       theme: str = 'light',
                                       title: str = "Interactive Audit Event Trends",
                                       show_plot: bool = False) -> Optional[Any]:
        """
        Generate interactive visualization of audit trends.
        
        Args:
            output_file: Path to save the visualization
            audit_metrics_aggregator: Optional metrics aggregator (uses self.audit_metrics if None)
            period: Aggregation period ('hourly', 'daily', 'weekly')
            lookback_days: Number of days to look back
            categories: Optional list of specific categories to include
            theme: 'light' or 'dark' color theme
            title: Title for the visualization
            show_plot: Whether to display the plot
            
        Returns:
            Optional[Any]: Plotly figure object if successful
        """
        # Use provided metrics or fall back to instance metrics
        audit_metrics = audit_metrics_aggregator or self.audit_metrics
        
        if not audit_metrics:
            logging.warning("No audit metrics available for interactive visualization")
            return None
            
        try:
            # Import the necessary function
            from ipfs_datasets_py.audit.audit_visualization import create_interactive_audit_trends
            
            # Generate the interactive visualization
            fig = create_interactive_audit_trends(
                metrics_aggregator=audit_metrics,
                period=period,
                lookback_days=lookback_days,
                categories=categories,
                theme=theme,
                title=title,
                output_file=output_file,
                show_plot=show_plot
            )
            
            return fig
            
        except ImportError:
            logging.error("Interactive visualization components not available")
            return None
        except Exception as e:
            logging.error(f"Error generating interactive audit trends: {str(e)}")
            import traceback
            logging.error(traceback.format_exc())
            return None


def create_integrated_monitoring_system(dashboard_dir: str = None):
    """
    Create an integrated monitoring system with audit logging and query metrics.
    
    Args:
        dashboard_dir: Optional directory for dashboard output
        
    Returns:
        tuple: (audit_logger, audit_metrics, query_metrics, dashboard)
    """
    # Initialize audit components
    try:
        from ipfs_datasets_py.audit.audit_logger import AuditLogger
        from ipfs_datasets_py.audit.audit_visualization import (
            AuditMetricsAggregator, 
            setup_audit_visualization
        )
        
        # Create audit logger and metrics
        audit_logger = AuditLogger()
        audit_metrics, audit_visualizer, audit_alert_manager = setup_audit_visualization(audit_logger)
        
    except ImportError:
        logging.warning("Audit components not available, creating query metrics only")
        audit_logger = None
        audit_metrics = None
        audit_visualizer = None
    
    # Create query metrics collector
    query_metrics = QueryMetricsCollector()
    
    # Create dashboard
    dashboard = RAGQueryDashboard(
        metrics_collector=query_metrics,
        audit_metrics=audit_metrics
    )
    
    # Integrate metrics with audit system if available
    if audit_logger and audit_metrics:
        integrate_with_audit_system(
            query_metrics=query_metrics,
            audit_alert_manager=audit_alert_manager,  # Use the alert manager we got from setup_audit_visualization
            audit_logger=audit_logger
        )
    
    # Create dashboard directory if specified
    if dashboard_dir:
        os.makedirs(dashboard_dir, exist_ok=True)
    
    return audit_logger, audit_metrics, query_metrics, dashboard


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
        self.learning_cycles = []  # Learning cycle completion events
        self.parameter_adaptations = {}  # Parameter changes over time {param_name: [(timestamp, value), ...]}
        self.strategy_effectiveness = {}  # Strategy effectiveness metrics {strategy: {success_rate, avg_time, count}}
        self.pattern_recognition = {}  # Query pattern recognition metrics {pattern: count}
        
        # Aggregated statistics
        self.total_learning_cycles = 0
        self.total_parameter_adaptations = 0
        self.total_queries_analyzed = 0
        self.last_learning_cycle_time = None
        
    def record_learning_cycle(self, cycle_data):
        """
        Record a completed learning cycle.
        
        Args:
            cycle_data (dict): Data about the learning cycle including:
                - timestamp: When the cycle completed
                - analyzed_queries: Number of queries analyzed
                - optimization_rules: Rules derived from learning
                - error: Any error encountered during learning (optional)
        """
        with self._lock:
            timestamp = cycle_data.get('timestamp', datetime.datetime.now())
            
            # Create cycle record
            cycle_record = {
                'timestamp': timestamp,
                'analyzed_queries': cycle_data.get('analyzed_queries', 0),
                'rule_count': len(cycle_data.get('optimization_rules', {})),
                'error': cycle_data.get('error')
            }
            
            # Add to history, maintaining size limit
            self.learning_cycles.append(cycle_record)
            if len(self.learning_cycles) > self.max_history_size:
                self.learning_cycles = self.learning_cycles[-self.max_history_size:]
                
            # Update aggregated statistics
            self.total_learning_cycles += 1
            self.total_queries_analyzed += cycle_record['analyzed_queries']
            self.last_learning_cycle_time = timestamp
            
            # Save to disk if configured
            if self.metrics_dir:
                self._save_metrics_to_disk('learning_cycles.json', self.learning_cycles)
    
    def record_parameter_adaptation(self, param_name, old_value, new_value, timestamp=None):
        """
        Record a parameter adaptation from learning.
        
        Args:
            param_name (str): Name of the parameter that was adapted
            old_value: Previous parameter value
            new_value: New parameter value after adaptation
            timestamp (datetime, optional): Timestamp for the adaptation, defaults to now
        """
        with self._lock:
            timestamp = timestamp or datetime.datetime.now()
            
            # Initialize parameter history if needed
            if param_name not in self.parameter_adaptations:
                self.parameter_adaptations[param_name] = []
                
            # Add adaptation to history
            adaptation = {
                'timestamp': timestamp,
                'old_value': self._convert_to_serializable(old_value),
                'new_value': self._convert_to_serializable(new_value),
                'delta': self._calculate_delta(old_value, new_value)
            }
            
            self.parameter_adaptations[param_name].append(adaptation)
            
            # Limit history size
            if len(self.parameter_adaptations[param_name]) > self.max_history_size:
                self.parameter_adaptations[param_name] = self.parameter_adaptations[param_name][-self.max_history_size:]
                
            # Update aggregated statistics
            self.total_parameter_adaptations += 1
            
            # Save to disk if configured
            if self.metrics_dir:
                self._save_metrics_to_disk('parameter_adaptations.json', self.parameter_adaptations)
    
    def record_strategy_effectiveness(self, strategy_name, success, execution_time):
        """
        Record effectiveness of an optimization strategy.
        
        Args:
            strategy_name (str): Name of the optimization strategy
            success (bool): Whether the strategy was successful
            execution_time (float): Time taken to execute the query with this strategy
        """
        with self._lock:
            # Initialize strategy metrics if needed
            if strategy_name not in self.strategy_effectiveness:
                self.strategy_effectiveness[strategy_name] = {
                    'success_count': 0,
                    'total_count': 0,
                    'total_time': 0,
                    'avg_time': 0,
                    'history': []
                }
                
            # Update metrics
            metrics = self.strategy_effectiveness[strategy_name]
            metrics['total_count'] += 1
            if success:
                metrics['success_count'] += 1
            metrics['total_time'] += execution_time
            metrics['avg_time'] = metrics['total_time'] / metrics['total_count']
            
            # Add to history
            metrics['history'].append({
                'timestamp': datetime.datetime.now(),
                'success': success,
                'execution_time': execution_time
            })
            
            # Limit history size
            if len(metrics['history']) > self.max_history_size:
                metrics['history'] = metrics['history'][-self.max_history_size:]
                
            # Save to disk if configured
            if self.metrics_dir:
                self._save_metrics_to_disk('strategy_effectiveness.json', self.strategy_effectiveness)
    
    def record_query_pattern(self, pattern):
        """
        Record a recognized query pattern.
        
        Args:
            pattern (dict): Query pattern information
        """
        with self._lock:
            # Create a stable pattern key from the pattern dict
            pattern_key = self._create_pattern_key(pattern)
            
            # Update pattern count
            if pattern_key not in self.pattern_recognition:
                self.pattern_recognition[pattern_key] = {
                    'count': 0,
                    'first_seen': datetime.datetime.now(),
                    'last_seen': datetime.datetime.now(),
                    'pattern': pattern
                }
            
            self.pattern_recognition[pattern_key]['count'] += 1
            self.pattern_recognition[pattern_key]['last_seen'] = datetime.datetime.now()
            
            # Save to disk if configured
            if self.metrics_dir:
                self._save_metrics_to_disk('query_patterns.json', self.pattern_recognition)
    
    def get_learning_metrics(self):
        """
        Get aggregated learning metrics.
        
        Returns:
            dict: Aggregated metrics about the learning process
        """
        with self._lock:
            return {
                'total_learning_cycles': self.total_learning_cycles,
                'total_parameter_adaptations': self.total_parameter_adaptations,
                'total_queries_analyzed': self.total_queries_analyzed,
                'last_learning_cycle_time': self.last_learning_cycle_time,
                'recognized_patterns': len(self.pattern_recognition),
                'tracked_strategies': len(self.strategy_effectiveness),
                'tracked_parameters': len(self.parameter_adaptations)
            }
    
    def get_parameter_history(self, param_name=None, limit=None):
        """
        Get parameter adaptation history.
        
        Args:
            param_name (str, optional): Specific parameter to get history for
            limit (int, optional): Maximum number of entries to return
            
        Returns:
            dict: Parameter adaptation history
        """
        with self._lock:
            if param_name and param_name in self.parameter_adaptations:
                history = self.parameter_adaptations[param_name]
                if limit:
                    history = history[-limit:]
                return {param_name: history}
            elif not param_name:
                # Return all parameters but limit each one's history
                if limit:
                    return {
                        param: history[-limit:] 
                        for param, history in self.parameter_adaptations.items()
                    }
                return self.parameter_adaptations
            return {}
    
    def get_strategy_metrics(self, strategy_name=None):
        """
        Get metrics for optimization strategies.
        
        Args:
            strategy_name (str, optional): Specific strategy to get metrics for
            
        Returns:
            dict: Strategy effectiveness metrics
        """
        with self._lock:
            if strategy_name and strategy_name in self.strategy_effectiveness:
                return {strategy_name: self.strategy_effectiveness[strategy_name]}
            return self.strategy_effectiveness
    
    def get_top_query_patterns(self, top_n=10):
        """
        Get the most common query patterns.
        
        Args:
            top_n (int): Number of top patterns to return
            
        Returns:
            list: Top query patterns with their metrics
        """
        with self._lock:
            # Sort patterns by count, descending
            sorted_patterns = sorted(
                self.pattern_recognition.items(),
                key=lambda x: x[1]['count'],
                reverse=True
            )
            
            # Return top N patterns
            return [
                {
                    'pattern_key': key,
                    'pattern': data['pattern'],
                    'count': data['count'],
                    'first_seen': data['first_seen'],
                    'last_seen': data['last_seen']
                }
                for key, data in sorted_patterns[:top_n]
            ]
    
    def visualize_learning_cycles(self, output_file=None, show_plot=True, figsize=None):
        """
        Visualize learning cycles over time.
        
        Args:
            output_file (str, optional): Path to save the visualization
            show_plot (bool): Whether to display the plot
            figsize (tuple, optional): Figure size (width, height) in inches
            
        Returns:
            matplotlib.figure.Figure: The generated figure
        """
        if not VISUALIZATION_LIBS_AVAILABLE:
            return None
            
        # Extract data from learning cycles
        if not self.learning_cycles:
            return None
            
        timestamps = [cycle['timestamp'] for cycle in self.learning_cycles]
        analyzed_queries = [cycle['analyzed_queries'] for cycle in self.learning_cycles]
        rule_counts = [cycle['rule_count'] for cycle in self.learning_cycles]
        errors = [cycle['error'] is not None for cycle in self.learning_cycles]
        
        # Create figure
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=figsize or (10, 8), sharex=True)
        
        # Plot analyzed queries
        ax1.plot(timestamps, analyzed_queries, 'o-', color='#2196F3', label='Analyzed Queries')
        ax1.set_ylabel('Queries Analyzed')
        ax1.set_title('RAG Query Optimizer Learning Cycles')
        ax1.grid(True, alpha=0.3)
        
        # Plot rule counts
        ax2.plot(timestamps, rule_counts, 'o-', color='#4CAF50', label='Optimization Rules')
        ax2.set_xlabel('Time')
        ax2.set_ylabel('Rules Generated')
        ax2.grid(True, alpha=0.3)
        
        # Mark error cycles
        for i, (timestamp, error) in enumerate(zip(timestamps, errors)):
            if error:
                ax1.plot(timestamp, analyzed_queries[i], 'rx', markersize=10)
                ax2.plot(timestamp, rule_counts[i], 'rx', markersize=10)
        
        # Add legend for errors
        from matplotlib.lines import Line2D
        error_legend = Line2D([0], [0], marker='x', color='r', 
                             label='Learning Error', markersize=10, linestyle='')
        ax1.legend(handles=[error_legend])
        
        # Format x-axis as dates
        fig.autofmt_xdate()
        
        # Adjust layout
        plt.tight_layout()
        
        # Save plot if output file is specified
        if output_file:
            plt.savefig(output_file, dpi=300, bbox_inches='tight')
        
        # Show or close the plot
        if show_plot:
            plt.show()
        else:
            plt.close(fig)
            
        return fig
    
    def visualize_parameter_adaptations(self, param_names=None, output_file=None, 
                                      show_plot=True, figsize=None):
        """
        Visualize parameter adaptations over time.
        
        Args:
            param_names (list, optional): List of parameter names to include
            output_file (str, optional): Path to save the visualization
            show_plot (bool): Whether to display the plot
            figsize (tuple, optional): Figure size (width, height) in inches
            
        Returns:
            matplotlib.figure.Figure: The generated figure
        """
        if not VISUALIZATION_LIBS_AVAILABLE:
            return None
            
        # Check if we have parameter adaptations
        if not self.parameter_adaptations:
            return None
            
        # Determine which parameters to plot
        if param_names:
            parameters = {p: self.parameter_adaptations[p] for p in param_names 
                         if p in self.parameter_adaptations}
        else:
            # If not specified, plot up to 4 most frequently adapted parameters
            sorted_params = sorted(
                self.parameter_adaptations.items(),
                key=lambda x: len(x[1]),
                reverse=True
            )
            parameters = dict(sorted_params[:4])
            
        if not parameters:
            return None
            
        # Create figure with subplots for each parameter
        n_params = len(parameters)
        fig, axes = plt.subplots(n_params, 1, figsize=figsize or (10, 3*n_params))
        
        # Handle case with only one parameter
        if n_params == 1:
            axes = [axes]
            
        # Plot each parameter
        for i, (param_name, adaptations) in enumerate(parameters.items()):
            ax = axes[i]
            
            timestamps = [a['timestamp'] for a in adaptations]
            values = [a['new_value'] for a in adaptations]
            
            ax.plot(timestamps, values, 'o-', label=param_name)
            ax.set_ylabel(f'{param_name} Value')
            ax.set_title(f'{param_name} Adaptations Over Time')
            ax.grid(True, alpha=0.3)
            
            # Add percent change annotations
            for j in range(1, len(adaptations)):
                prev = adaptations[j-1]['new_value']
                curr = adaptations[j]['new_value']
                if prev != 0:  # Avoid division by zero
                    pct_change = ((curr - prev) / abs(prev)) * 100
                    ax.annotate(f"{pct_change:.1f}%", 
                               (timestamps[j], values[j]),
                               textcoords="offset points",
                               xytext=(0, 10),
                               ha='center')
        
        # Format x-axis as dates
        fig.autofmt_xdate()
        
        # Adjust layout
        plt.tight_layout()
        
        # Save plot if output file is specified
        if output_file:
            plt.savefig(output_file, dpi=300, bbox_inches='tight')
        
        # Show or close the plot
        if show_plot:
            plt.show()
        else:
            plt.close(fig)
            
        return fig
    
    def visualize_strategy_effectiveness(self, output_file=None, show_plot=True, figsize=None):
        """
        Visualize the effectiveness of different optimization strategies.
        
        Args:
            output_file (str, optional): Path to save the visualization
            show_plot (bool): Whether to display the plot
            figsize (tuple, optional): Figure size (width, height) in inches
            
        Returns:
            matplotlib.figure.Figure: The generated figure
        """
        if not VISUALIZATION_LIBS_AVAILABLE:
            return None
            
        # Check if we have strategy metrics
        if not self.strategy_effectiveness:
            return None
            
        # Extract data
        strategies = list(self.strategy_effectiveness.keys())
        success_rates = [
            (metrics['success_count'] / metrics['total_count']) * 100 
            if metrics['total_count'] > 0 else 0
            for metrics in self.strategy_effectiveness.values()
        ]
        avg_times = [metrics['avg_time'] for metrics in self.strategy_effectiveness.values()]
        counts = [metrics['total_count'] for metrics in self.strategy_effectiveness.values()]
        
        # Create figure
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=figsize or (12, 6))
        
        # Plot success rates
        bars1 = ax1.bar(strategies, success_rates, color='#2196F3')
        ax1.set_ylabel('Success Rate (%)')
        ax1.set_title('Strategy Success Rates')
        ax1.set_ylim(0, 100)
        
        # Add count labels
        for bar, count in zip(bars1, counts):
            ax1.text(bar.get_x() + bar.get_width()/2, 5,
                   f'n={count}', ha='center', va='bottom',
                   color='white', fontweight='bold')
        
        # Plot average execution times
        bars2 = ax2.bar(strategies, avg_times, color='#FF9800')
        ax2.set_ylabel('Avg. Execution Time (s)')
        ax2.set_title('Strategy Execution Times')
        
        # Add time labels
        for bar, time_val in zip(bars2, avg_times):
            ax2.text(bar.get_x() + bar.get_width()/2, time_val + 0.05,
                   f'{time_val:.3f}s', ha='center', va='bottom',
                   fontsize=9)
        
        # Rotate x-axis labels for readability
        for ax in (ax1, ax2):
            plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
        
        # Adjust layout
        plt.tight_layout()
        
        # Save plot if output file is specified
        if output_file:
            plt.savefig(output_file, dpi=300, bbox_inches='tight')
        
        # Show or close the plot
        if show_plot:
            plt.show()
        else:
            plt.close(fig)
            
        return fig
    
    def visualize_query_patterns(self, output_file=None, top_n=5, show_plot=True, figsize=None):
        """
        Visualize the distribution of query patterns recognized by the optimizer.
        
        Args:
            output_file (str, optional): Path to save the visualization
            top_n (int): Number of top patterns to include
            show_plot (bool): Whether to display the plot
            figsize (tuple, optional): Figure size (width, height) in inches
            
        Returns:
            matplotlib.figure.Figure: The generated figure
        """
        if not VISUALIZATION_LIBS_AVAILABLE:
            return None
            
        # Get top patterns
        top_patterns = self.get_top_query_patterns(top_n)
        if not top_patterns:
            return None
            
        # Extract data
        pattern_names = [f"Pattern {i+1}" for i in range(len(top_patterns))]
        pattern_counts = [p['count'] for p in top_patterns]
        
        # Create figure
        fig, ax = plt.subplots(figsize=figsize or (10, 6))
        
        # Plot pattern distribution
        bars = ax.bar(pattern_names, pattern_counts, color='#673AB7')
        ax.set_ylabel('Query Count')
        ax.set_title('Top Query Patterns Recognized by Optimizer')
        
        # Add pattern details in annotations
        for i, (bar, pattern) in enumerate(zip(bars, top_patterns)):
            pattern_text = str(pattern['pattern']).replace("{", "").replace("}", "")
            if len(pattern_text) > 30:
                pattern_text = pattern_text[:27] + "..."
                
            ax.annotate(
                pattern_text,
                xy=(bar.get_x() + bar.get_width()/2, 5),
                xytext=(0, -25),
                textcoords="offset points",
                ha='center', va='top',
                fontsize=8,
                rotation=45
            )
            
            # Add count on top of bar
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                   f'{bar.get_height()}', ha='center', va='bottom')
        
        # Add extra space at bottom for annotations
        plt.subplots_adjust(bottom=0.25)
        
        # Save plot if output file is specified
        if output_file:
            plt.savefig(output_file, dpi=300, bbox_inches='tight')
        
        # Show or close the plot
        if show_plot:
            plt.show()
        else:
            plt.close(fig)
            
        return fig
    
    def visualize_learning_performance(self, output_file=None, interactive=True, **kwargs):
        """
        Create a comprehensive visualization of learning performance metrics.
        
        This is a high-level method that combines multiple visualizations 
        into a single output for easy analysis of the learning process.
        
        Args:
            output_file (str, optional): Path to save the visualization
            interactive (bool): Whether to create interactive visualization
            **kwargs: Additional arguments for specific visualizations
            
        Returns:
            Object: Figure object or path to saved file
        """
        if interactive and INTERACTIVE_VISUALIZATION_AVAILABLE:
            # Create interactive dashboard
            return self.create_interactive_learning_dashboard(
                output_file=output_file,
                show_plot=kwargs.get('show_plot', False)
            )
        else:
            # Create static visualizations
            if not output_file:
                # Generate default filename if not provided
                import tempfile
                temp_dir = tempfile.mkdtemp()
                output_file = os.path.join(temp_dir, "learning_performance.png")
                
            # Create a visualization of learning cycles
            fig = self.visualize_learning_cycles(
                output_file=output_file,
                show_plot=kwargs.get('show_plot', False)
            )
            
            return fig
    
    def create_interactive_learning_dashboard(self, output_file, show_plot=False):
        """
        Create an interactive dashboard for learning metrics visualization using Plotly.
        
        Args:
            output_file (str): Path to save the HTML dashboard
            show_plot (bool): Whether to display the plot
            
        Returns:
            str: Path to the generated dashboard
        """
        if not INTERACTIVE_VISUALIZATION_AVAILABLE or not TEMPLATE_ENGINE_AVAILABLE:
            return None
            
        # Create directory for output file if it doesn't exist
        os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
        
        # Create subplot figure
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=(
                'Learning Cycles', 
                'Parameter Adaptations',
                'Strategy Effectiveness', 
                'Query Pattern Distribution'
            ),
            specs=[
                [{"type": "scatter"}, {"type": "scatter"}],
                [{"type": "bar"}, {"type": "bar"}]
            ]
        )
        
        # Add learning cycles plot
        if self.learning_cycles:
            timestamps = [cycle['timestamp'] for cycle in self.learning_cycles]
            analyzed_queries = [cycle['analyzed_queries'] for cycle in self.learning_cycles]
            rule_counts = [cycle['rule_count'] for cycle in self.learning_cycles]
            
            fig.add_trace(
                go.Scatter(
                    x=timestamps,
                    y=analyzed_queries,
                    mode='lines+markers',
                    name='Analyzed Queries',
                    line=dict(color='#2196F3')
                ),
                row=1, col=1
            )
            
            fig.add_trace(
                go.Scatter(
                    x=timestamps,
                    y=rule_counts,
                    mode='lines+markers',
                    name='Optimization Rules',
                    line=dict(color='#4CAF50')
                ),
                row=1, col=1
            )
        
        # Add parameter adaptations plot
        if self.parameter_adaptations:
            # Take top 3 most adapted parameters
            sorted_params = sorted(
                self.parameter_adaptations.items(),
                key=lambda x: len(x[1]),
                reverse=True
            )[:3]
            
            for param_name, adaptations in sorted_params:
                timestamps = [a['timestamp'] for a in adaptations]
                values = [a['new_value'] for a in adaptations]
                
                fig.add_trace(
                    go.Scatter(
                        x=timestamps,
                        y=values,
                        mode='lines+markers',
                        name=param_name
                    ),
                    row=1, col=2
                )
        
        # Add strategy effectiveness plot
        if self.strategy_effectiveness:
            strategies = list(self.strategy_effectiveness.keys())
            success_rates = [
                (metrics['success_count'] / metrics['total_count']) * 100 
                if metrics['total_count'] > 0 else 0
                for metrics in self.strategy_effectiveness.values()
            ]
            
            fig.add_trace(
                go.Bar(
                    x=strategies,
                    y=success_rates,
                    name='Success Rate (%)',
                    marker_color='#2196F3'
                ),
                row=2, col=1
            )
        
        # Add query pattern distribution plot
        top_patterns = self.get_top_query_patterns(5)
        if top_patterns:
            pattern_names = [f"Pattern {i+1}" for i in range(len(top_patterns))]
            pattern_counts = [p['count'] for p in top_patterns]
            
            fig.add_trace(
                go.Bar(
                    x=pattern_names,
                    y=pattern_counts,
                    name='Query Patterns',
                    marker_color='#673AB7',
                    text=[str(p['pattern']) for p in top_patterns],
                    hoverinfo='text+y'
                ),
                row=2, col=2
            )
        
        # Update layout
        fig.update_layout(
            title_text="RAG Query Optimizer Learning Metrics",
            height=800,
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            )
        )
        
        # Save to HTML
        fig.write_html(output_file)
        
        # Show plot if requested
        if show_plot:
            fig.show()
            
        return output_file
        
    def _save_metrics_to_disk(self, filename, data):
        """Save metrics data to disk in JSON format."""
        try:
            filepath = os.path.join(self.metrics_dir, filename)
            with open(filepath, 'w') as f:
                json.dump(self._convert_to_serializable(data), f)
        except Exception as e:
            logging.error(f"Error saving metrics to {filename}: {str(e)}")
    
    def _convert_to_serializable(self, obj):
        """Convert objects to JSON serializable format."""
        if isinstance(obj, dict):
            return {k: self._convert_to_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._convert_to_serializable(item) for item in obj]
        elif isinstance(obj, (np.int64, np.int32, np.int16, np.int8)):
            return int(obj)
        elif isinstance(obj, (np.float64, np.float32, np.float16)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, datetime.datetime):
            return obj.isoformat()
        else:
            return obj
    
    def _calculate_delta(self, old_value, new_value):
        """Calculate delta between old and new values, handling different types."""
        try:
            if isinstance(old_value, (int, float)) and isinstance(new_value, (int, float)):
                return new_value - old_value
            elif isinstance(old_value, (list, np.ndarray)) and isinstance(new_value, (list, np.ndarray)):
                # For lists/arrays, return average change
                old_arr = np.array(old_value)
                new_arr = np.array(new_value)
                if old_arr.size == new_arr.size:
                    return float(np.mean(new_arr - old_arr))
            # Default for non-numeric or incomparable types
            return None
        except:
            return None
    
    def _create_pattern_key(self, pattern):
        """Create a stable string key from a pattern dictionary."""
        try:
            # Sort the dictionary items to create a stable representation
            sorted_items = sorted(
                [(str(k), str(v)) for k, v in pattern.items()],
                key=lambda x: x[0]
            )
            # Join into a single string
            return ":".join([f"{k}={v}" for k, v in sorted_items])
        except:
            # Fallback to string representation if sorting fails
            return str(pattern)


# Version constant used by tests to check feature availability
ENHANCED_VIS_AVAILABLE = True


def create_learning_metrics_visualizations(output_dir=None, theme="light"):
    """
    Create example visualizations for RAG query optimizer learning metrics.
    
    This function demonstrates the visualization capabilities for learning metrics
    by creating sample visualizations using simulated data.
    
    Args:
        output_dir: Directory to save visualizations
        theme: Color theme ('light' or 'dark')
        
    Returns:
        Dict of visualization file paths
    """
    try:
        from ipfs_datasets_py.audit.audit_visualization import OptimizerLearningMetricsVisualizer
    except ImportError:
        logging.error("OptimizerLearningMetricsVisualizer not available")
        return None
        
    import tempfile
    import datetime
    import random
    import os
    
    # Create output directory if not provided
    if not output_dir:
        output_dir = os.path.join(tempfile.gettempdir(), "rag_learning_metrics")
        os.makedirs(output_dir, exist_ok=True)
    
    # Create a mock metrics collector
    class MockLearningMetricsCollector:
        def __init__(self):
            self.learning_cycles = []
            self.parameter_adaptations = []
            self.strategy_effectiveness = []
            
            # Generate sample data
            self._generate_learning_cycles()
            self._generate_parameter_adaptations()
            self._generate_strategy_effectiveness()
            
        def _generate_learning_cycles(self):
            """Generate sample learning cycle data."""
            now = datetime.datetime.now()
            
            for i in range(10):
                self.learning_cycles.append({
                    'cycle_id': f"cycle_{i}",
                    'timestamp': now - datetime.timedelta(days=10-i),
                    'analyzed_queries': 10 + i * 5 + random.randint(-2, 2),
                    'patterns_identified': 2 + i + random.randint(0, 2),
                    'parameters_adjusted': i % 3 + 1,
                    'execution_time': 2.5 + i * 0.5 + random.random()
                })
                
        def _generate_parameter_adaptations(self):
            """Generate sample parameter adaptation data."""
            now = datetime.datetime.now()
            param_names = ['max_depth', 'min_similarity', 'vector_weight', 'graph_weight', 'cache_ttl']
            
            for i in range(20):
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
                
                self.parameter_adaptations.append({
                    'parameter_name': param_name,
                    'old_value': old_value,
                    'new_value': new_value,
                    'timestamp': now - datetime.timedelta(days=10-i//2)
                })
                
        def _generate_strategy_effectiveness(self):
            """Generate sample strategy effectiveness data."""
            now = datetime.datetime.now()
            strategies = ['vector_first', 'graph_first', 'balanced']
            query_types = ['factual', 'complex', 'exploratory']
            
            for i in range(30):
                strategy = strategies[i % len(strategies)]
                query_type = query_types[(i // 3) % len(query_types)]
                timestamp = now - datetime.timedelta(days=15-i//2)
                
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
                    
                self.strategy_effectiveness.append({
                    'strategy': strategy,
                    'query_type': query_type,
                    'success_rate': success_rate,
                    'mean_latency': mean_latency,
                    'sample_size': 10 + i,
                    'timestamp': timestamp
                })
    
    # Create the mock collector and visualizer
    collector = MockLearningMetricsCollector()
    visualizer = OptimizerLearningMetricsVisualizer(collector, output_dir)
    
    # Generate visualizations
    results = {}
    
    # Create static visualizations
    if VISUALIZATION_LIBS_AVAILABLE:
        cycles_png = os.path.join(output_dir, "learning_cycles.png")
        cycles_fig = visualizer.visualize_learning_cycles(
            output_file=cycles_png,
            theme=theme,
            interactive=False
        )
        results['learning_cycles_static'] = cycles_png if cycles_fig else None
        
        params_png = os.path.join(output_dir, "parameter_adaptations.png")
        params_fig = visualizer.visualize_parameter_adaptations(
            output_file=params_png,
            theme=theme,
            interactive=False
        )
        results['parameter_adaptations_static'] = params_png if params_fig else None
        
        strategy_png = os.path.join(output_dir, "strategy_effectiveness.png")
        strategy_fig = visualizer.visualize_strategy_effectiveness(
            output_file=strategy_png,
            theme=theme,
            interactive=False
        )
        results['strategy_effectiveness_static'] = strategy_png if strategy_fig else None
    
    # Create interactive visualizations
    if INTERACTIVE_VISUALIZATION_AVAILABLE:
        cycles_html = os.path.join(output_dir, "learning_cycles.html")
        cycles_fig = visualizer.visualize_learning_cycles(
            output_file=cycles_html,
            theme=theme,
            interactive=True
        )
        results['learning_cycles_interactive'] = cycles_html if cycles_fig else None
        
        params_html = os.path.join(output_dir, "parameter_adaptations.html")
        params_fig = visualizer.visualize_parameter_adaptations(
            output_file=params_html,
            theme=theme,
            interactive=True
        )
        results['parameter_adaptations_interactive'] = params_html if params_fig else None
        
        strategy_html = os.path.join(output_dir, "strategy_effectiveness.html")
        strategy_fig = visualizer.visualize_strategy_effectiveness(
            output_file=strategy_html,
            theme=theme,
            interactive=True
        )
        results['strategy_effectiveness_interactive'] = strategy_html if strategy_fig else None
    
    # Create dashboard
    if TEMPLATE_ENGINE_AVAILABLE and INTERACTIVE_VISUALIZATION_AVAILABLE:
        dashboard_html = os.path.join(output_dir, "learning_metrics_dashboard.html")
        dashboard_path = visualizer.generate_learning_metrics_dashboard(
            output_file=dashboard_html,
            theme=theme
        )
        results['dashboard'] = dashboard_path
    
    return results