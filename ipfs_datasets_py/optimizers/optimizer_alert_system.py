"""
RAG Query Optimizer Learning Alert System

This module provides an alert system for monitoring the RAG query optimizer's
learning process and detecting anomalies, such as parameter oscillations,
declining performance, and other issues that might indicate problems.
"""
from dataclasses import dataclass, field
import datetime
import json
import logging
import os
import threading
import time
from typing import Dict, List, Any, Optional, Callable


from ipfs_datasets_py.optimizers.optimizer_learning_metrics import OptimizerLearningMetricsCollector


# Setup logging
logger = logging.getLogger(__name__)


@dataclass
class LearningAnomaly:
    """
    Represents a detected anomaly in the learning process.

    Attributes:
        anomaly_type: Type of anomaly (oscillation, decline, etc.)
        severity: Severity level (info, warning, critical)
        description: Human-readable description of the anomaly
        affected_parameters: Parameters affected by the anomaly
        timestamp: When the anomaly was detected
        metric_values: Relevant metric values related to the anomaly
        id: Unique identifier for the anomaly
    """
    anomaly_type: str
    severity: str
    description: str
    affected_parameters: List[str] = field(default_factory=list)
    timestamp: datetime.datetime = field(default_factory=datetime.datetime.now)
    metric_values: Dict[str, Any] = field(default_factory=dict)
    id: str = field(default="")

    def __post_init__(self):
        """Set default ID if not provided."""
        if not self.id:
            self.id = f"{int(time.time())}_{self.anomaly_type}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert the anomaly to a dictionary."""
        return {
            'id': self.id,
            'anomaly_type': self.anomaly_type,
            'severity': self.severity,
            'description': self.description,
            'affected_parameters': self.affected_parameters,
            'timestamp': self.timestamp.isoformat(),
            'metric_values': self.metric_values
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LearningAnomaly':
        """Create an anomaly from a dictionary."""
        # Parse timestamp if it's a string
        timestamp = data.get('timestamp')
        if isinstance(timestamp, str):
            timestamp = datetime.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))

        return cls(
            anomaly_type=data.get('anomaly_type', 'unknown'),
            severity=data.get('severity', 'warning'),
            description=data.get('description', 'Unknown anomaly'),
            affected_parameters=data.get('affected_parameters', []),
            timestamp=timestamp,
            metric_values=data.get('metric_values', {}),
            id=data.get('id', '')
        )


class LearningAlertSystem:
    """
    Alert system for monitoring the optimizer's learning process.

    This class detects anomalies in the optimizer's learning process, such as:
    - Parameter oscillations (parameters change back and forth)
    - Performance declines (success rates dropping or latencies increasing)
    - Strategy effectiveness issues (certain strategies becoming less effective)
    - Stalled learning (no parameter adjustments despite query pattern changes)
    """

    def __init__(
        self,
        metrics_collector: Optional[OptimizerLearningMetricsCollector] = None,
        alert_handlers: Optional[List[Callable]] = None,
        check_interval: int = 900,  # 15 minutes
        alerts_dir: Optional[str] = None,
        alert_config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize the alert system.

        Args:
            metrics_collector: Collector with learning metrics data
            alert_handlers: Functions to call when anomalies are detected
            check_interval: Interval in seconds for checking anomalies
            alerts_dir: Directory to store alert records
            alert_config: Configuration parameters for alerts
        """
        self.metrics_collector = metrics_collector
        self.alert_handlers = alert_handlers or []
        self.check_interval = check_interval

        # Set up alerts directory
        self.alerts_dir = alerts_dir
        if self.alerts_dir and not os.path.exists(self.alerts_dir):
            os.makedirs(self.alerts_dir, exist_ok=True)

        # Set up alert configuration with defaults
        self.alert_config = {
            'oscillation_threshold': 3,  # Number of reversals to count as oscillation
            'performance_decline_threshold': 0.15,  # 15% decline to trigger alert
            'learning_stall_threshold': 20,  # Number of queries without parameter adjustment
            'min_sample_size': 5,  # Minimum samples needed for trend detection
            'recent_window_size': 10,  # Number of recent events to consider
            'severity_thresholds': {
                'minor': 0.1,  # 10% change
                'moderate': 0.2,  # 20% change
                'major': 0.3  # 30% change
            }
        }

        # Override defaults with provided configuration
        if alert_config:
            self.alert_config.update(alert_config)

        # Recent anomalies tracking (to avoid duplicate alerts)
        self.recent_anomalies = []
        self.max_recent_anomalies = 100

        # Set up monitoring thread
        self._stop_monitoring = threading.Event()
        self._monitoring_thread = None
        self.last_check_time = time.time()

    def start_monitoring(self):
        """Start automatic monitoring of learning metrics."""
        if not self.metrics_collector:
            logger.warning("No metrics collector available. Cannot start monitoring.")
            return

        if self._monitoring_thread is not None and self._monitoring_thread.is_alive():
            logger.warning("Monitoring thread is already running")
            return

        self._stop_monitoring.clear()
        self._monitoring_thread = threading.Thread(
            target=self._monitoring_loop,
            daemon=True
        )
        self._monitoring_thread.start()
        logger.info(f"Started learning metrics monitoring with interval {self.check_interval} seconds")

    def stop_monitoring(self):
        """Stop the automatic monitoring."""
        if self._monitoring_thread is None or not self._monitoring_thread.is_alive():
            logger.warning("Monitoring thread is not running")
            return

        self._stop_monitoring.set()
        self._monitoring_thread.join(timeout=5.0)
        logger.info("Stopped learning metrics monitoring")

    def _monitoring_loop(self):
        """Background thread that periodically checks for anomalies."""
        while not self._stop_monitoring.is_set():
            # Wait for a short time and check stop flag
            for _ in range(60):  # Check every second
                if self._stop_monitoring.is_set():
                    return
                time.sleep(1)

            # Check if it's time to run anomaly detection
            current_time = time.time()
            if current_time - self.last_check_time >= self.check_interval:
                try:
                    logger.info("Running anomaly detection...")
                    anomalies = self.check_anomalies()

                    if anomalies:
                        logger.info(f"Detected {len(anomalies)} anomalies")
                        for anomaly in anomalies:
                            self.handle_anomaly(anomaly)
                    else:
                        logger.info("No anomalies detected")

                    self.last_check_time = current_time
                except Exception as e:
                    logger.error(f"Error during anomaly detection: {e}")

    def check_anomalies(self) -> List[LearningAnomaly]:
        """
        Check for anomalies in the learning process.

        Returns:
            List[LearningAnomaly]: Detected anomalies
        """
        if not self.metrics_collector:
            return []

        anomalies = []

        # Check for parameter oscillations
        oscillation_anomalies = self._detect_parameter_oscillations()
        anomalies.extend(oscillation_anomalies)

        # Check for performance declines
        performance_anomalies = self._detect_performance_declines()
        anomalies.extend(performance_anomalies)

        # Check for strategy effectiveness issues
        strategy_anomalies = self._detect_strategy_issues()
        anomalies.extend(strategy_anomalies)

        # Check for stalled learning
        stall_anomalies = self._detect_learning_stalls()
        anomalies.extend(stall_anomalies)

        # Filter out duplicate recent anomalies
        filtered_anomalies = [
            anomaly for anomaly in anomalies
            if not self._is_duplicate_anomaly(anomaly)
        ]

        # Add to recent anomalies list
        self.recent_anomalies.extend(filtered_anomalies)

        # Keep only the most recent anomalies
        if len(self.recent_anomalies) > self.max_recent_anomalies:
            self.recent_anomalies = self.recent_anomalies[-self.max_recent_anomalies:]

        return filtered_anomalies

    def _is_duplicate_anomaly(self, anomaly: LearningAnomaly) -> bool:
        """Check if an anomaly is a duplicate of a recent one."""
        for recent in self.recent_anomalies:
            # If same type, parameters, and within 1 hour
            if (
                recent.anomaly_type == anomaly.anomaly_type and
                set(recent.affected_parameters) == set(anomaly.affected_parameters) and
                abs((recent.timestamp - anomaly.timestamp).total_seconds()) < 3600
            ):
                return True

        return False

    def handle_anomaly(self, anomaly: LearningAnomaly):
        """
        Handle a detected anomaly.

        Args:
            anomaly: The anomaly to handle
        """
        # Log the anomaly
        logger.warning(
            f"Learning anomaly detected: {anomaly.anomaly_type} ({anomaly.severity}) - {anomaly.description}"
        )

        # Save to file if alerts directory is configured
        if self.alerts_dir:
            self._save_anomaly_to_file(anomaly)

        # Call alert handlers
        for handler in self.alert_handlers:
            try:
                handler(anomaly)
            except Exception as e:
                logger.error(f"Error in alert handler: {e}")

    def _save_anomaly_to_file(self, anomaly: LearningAnomaly):
        """Save anomaly record to a file."""
        if not self.alerts_dir:
            return

        try:
            # Create filename based on anomaly ID
            filename = f"anomaly_{anomaly.id}.json"
            filepath = os.path.join(self.alerts_dir, filename)

            # Save as JSON
            with open(filepath, 'w') as f:
                json.dump(anomaly.to_dict(), f, indent=2)

            logger.info(f"Saved anomaly record to {filepath}")
        except Exception as e:
            logger.error(f"Error saving anomaly record: {e}")

    def _detect_parameter_oscillations(self) -> List[LearningAnomaly]:
        """
        Detect parameters that oscillate frequently between values.

        Returns:
            List[LearningAnomaly]: Detected oscillation anomalies
        """
        anomalies = []

        if not hasattr(self.metrics_collector, 'parameter_adaptations'):
            return []

        # Group adaptations by parameter
        param_adaptations = {}
        for adaptation in self.metrics_collector.parameter_adaptations:
            param_name = adaptation.get('parameter_name', '')
            if not param_name:
                continue

            if param_name not in param_adaptations:
                param_adaptations[param_name] = []

            param_adaptations[param_name].append(adaptation)

        # Check each parameter for oscillations
        for param_name, adaptations in param_adaptations.items():
            # Sort by timestamp
            sorted_adaptations = sorted(
                adaptations,
                key=lambda a: a.get('timestamp', datetime.datetime.min)
            )

            # Need at least 3 adaptations to detect oscillations
            if len(sorted_adaptations) < 3:
                continue

            # Focus on recent adaptations within window size
            recent_adaptations = sorted_adaptations[-self.alert_config['recent_window_size']:]

            # Count direction changes
            direction_changes = 0
            prev_direction = None

            for i in range(1, len(recent_adaptations)):
                prev_value = recent_adaptations[i-1].get('new_value')
                curr_value = recent_adaptations[i].get('new_value')

                if prev_value is None or curr_value is None:
                    continue

                # Skip if values are not numeric
                if not isinstance(prev_value, (int, float)) or not isinstance(curr_value, (int, float)):
                    continue

                # Determine direction of change
                if curr_value > prev_value:
                    curr_direction = 'increasing'
                elif curr_value < prev_value:
                    curr_direction = 'decreasing'
                else:
                    curr_direction = prev_direction  # No change

                # Count direction changes
                if prev_direction and curr_direction != prev_direction:
                    direction_changes += 1

                prev_direction = curr_direction

            # If enough direction changes, create anomaly
            if direction_changes >= self.alert_config['oscillation_threshold']:
                # Calculate severity based on frequency of changes
                change_frequency = direction_changes / len(recent_adaptations)

                if change_frequency >= 0.8:
                    severity = 'critical'
                elif change_frequency >= 0.5:
                    severity = 'warning'
                else:
                    severity = 'info'

                anomalies.append(LearningAnomaly(
                    anomaly_type='parameter_oscillation',
                    severity=severity,
                    description=f"Parameter '{param_name}' is oscillating frequently ({direction_changes} direction changes in {len(recent_adaptations)} adjustments)",
                    affected_parameters=[param_name],
                    metric_values={
                        'direction_changes': direction_changes,
                        'total_adaptations': len(recent_adaptations),
                        'change_frequency': change_frequency,
                        'recent_values': [a.get('new_value') for a in recent_adaptations[-5:]]
                    }
                ))

        return anomalies

    def _detect_performance_declines(self) -> List[LearningAnomaly]:
        """
        Detect declining performance trends in strategy effectiveness.

        Returns:
            List[LearningAnomaly]: Detected performance decline anomalies
        """
        anomalies = []

        if not hasattr(self.metrics_collector, 'strategy_effectiveness'):
            return []

        # Group effectiveness data by strategy and query type
        strategy_data = {}
        for entry in self.metrics_collector.strategy_effectiveness:
            strategy = entry.get('strategy', '')
            query_type = entry.get('query_type', '')

            if not strategy or not query_type:
                continue

            key = f"{strategy}_{query_type}"
            if key not in strategy_data:
                strategy_data[key] = []

            strategy_data[key].append(entry)

        # Check each strategy for performance declines
        for key, entries in strategy_data.items():
            # Need enough data points
            if len(entries) < self.alert_config['min_sample_size']:
                continue

            # Sort by timestamp
            sorted_entries = sorted(
                entries,
                key=lambda e: e.get('timestamp', datetime.datetime.min)
            )

            # Focus on recent entries within window size
            recent_entries = sorted_entries[-self.alert_config['recent_window_size']:]

            # Check if enough entries
            if len(recent_entries) < self.alert_config['min_sample_size']:
                continue

            # Calculate baseline (average of first half of recent entries)
            baseline_entries = recent_entries[:len(recent_entries)//2]
            baseline_success_rate = sum(e.get('success_rate', 0) for e in baseline_entries) / len(baseline_entries)
            baseline_latency = sum(e.get('mean_latency', 0) for e in baseline_entries) / len(baseline_entries)

            # Calculate current (average of second half of recent entries)
            current_entries = recent_entries[len(recent_entries)//2:]
            current_success_rate = sum(e.get('success_rate', 0) for e in current_entries) / len(current_entries)
            current_latency = sum(e.get('mean_latency', 0) for e in current_entries) / len(current_entries)

            # Calculate relative changes
            success_rate_change = (baseline_success_rate - current_success_rate) / max(0.001, baseline_success_rate)
            latency_change = (current_latency - baseline_latency) / max(0.001, baseline_latency)

            # Check for significant decline in success rate or increase in latency
            threshold = self.alert_config['performance_decline_threshold']

            if success_rate_change > threshold or latency_change > threshold:
                # Parse strategy and query type from key
                strategy, query_type = key.split('_', 1)

                # Determine which metric declined and by how much
                decline_details = []
                if success_rate_change > threshold:
                    decline_details.append(f"success rate decreased by {success_rate_change:.1%}")
                if latency_change > threshold:
                    decline_details.append(f"latency increased by {latency_change:.1%}")

                # Determine severity based on magnitude of decline
                severity = 'info'
                for level, level_threshold in self.alert_config['severity_thresholds'].items():
                    if success_rate_change > level_threshold or latency_change > level_threshold:
                        severity = level

                anomalies.append(LearningAnomaly(
                    anomaly_type='performance_decline',
                    severity=severity,
                    description=f"Performance decline for strategy '{strategy}' on '{query_type}' queries: {', '.join(decline_details)}",
                    affected_parameters=[strategy, query_type],
                    metric_values={
                        'baseline_success_rate': baseline_success_rate,
                        'current_success_rate': current_success_rate,
                        'baseline_latency': baseline_latency,
                        'current_latency': current_latency,
                        'success_rate_change': success_rate_change,
                        'latency_change': latency_change
                    }
                ))

        return anomalies

    def _detect_strategy_issues(self) -> List[LearningAnomaly]:
        """
        Detect issues with specific strategies.

        Returns:
            List[LearningAnomaly]: Detected strategy anomalies
        """
        anomalies = []

        if not hasattr(self.metrics_collector, 'strategy_effectiveness'):
            return []

        # Group effectiveness data by strategy
        strategy_data = {}
        for entry in self.metrics_collector.strategy_effectiveness:
            strategy = entry.get('strategy', '')

            if not strategy:
                continue

            if strategy not in strategy_data:
                strategy_data[strategy] = []

            strategy_data[strategy].append(entry)

        # Calculate overall metrics for each strategy
        strategy_metrics = {}
        for strategy, entries in strategy_data.items():
            # Calculate average success rate across all query types
            avg_success_rate = sum(e.get('success_rate', 0) for e in entries) / max(1, len(entries))
            avg_latency = sum(e.get('mean_latency', 0) for e in entries) / max(1, len(entries))

            strategy_metrics[strategy] = {
                'avg_success_rate': avg_success_rate,
                'avg_latency': avg_latency,
                'entry_count': len(entries)
            }

        # Compare strategies to find significant differences
        if len(strategy_metrics) >= 2:
            # Find best and worst strategies
            best_strategy = max(strategy_metrics, key=lambda s: strategy_metrics[s]['avg_success_rate'])
            worst_strategy = min(strategy_metrics, key=lambda s: strategy_metrics[s]['avg_success_rate'])

            # Calculate difference
            best_rate = strategy_metrics[best_strategy]['avg_success_rate']
            worst_rate = strategy_metrics[worst_strategy]['avg_success_rate']

            rate_difference = (best_rate - worst_rate) / max(0.001, best_rate)

            # If significant difference, create anomaly
            if rate_difference > self.alert_config['performance_decline_threshold']:
                # Determine severity based on magnitude of difference
                severity = 'info'
                for level, level_threshold in self.alert_config['severity_thresholds'].items():
                    if rate_difference > level_threshold:
                        severity = level

                anomalies.append(LearningAnomaly(
                    anomaly_type='strategy_performance_gap',
                    severity=severity,
                    description=f"Significant performance gap between strategies: '{best_strategy}' ({best_rate:.2f}) vs '{worst_strategy}' ({worst_rate:.2f}), {rate_difference:.1%} difference",
                    affected_parameters=[worst_strategy],
                    metric_values={
                        'best_strategy': best_strategy,
                        'best_rate': best_rate,
                        'worst_strategy': worst_strategy,
                        'worst_rate': worst_rate,
                        'rate_difference': rate_difference,
                        'strategy_metrics': strategy_metrics
                    }
                ))

        return anomalies

    def _detect_learning_stalls(self) -> List[LearningAnomaly]:
        """
        Detect stalls in the learning process.

        Returns:
            List[LearningAnomaly]: Detected learning stall anomalies
        """
        anomalies = []

        if not (hasattr(self.metrics_collector, 'learning_cycles') and
                hasattr(self.metrics_collector, 'parameter_adaptations')):
            return []

        # Get recent learning cycles
        if not self.metrics_collector.learning_cycles:
            return []

        # Sort cycles by timestamp
        sorted_cycles = sorted(
            self.metrics_collector.learning_cycles,
            key=lambda c: c.get('timestamp', datetime.datetime.min)
        )

        # Focus on recent cycles
        recent_cycles = sorted_cycles[-self.alert_config['recent_window_size']:]

        if not recent_cycles:
            return []

        # Calculate total queries analyzed and parameters adjusted
        total_analyzed = sum(c.get('analyzed_queries', 0) for c in recent_cycles)
        total_adjusted = sum(c.get('parameters_adjusted', 0) for c in recent_cycles)

        # Check if there are enough queries without parameter adjustments
        if (total_analyzed > self.alert_config['learning_stall_threshold'] and
            total_adjusted == 0):
            anomalies.append(LearningAnomaly(
                anomaly_type='learning_stall',
                severity='warning',
                description=f"Learning process appears stalled: {total_analyzed} queries analyzed without parameter adjustments",
                affected_parameters=[],
                metric_values={
                    'total_analyzed_queries': total_analyzed,
                    'total_parameters_adjusted': total_adjusted,
                    'cycles_considered': len(recent_cycles),
                    'patterns_identified': sum(c.get('patterns_identified', 0) for c in recent_cycles)
                }
            ))

        return anomalies


# Simple console handler for alerts
def console_alert_handler(anomaly: LearningAnomaly):
    """
    Simple handler that prints alerts to the console.

    Args:
        anomaly: The detected anomaly
    """
    severity_markers = {
        'info': '❗',
        'minor': '❗',
        'moderate': '⚠️',
        'warning': '⚠️',
        'major': '🔴',
        'critical': '🔴'
    }

    marker = severity_markers.get(anomaly.severity, '❗')

    # Print formatted alert
    print(f"\n{marker} LEARNING ALERT: {anomaly.anomaly_type.upper()} {marker}")
    print(f"Severity: {anomaly.severity}")
    print(f"Time: {anomaly.timestamp}")
    print(f"Description: {anomaly.description}")

    if anomaly.affected_parameters:
        print(f"Affected: {', '.join(anomaly.affected_parameters)}")

    print("-" * 50)


# Convenience function to create and setup alert system
def setup_learning_alerts(
    metrics_collector: Optional[OptimizerLearningMetricsCollector] = None,
    alert_config: Optional[Dict[str, Any]] = None,
    alerts_dir: Optional[str] = None,
    check_interval: int = 900,  # 15 minutes
    console_alerts: bool = True,
    additional_handlers: Optional[List[Callable]] = None
) -> LearningAlertSystem:
    """
    Set up a learning alert system.

    Args:
        metrics_collector: Collector with learning metrics
        alert_config: Configuration for alert thresholds
        alerts_dir: Directory to store alert records
        check_interval: Interval in seconds for checking anomalies
        console_alerts: Whether to print alerts to console
        additional_handlers: Additional alert handler functions

    Returns:
        LearningAlertSystem: Configured alert system
    """
    # Set up alert handlers
    handlers = []

    if console_alerts:
        handlers.append(console_alert_handler)

    if additional_handlers:
        handlers.extend(additional_handlers)

    # Create the alert system
    alert_system = LearningAlertSystem(
        metrics_collector=metrics_collector,
        alert_handlers=handlers,
        check_interval=check_interval,
        alerts_dir=alerts_dir,
        alert_config=alert_config
    )

    # Start monitoring
    alert_system.start_monitoring()

    return alert_system
