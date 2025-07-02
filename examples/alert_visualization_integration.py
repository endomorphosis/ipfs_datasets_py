#!/usr/bin/env python3
"""
Alert and Visualization Integration Example

This script demonstrates how to integrate the optimizer alert system with
the visualization system. It creates a simulated optimizer with deliberate
anomalies and shows how alerts are detected and visualized.
"""

import os
import sys
import time
import random
import threading
import argparse
from datetime import datetime, timedelta
import json

# Add parent directory to path to allow importing from project
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from ipfs_datasets_py.optimizers.optimizer_alert_system import LearningAlertSystem, LearningAnomaly, console_alert_handler
from ipfs_datasets_py.optimizer_visualization_integration import LiveOptimizerVisualization


class SimulatedOptimizer:
    """
    Simulates a RAG Query Optimizer with controlled anomalies for demonstration.

    This class mimics the behavior of a real optimizer but allows injection of
    deliberate anomalies to demonstrate the alert and visualization systems.
    """

    def __init__(self):
        """Initialize the simulated optimizer."""
        self.current_cycle = 0
        self.parameters = {
            "max_vector_results": 10,
            "min_similarity": 0.7,
            "traversal_depth": 2,
            "vector_weight": 0.6,
            "graph_weight": 0.4
        }
        self.metrics = {
            "query_count": 0,
            "successful_queries": 0,
            "failed_queries": 0,
            "avg_latency": 100,  # milliseconds
            "parameter_changes": {},
            "strategy_effectiveness": {
                "vector_first": 0.8,
                "graph_first": 0.7,
                "hybrid": 0.9
            }
        }
        self.learning_enabled = True
        self.last_update = datetime.now()
        self.learning_history = []
        self.lock = threading.RLock()

    def simulate_query(self, anomaly=None):
        """
        Simulate processing a query, optionally with a specific anomaly.

        Args:
            anomaly (str, optional): Type of anomaly to simulate:
                - "oscillation": Make parameters oscillate
                - "performance_decline": Gradually decrease success rate
                - "strategy_issue": Make a strategy ineffective
                - "stalled": Stop learning despite changes
        """
        with self.lock:
            self.metrics["query_count"] += 1

            # Simulate success/failure
            success = random.random() < 0.9  # 90% success rate by default
            if anomaly == "performance_decline" and self.metrics["query_count"] % 5 == 0:
                # Force failure every 5th query for this anomaly
                success = False

            if success:
                self.metrics["successful_queries"] += 1
            else:
                self.metrics["failed_queries"] += 1

            # Simulate latency (80-120ms normally)
            latency = random.uniform(80, 120)
            if anomaly == "performance_decline":
                # Increase latency by 5ms per query for this anomaly
                latency += self.metrics["query_count"] * 5

            # Update average latency
            old_avg = self.metrics["avg_latency"]
            query_count = self.metrics["query_count"]
            self.metrics["avg_latency"] = (old_avg * (query_count - 1) + latency) / query_count

            # Simulate strategy effectiveness changes
            if anomaly == "strategy_issue" and self.metrics["query_count"] % 3 == 0:
                # Decrease effectiveness of vector_first strategy
                self.metrics["strategy_effectiveness"]["vector_first"] = max(
                    0.1, self.metrics["strategy_effectiveness"]["vector_first"] - 0.05
                )

            # Every 10 queries, simulate a learning cycle
            if self.metrics["query_count"] % 10 == 0 and self.learning_enabled:
                self._simulate_learning_cycle(anomaly)

    def _simulate_learning_cycle(self, anomaly=None):
        """
        Simulate a learning cycle with parameter adaptations.

        Args:
            anomaly (str, optional): Type of anomaly to simulate
        """
        self.current_cycle += 1

        # Record old parameters
        old_params = self.parameters.copy()

        # Simulate parameter changes based on anomaly type
        if anomaly == "oscillation":
            # Oscillate max_vector_results between 5 and 15
            if self.parameters["max_vector_results"] == 10:
                self.parameters["max_vector_results"] = 5 if self.current_cycle % 2 == 0 else 15
            else:
                self.parameters["max_vector_results"] = 10

            # Oscillate min_similarity between 0.6 and 0.8
            if self.parameters["min_similarity"] == 0.7:
                self.parameters["min_similarity"] = 0.6 if self.current_cycle % 2 == 0 else 0.8
            else:
                self.parameters["min_similarity"] = 0.7

        elif anomaly == "stalled":
            # Don't change any parameters
            pass

        else:
            # Normal learning: make small adjustments
            self.parameters["max_vector_results"] += random.choice([-1, 0, 1])
            self.parameters["min_similarity"] += random.choice([-0.05, 0, 0.05])
            self.parameters["traversal_depth"] += random.choice([-1, 0, 1])

            # Keep parameters in reasonable ranges
            self.parameters["max_vector_results"] = max(3, min(20, self.parameters["max_vector_results"]))
            self.parameters["min_similarity"] = max(0.3, min(0.9, self.parameters["min_similarity"]))
            self.parameters["traversal_depth"] = max(1, min(4, self.parameters["traversal_depth"]))

        # Record parameter changes
        changes = {}
        for param, new_value in self.parameters.items():
            old_value = old_params[param]
            if new_value != old_value:
                changes[param] = {
                    "old": old_value,
                    "new": new_value,
                    "change": new_value - old_value
                }

        # Update metrics
        self.metrics["parameter_changes"] = changes

        # Record learning history
        self.learning_history.append({
            "cycle": self.current_cycle,
            "timestamp": datetime.now(),
            "parameters": self.parameters.copy(),
            "changes": changes,
            "metrics": {
                "success_rate": self.metrics["successful_queries"] / max(1, self.metrics["query_count"]),
                "avg_latency": self.metrics["avg_latency"],
                "strategy_effectiveness": self.metrics["strategy_effectiveness"].copy()
            }
        })

        self.last_update = datetime.now()

    def get_learning_metrics(self):
        """
        Get current learning metrics for visualization and alerting.

        Returns:
            dict: Current metrics and learning history
        """
        with self.lock:
            return {
                "current_cycle": self.current_cycle,
                "current_parameters": self.parameters.copy(),
                "metrics": self.metrics.copy(),
                "learning_history": self.learning_history.copy(),
                "learning_enabled": self.learning_enabled,
                "last_update": self.last_update
            }


class VisualizationAlertHandler:
    """Custom alert handler that integrates with the visualization system."""

    def __init__(self, visualizer):
        """
        Initialize the alert handler.

        Args:
            visualizer (LiveOptimizerVisualization): Visualization system
        """
        self.visualizer = visualizer
        self.alerts = []

    def __call__(self, anomaly: LearningAnomaly):
        """
        Handle an anomaly by adding it to the visualization.

        Args:
            anomaly: The detected anomaly
        """
        self.alerts.append(anomaly)

        # Instead of trying to add markers (which the existing visualization system
        # doesn't support), we'll just record the alerts and save them separately

        # Print debug info
        print(f"[VISUALIZATION] Recorded alert for {anomaly.anomaly_type} at {anomaly.timestamp}")


def run_simulation(duration=300, anomaly_schedule=None, output_dir="./visualizations"):
    """
    Run the integrated alert and visualization simulation.

    Args:
        duration (int): Duration in seconds to run the simulation
        anomaly_schedule (dict, optional): Schedule of anomalies to inject
            Format: {time_seconds: anomaly_type}
        output_dir (str): Directory to save visualization outputs
    """
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    # Create simulated optimizer
    optimizer = SimulatedOptimizer()

    # Set up visualization system
    visualizer = LiveOptimizerVisualization(
        optimizer=None,  # We'll use metrics_source function directly
        metrics_dir=output_dir,
        visualization_dir=output_dir,
        visualization_interval=5  # Update every 5 seconds
    )

    # Add a method to directly pass metrics from our simulator
    def update_visualizer_with_metrics():
        """Update visualizer with metrics from our simulator."""
        metrics = optimizer.get_learning_metrics()
        visualizer.last_metrics = metrics

    # Set up custom alert handler
    custom_handler = VisualizationAlertHandler(visualizer)

    # Create metrics collector adapter for the simulator
    class SimulatedMetricsCollector:
        def __init__(self, optimizer):
            self.optimizer = optimizer
            self.learning_cycles = []
            self.parameter_adaptations = []
            self.strategy_effectiveness = []
            self.update_metrics()

            # Add some sample data to trigger anomalies for testing
            self._add_sample_oscillations()

        def update_metrics(self):
            metrics = self.optimizer.get_learning_metrics()

            # Convert learning history to the format expected by LearningAlertSystem
            self.learning_cycles = []
            self.parameter_adaptations = []
            self.strategy_effectiveness = []

            for cycle in metrics.get('learning_history', []):
                # Add learning cycle data
                self.learning_cycles.append({
                    'cycle_id': f"cycle_{cycle.get('cycle', 0)}",
                    'timestamp': cycle.get('timestamp', datetime.now()),
                    'analyzed_queries': metrics.get('metrics', {}).get('query_count', 0),
                    'parameters_adjusted': len(cycle.get('changes', {})),
                    'patterns_identified': random.randint(1, 3),  # Simulated value
                    'execution_time': random.uniform(0.5, 3.0)  # Simulated value
                })

                # Add parameter adaptations
                for param_name, change_data in cycle.get('changes', {}).items():
                    self.parameter_adaptations.append({
                        'parameter_name': param_name,
                        'old_value': change_data.get('old'),
                        'new_value': change_data.get('new'),
                        'reason': f"Learning cycle {cycle.get('cycle', 0)}",
                        'timestamp': cycle.get('timestamp', datetime.now())
                    })

                # Add strategy effectiveness data
                cycle_metrics = cycle.get('metrics', {})
                if 'strategy_effectiveness' in cycle_metrics:
                    for strategy, effectiveness in cycle_metrics['strategy_effectiveness'].items():
                        self.strategy_effectiveness.append({
                            'strategy': strategy,
                            'query_type': 'general',  # Simulated value
                            'success_rate': effectiveness,
                            'mean_latency': cycle_metrics.get('avg_latency', 100),
                            'sample_size': random.randint(10, 30),  # Simulated value
                            'timestamp': cycle.get('timestamp', datetime.now())
                        })

        def _add_sample_oscillations(self):
            """Add sample data to trigger anomalies for testing."""
            # Add oscillating parameter adaptations
            param_name = "max_vector_results"
            base_time = datetime.now() - timedelta(minutes=20)

            # Create an oscillating pattern: 10 -> 5 -> 10 -> 15 -> 10 -> 5
            values = [10, 5, 10, 15, 10, 5]

            for i in range(len(values) - 1):
                self.parameter_adaptations.append({
                    'parameter_name': param_name,
                    'old_value': values[i],
                    'new_value': values[i+1],
                    'reason': f"Testing oscillation {i}",
                    'timestamp': base_time + timedelta(minutes=i*2)
                })

            # Add declining strategy effectiveness
            strategy = "vector_first"
            base_effectiveness = 0.9

            for i in range(5):
                # Gradually decreasing effectiveness
                current_effectiveness = base_effectiveness - (i * 0.1)

                self.strategy_effectiveness.append({
                    'strategy': strategy,
                    'query_type': 'general',
                    'success_rate': current_effectiveness,
                    'mean_latency': 100 + (i * 20),  # Increasing latency
                    'sample_size': 20,
                    'timestamp': base_time + timedelta(minutes=i*3)
                })

    # Create metrics collector for the optimizer
    metrics_collector = SimulatedMetricsCollector(optimizer)

    # Manually create some anomalies for testing since our simulation is too short
    # to trigger the detection mechanisms
    oscillation_anomaly = LearningAnomaly(
        anomaly_type='parameter_oscillation',
        severity='warning',
        description=f"Parameter 'max_vector_results' is oscillating frequently (4 direction changes in 5 adjustments)",
        affected_parameters=['max_vector_results'],
        timestamp=datetime.now() - timedelta(minutes=5),
        metric_values={
            'direction_changes': 4,
            'total_adaptations': 5,
            'change_frequency': 0.8,
            'recent_values': [10, 5, 10, 15, 10]
        }
    )

    performance_anomaly = LearningAnomaly(
        anomaly_type='performance_decline',
        severity='critical',
        description=f"Performance decline for strategy 'vector_first': success rate decreased by 35.0%, latency increased by 42.0%",
        affected_parameters=['vector_first'],
        timestamp=datetime.now() - timedelta(minutes=3),
        metric_values={
            'baseline_success_rate': 0.85,
            'current_success_rate': 0.55,
            'success_rate_change': 0.35,
            'baseline_latency': 100,
            'current_latency': 142
        }
    )

    stall_anomaly = LearningAnomaly(
        anomaly_type='learning_stall',
        severity='info',
        description=f"Learning process appears stalled: 25 queries analyzed without parameter adjustments",
        affected_parameters=[],
        timestamp=datetime.now() - timedelta(minutes=1),
        metric_values={
            'total_analyzed_queries': 25,
            'total_parameters_adjusted': 0,
            'cycles_considered': 3
        }
    )

    # Set up alert system with custom handler
    alert_system = LearningAlertSystem(
        metrics_collector=metrics_collector,
        alert_handlers=[custom_handler, console_alert_handler],
        check_interval=5,  # Check every 5 seconds
        alerts_dir=output_dir
    )

    # Default anomaly schedule if none provided
    if anomaly_schedule is None:
        anomaly_schedule = {
            60: "oscillation",       # Start parameter oscillation at 1 minute
            120: "performance_decline",  # Start performance decline at 2 minutes
            180: "strategy_issue",   # Start strategy issues at 3 minutes
            240: "stalled"           # Start stalled learning at 4 minutes
        }

    # Start alert system
    alert_system.start_monitoring()

    # Manually process the test anomalies we created
    custom_handler(oscillation_anomaly)
    custom_handler(performance_anomaly)
    custom_handler(stall_anomaly)

    # Also process through the console handler for demo
    console_alert_handler(oscillation_anomaly)
    console_alert_handler(performance_anomaly)
    console_alert_handler(stall_anomaly)

    # Start auto-update for visualizer
    visualizer.start_auto_update()

    try:
        print(f"Starting simulation for {duration} seconds...")
        start_time = time.time()
        current_anomaly = None
        update_counter = 0

        while time.time() - start_time < duration:
            # Check if we need to change the anomaly
            elapsed = int(time.time() - start_time)
            for schedule_time, anomaly_type in list(anomaly_schedule.items()):
                if elapsed >= schedule_time and schedule_time >= 0:
                    current_anomaly = anomaly_type
                    print(f"[{elapsed}s] Injecting anomaly: {anomaly_type}")
                    # Mark this anomaly as processed
                    anomaly_schedule[schedule_time] = -1

            # Simulate a query with the current anomaly
            optimizer.simulate_query(current_anomaly)

            # Update metrics collector every 5 queries
            update_counter += 1
            if update_counter % 5 == 0:
                metrics_collector.update_metrics()
                update_visualizer_with_metrics()

            # Sleep for a random interval (0.5-1.5s) to simulate real query patterns
            time.sleep(random.uniform(0.5, 1.5))

    except KeyboardInterrupt:
        print("\nSimulation interrupted by user.")

    finally:
        # Stop alert system and visualization
        alert_system.stop_monitoring()
        visualizer.stop_auto_update()

        # Generate final dashboard with all data and alerts
        final_dashboard_path = os.path.join(output_dir, "final_dashboard.html")

        # Since visualizer doesn't have a parameter for alerts, let's save them separately
        alerts_path = os.path.join(output_dir, "alerts.json")
        with open(alerts_path, 'w') as f:
            alert_data = []
            for anomaly in custom_handler.alerts:
                alert_data.append({
                    "timestamp": anomaly.timestamp.isoformat(),
                    "type": anomaly.anomaly_type,
                    "message": anomaly.description,
                    "severity": anomaly.severity,
                    "data": anomaly.metric_values
                })
            json.dump(alert_data, f, indent=2)

        # Update metrics for visualization one last time
        update_visualizer_with_metrics()

        # We'll create a simple HTML dashboard instead of using the existing visualizer
        # which has parameter compatibility issues
        dashboard_path = os.path.join(output_dir, "integrated_dashboard.html")
        with open(dashboard_path, 'w') as f:
            f.write(f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>RAG Query Optimizer Monitoring Dashboard</title>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 20px; }}
                    h1, h2 {{ color: #333; }}
                    .alert {{
                        padding: 10px;
                        margin: 10px 0;
                        border-radius: 5px;
                    }}
                    .oscillation {{ background-color: #fff3cd; }}
                    .performance {{ background-color: #f8d7da; }}
                    .strategy_issue {{ background-color: #d4edda; }}
                    .stalled {{ background-color: #d1ecf1; }}
                    .controls {{ margin: 20px 0; }}
                    .visualizations {{ display: flex; flex-wrap: wrap; }}
                    .viz-container {{ margin: 10px; max-width: 500px; }}
                </style>
            </head>
            <body>
                <h1>RAG Query Optimizer Monitoring Dashboard</h1>
                <p>Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>

                <h2>Alert Summary</h2>
                <div class="alerts">
            """)

            # Add alerts to dashboard
            for anomaly in custom_handler.alerts:
                alert_class = anomaly.anomaly_type.lower()
                f.write(f"""
                    <div class="alert {alert_class}">
                        <strong>{anomaly.severity.upper()} - {anomaly.anomaly_type}:</strong>
                        {anomaly.description} <br>
                        <small>Detected at: {anomaly.timestamp}</small>
                    </div>
                """)

            # Close the HTML structure
            f.write("""
                </div>

                <h2>Visualizations</h2>
                <p>Visualizations can be found in the output directory.</p>

                <h2>Raw Metrics</h2>
                <p>Detailed metrics data is available in the metrics files.</p>
            </body>
            </html>
            """)

        dashboard_result = {'dashboard': dashboard_path}

        print(f"\nSimulation completed.")
        print(f"Alert data saved to: {alerts_path}")

        if 'dashboard' in dashboard_result:
            print(f"Final dashboard saved to: {dashboard_result['dashboard']}")
        else:
            print(f"Visualizations saved to: {output_dir}")


def main():
    """Main entry point with command-line argument parsing."""
    parser = argparse.ArgumentParser(description="Run an integrated alert and visualization demo")

    parser.add_argument(
        "--duration", type=int, default=300,
        help="Duration of the simulation in seconds (default: 300)"
    )

    parser.add_argument(
        "--output-dir", type=str, default="./visualizations",
        help="Directory to save visualization outputs (default: ./visualizations)"
    )

    parser.add_argument(
        "--anomaly-free", action="store_true",
        help="Run the simulation without injecting anomalies"
    )

    args = parser.parse_args()

    # Use custom anomaly schedule if anomaly-free option is set
    anomaly_schedule = None if not args.anomaly_free else {}

    run_simulation(
        duration=args.duration,
        anomaly_schedule=anomaly_schedule,
        output_dir=args.output_dir
    )


if __name__ == "__main__":
    main()
