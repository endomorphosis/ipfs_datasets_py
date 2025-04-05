#!/usr/bin/env python3
"""
Unified Dashboard Example

This example demonstrates how to set up and use the unified monitoring dashboard
to integrate learning metrics visualization, alert notifications, performance 
statistics, and system health indicators.
"""

import os
import sys
import time
import random
import logging
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import components
from ipfs_datasets_py.unified_monitoring_dashboard import UnifiedDashboard, create_unified_dashboard
from ipfs_datasets_py.audit.audit_visualization import OptimizerLearningMetricsVisualizer
from ipfs_datasets_py.optimizer_alert_system import LearningAlertSystem, LearningAnomaly, setup_learning_alerts
from ipfs_datasets_py.monitoring import MetricsCollector

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SampleMetricsCollector:
    """
    Sample metrics collector that generates simulated metrics for demonstration.
    
    In a real application, this would be replaced with a real metrics collector
    that gathers data from the optimizer and other system components.
    """
    
    def __init__(self):
        """Initialize the sample metrics collector."""
        self.start_time = datetime.now()
        self.last_update = self.start_time
        self.query_count = 0
        self.success_count = 0
        self.learning_enabled = True
        self.learning_cycles = 0
        
        # Performance metrics
        self.latencies = []
        self.success_rates = []
        
        # Resources
        self.cpu_samples = []
        self.memory_samples = []
        
        # Query types
        self.query_types = {
            'factual': {'count': 0, 'success': 0, 'latencies': []},
            'complex': {'count': 0, 'success': 0, 'latencies': []},
            'exploratory': {'count': 0, 'success': 0, 'latencies': []}
        }
        
        # Strategies
        self.strategies = {
            'vector_first': {'success': 0, 'count': 0, 'latencies': []},
            'graph_first': {'success': 0, 'count': 0, 'latencies': []},
            'balanced': {'success': 0, 'count': 0, 'latencies': []}
        }
        
        # Parameter adaptations
        self.parameter_adaptations = {}
        
        # Generate some initial data
        self._generate_sample_data()
    
    def _generate_sample_data(self):
        """Generate sample data for demonstration."""
        # Simulate queries over time
        elapsed_seconds = (datetime.now() - self.start_time).total_seconds()
        new_queries = int(elapsed_seconds / 2)  # 1 query every 2 seconds
        
        if new_queries > self.query_count:
            # Add new queries
            for i in range(self.query_count, new_queries):
                # Add overall query
                self.query_count += 1
                success = random.random() < 0.85  # 85% success rate
                if success:
                    self.success_count += 1
                
                latency = random.normalvariate(150, 50)  # Mean 150ms, stddev 50ms
                self.latencies.append(latency)
                
                # Add query type
                query_type = random.choice(list(self.query_types.keys()))
                self.query_types[query_type]['count'] += 1
                if success:
                    self.query_types[query_type]['success'] += 1
                self.query_types[query_type]['latencies'].append(latency)
                
                # Add strategy
                strategy = random.choice(list(self.strategies.keys()))
                self.strategies[strategy]['count'] += 1
                if success:
                    self.strategies[strategy]['success'] += 1
                self.strategies[strategy]['latencies'].append(latency)
            
            # Add resource samples
            self.cpu_samples.append(random.uniform(10, 40))
            self.memory_samples.append(random.uniform(200, 600))
            
            # Simulate learning cycles
            new_cycles = int(elapsed_seconds / 60)  # 1 cycle every minute
            if new_cycles > self.learning_cycles:
                for i in range(self.learning_cycles, new_cycles):
                    self.learning_cycles += 1
                    
                    # Add parameter adaptation
                    param_name = random.choice(['max_vector_results', 'min_similarity', 'traversal_depth'])
                    old_value = random.uniform(0.2, 0.8) if 'similarity' in param_name else random.randint(3, 15)
                    change = random.uniform(-0.1, 0.1) if 'similarity' in param_name else random.randint(-2, 2)
                    new_value = old_value + change
                    
                    self.parameter_adaptations[f"{param_name}_{self.learning_cycles}"] = {
                        'parameter_name': param_name,
                        'old_value': old_value,
                        'new_value': new_value,
                        'timestamp': datetime.now() - timedelta(seconds=random.randint(0, 300))
                    }
        
        self.last_update = datetime.now()
    
    def get_metrics_snapshot(self):
        """
        Get a snapshot of current metrics.
        
        Returns:
            dict: Current metrics data
        """
        # Update sample data
        self._generate_sample_data()
        
        # Calculate metrics
        avg_latency = sum(self.latencies) / max(1, len(self.latencies))
        success_rate = self.success_count / max(1, self.query_count)
        
        # Sort latencies for percentiles
        sorted_latencies = sorted(self.latencies)
        p95_index = int(len(sorted_latencies) * 0.95)
        p99_index = int(len(sorted_latencies) * 0.99)
        p95_latency = sorted_latencies[p95_index] if len(sorted_latencies) > p95_index else avg_latency
        p99_latency = sorted_latencies[p99_index] if len(sorted_latencies) > p99_index else avg_latency
        
        # Resource metrics
        avg_cpu = sum(self.cpu_samples) / max(1, len(self.cpu_samples))
        avg_memory = sum(self.memory_samples) / max(1, len(self.memory_samples))
        
        # Query type metrics
        query_type_metrics = {}
        for query_type, data in self.query_types.items():
            success_rate = data['success'] / max(1, data['count'])
            avg_latency = sum(data['latencies']) / max(1, len(data['latencies']))
            query_type_metrics[query_type] = {
                'count': data['count'],
                'success_rate': success_rate,
                'avg_latency': avg_latency
            }
        
        # Strategy metrics
        strategy_metrics = {}
        for strategy, data in self.strategies.items():
            success_rate = data['success'] / max(1, data['count'])
            avg_latency = sum(data['latencies']) / max(1, len(data['latencies']))
            
            # Group by query type (simplifying to just 'general' for this example)
            if strategy not in strategy_metrics:
                strategy_metrics[strategy] = {}
            
            strategy_metrics[strategy]['general'] = {
                'success_rate': success_rate,
                'mean_latency': avg_latency,
                'sample_size': data['count']
            }
        
        # Learning metrics
        learning_metrics = {
            'learning_cycles': {
                'total_cycles': self.learning_cycles,
                'total_analyzed_queries': self.query_count,
                'total_patterns': int(self.learning_cycles * 1.5),  # Simulated
                'total_adjustments': len(self.parameter_adaptations)
            },
            'parameter_adaptations': self.parameter_adaptations,
            'strategy_effectiveness': strategy_metrics
        }
        
        # Return formatted metrics
        return {
            'performance': {
                'total_queries': self.query_count,
                'success_rate': success_rate,
                'avg_latency': avg_latency,
                'p95_latency': p95_latency,
                'p99_latency': p99_latency,
                'query_types': query_type_metrics
            },
            'resources': {
                'cpu_usage': avg_cpu,
                'memory_usage': avg_memory
            },
            'learning_status': {
                'enabled': self.learning_enabled,
                'last_cycle': datetime.now() - timedelta(seconds=random.randint(0, 300))
            },
            'learning_metrics': learning_metrics,
            'updated_at': self.last_update.isoformat()
        }


class SampleLearningVisualizer:
    """Sample learning visualizer for demonstration."""
    
    def __init__(self, output_dir):
        """
        Initialize the visualizer.
        
        Args:
            output_dir: Directory to save visualizations
        """
        self.output_dir = output_dir
        self.last_update = datetime.now()
    
    def update_visualizations(self, create_dashboard=False):
        """
        Update visualizations.
        
        Args:
            create_dashboard: Whether to create a dashboard
            
        Returns:
            dict: Paths to visualization outputs
        """
        # In a real implementation, this would call the actual visualizer
        # For this demo, we'll just create some sample files
        
        # Create timestamp for filenames
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Create visualization directories
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir, exist_ok=True)
            
        cycles_path = os.path.join(self.output_dir, f"learning_cycles_{timestamp}.png")
        params_path = os.path.join(self.output_dir, f"parameter_adaptations_{timestamp}.png")
        strategy_path = os.path.join(self.output_dir, f"strategy_effectiveness_{timestamp}.png")
        
        # Create empty files for demonstration
        for path in [cycles_path, params_path, strategy_path]:
            with open(path, 'w') as f:
                f.write("# Sample visualization file")
        
        # Return paths to visualization files
        return {
            'learning_cycles_static': cycles_path,
            'parameter_adaptations_static': params_path,
            'strategy_effectiveness_static': strategy_path
        }


def run_demo(dashboard_dir, duration=300):
    """
    Run the unified dashboard demo.
    
    Args:
        dashboard_dir: Directory to store dashboard files
        duration: Duration in seconds to run the demo
    """
    # Create output directories
    os.makedirs(dashboard_dir, exist_ok=True)
    visualizations_dir = os.path.join(dashboard_dir, "visualizations")
    os.makedirs(visualizations_dir, exist_ok=True)
    
    # Create components
    metrics_collector = SampleMetricsCollector()
    learning_visualizer = SampleLearningVisualizer(visualizations_dir)
    
    # Create unified dashboard
    dashboard = create_unified_dashboard(
        dashboard_dir=dashboard_dir,
        dashboard_title="RAG Optimizer Unified Dashboard",
        refresh_interval=30,  # 30 seconds for demo
        auto_refresh=True
    )
    
    # Register components
    dashboard.register_metrics_collector(metrics_collector)
    dashboard.register_learning_visualizer(learning_visualizer)
    
    # Create some sample alerts
    alert_types = [
        {
            'type': 'parameter_oscillation',
            'severity': 'warning',
            'description': "Parameter 'max_vector_results' is oscillating frequently (4 direction changes in 5 adjustments)",
            'parameters': ['max_vector_results'],
        },
        {
            'type': 'performance_decline',
            'severity': 'critical',
            'description': "Performance decline for strategy 'vector_first': success rate decreased by 35%, latency increased by 42%",
            'parameters': ['vector_first'],
        },
        {
            'type': 'learning_stall',
            'severity': 'info',
            'description': "Learning process appears stalled: 25 queries analyzed without parameter adjustments",
            'parameters': [],
        }
    ]
    
    # Add initial alerts
    for i, alert_info in enumerate(alert_types):
        anomaly = LearningAnomaly(
            anomaly_type=alert_info['type'],
            severity=alert_info['severity'],
            description=alert_info['description'],
            affected_parameters=alert_info['parameters'],
            timestamp=datetime.now() - timedelta(minutes=i*10)
        )
        dashboard._alert_handler(anomaly)
    
    # Initial dashboard update
    dashboard.update_dashboard()
    
    print(f"Dashboard created at: {dashboard.dashboard_path}")
    print(f"Running demo for {duration} seconds...")
    
    # Periodically add new alerts during the demo
    start_time = time.time()
    
    try:
        while time.time() - start_time < duration:
            # Sleep for a bit
            time.sleep(10)
            
            # Add a random alert occasionally
            if random.random() < 0.3:  # 30% chance each loop
                alert_info = random.choice(alert_types)
                anomaly = LearningAnomaly(
                    anomaly_type=alert_info['type'],
                    severity=alert_info['severity'],
                    description=alert_info['description'],
                    affected_parameters=alert_info['parameters'],
                    timestamp=datetime.now()
                )
                dashboard._alert_handler(anomaly)
                print(f"Added new alert: {alert_info['type']}")
    
    except KeyboardInterrupt:
        print("\nDemo interrupted by user.")
    
    finally:
        # Stop auto-refresh
        dashboard.stop_auto_refresh()
        print("\nDemo completed. Dashboard is available at:")
        print(f"file://{os.path.abspath(dashboard.dashboard_path)}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Run a unified dashboard demo")
    parser.add_argument("--dir", default="./unified_dashboard_demo", help="Directory to store dashboard files")
    parser.add_argument("--duration", type=int, default=300, help="Duration in seconds to run the demo")
    
    args = parser.parse_args()
    
    run_demo(args.dir, args.duration)