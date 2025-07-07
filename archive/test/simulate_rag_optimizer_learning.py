"""
Simulation script for the RAG query optimizer learning process.

This script demonstrates the integration between the RAG query optimizer
and the metrics visualization system, generating a comprehensive dashboard
with both performance and learning metrics.
"""

import os
import sys
import time
import json
import tempfile
import datetime
import argparse
import logging

# Add the parent directory to the path to ensure imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Try to import the required modules
try:
    from ipfs_datasets_py.rag.rag_query_visualization import (
        QueryMetricsCollector, OptimizerLearningMetricsCollector,
        RAGQueryDashboard, EnhancedQueryVisualizer
    )
    MODULES_AVAILABLE = True
except ImportError as e:
    logger.error(f"Required modules not available: {e}")
    MODULES_AVAILABLE = False


def simulate_rag_optimizer_learning(output_dir=None, num_cycles=3, queries_per_cycle=10, interactive=True):
    """
    Simulate the RAG query optimizer learning process for demonstration.

    This function demonstrates the integration between the RAG query optimizer
    and the metrics visualization system, generating a comprehensive dashboard
    with both performance and learning metrics.

    Args:
        output_dir (str): Directory for output files, uses tempdir if None
        num_cycles (int): Number of learning cycles to simulate
        queries_per_cycle (int): Number of queries per learning cycle
        interactive (bool): Whether to generate interactive visualizations

    Returns:
        str: Path to the generated dashboard HTML file
    """
    logger.info("Simulating RAG query optimizer learning process...")

    if not MODULES_AVAILABLE:
        logger.error("Required components not available")
        return None

    # Create temporary directory for outputs if none provided
    if output_dir is None:
        output_dir = tempfile.mkdtemp()
        logger.info(f"Created temporary directory: {output_dir}")
    elif not os.path.exists(output_dir):
        os.makedirs(output_dir)
        logger.info(f"Created output directory: {output_dir}")

    try:
        # Initialize metrics collectors
        query_metrics = QueryMetricsCollector()
        learning_metrics = OptimizerLearningMetricsCollector()

        # Simulate a learning process with multiple cycles
        for cycle in range(num_cycles):
            logger.info(f"Running learning cycle {cycle+1}...")
            cycle_start_time = time.time()
            analyzed_queries = 0

            # Simulate processing multiple queries in this cycle
            for i in range(queries_per_cycle):
                query_id = f"cycle{cycle+1}-query{i+1}"
                query_text = f"Test query {i+1} for cycle {cycle+1}"
                query_params = {
                    "query_text": query_text,
                    "max_depth": 2 + (cycle % 2),
                    "threshold": 0.6 + (cycle * 0.1)
                }

                # Record query start
                query_metrics.record_query_start(query_id, query_params)

                # Simulate vector search phase
                vector_search_time = 0.2 + (i * 0.02)
                time.sleep(0.01)  # Just to make the timing real
                query_metrics.record_phase_completion(query_id, "vector_search", vector_search_time)

                # Simulate graph traversal phase
                graph_time = 0.3 + (i * 0.03)
                time.sleep(0.01)  # Just to make the timing real
                query_metrics.record_phase_completion(query_id, "graph_traversal", graph_time)

                # Record query completion
                if i % 7 != 0:  # Make some queries successful
                    query_metrics.record_query_completion(
                        query_id,
                        results_count=5 + (i % 3),
                        quality_score=0.7 + (i * 0.02)
                    )
                else:  # And some failures
                    query_metrics.record_query_error(
                        query_id,
                        error="Simulated error for testing"
                    )

                analyzed_queries += 1

            # Record the learning cycle
            cycle_time = time.time() - cycle_start_time
            learning_metrics.record_learning_cycle(
                cycle_id=f"learning-cycle-{cycle+1}",
                analyzed_queries=analyzed_queries,
                patterns_identified=cycle + 2,
                parameters_adjusted={
                    "max_depth": 2 + cycle,
                    "threshold": 0.6 + (cycle * 0.1),
                    "search_strategy": "depth_first" if cycle % 2 == 0 else "breadth_first"
                },
                execution_time=cycle_time
            )

            # Record parameter adaptations
            learning_metrics.record_parameter_adaptation(
                parameter_name="max_depth",
                old_value=2 + (cycle-1 if cycle > 0 else 0),
                new_value=2 + cycle,
                adaptation_reason="performance_optimization",
                confidence=0.7 + (cycle * 0.1)
            )

            learning_metrics.record_parameter_adaptation(
                parameter_name="threshold",
                old_value=0.6 + ((cycle-1) * 0.1 if cycle > 0 else 0),
                new_value=0.6 + (cycle * 0.1),
                adaptation_reason="accuracy_improvement",
                confidence=0.8 + (cycle * 0.05)
            )

            # Record strategy effectiveness
            strategy = "depth_first" if cycle % 2 == 0 else "breadth_first"
            learning_metrics.record_strategy_effectiveness(
                strategy_name=strategy,
                query_type="complex",
                effectiveness_score=0.7 + (cycle * 0.05),
                execution_time=0.5 - (cycle * 0.1),  # Improving over time
                result_count=6 + cycle
            )

            # Record query patterns
            learning_metrics.record_query_pattern(
                pattern_id=f"pattern-{cycle+1}",
                pattern_type="semantic" if cycle % 2 == 0 else "lexical",
                matching_queries=4 + cycle,
                average_performance=0.5 + (cycle * 0.1),
                parameters={
                    "depth": 2 + cycle,
                    "strategy": strategy
                }
            )

            logger.info(f"Learning cycle {cycle+1} complete with {analyzed_queries} queries analyzed")
            time.sleep(0.5)  # Space out the cycles

        # Generate individual visualizations
        logger.info("Generating individual visualizations...")

        # Learning cycles visualization
        learning_cycles_file = os.path.join(output_dir, "learning_cycles.png")
        learning_metrics.visualize_learning_cycles(output_file=learning_cycles_file)

        # Parameter adaptations visualization
        param_adapt_file = os.path.join(output_dir, "parameter_adaptations.png")
        learning_metrics.visualize_parameter_adaptations(output_file=param_adapt_file)

        # Strategy effectiveness visualization
        strategy_file = os.path.join(output_dir, "strategy_effectiveness.png")
        learning_metrics.visualize_strategy_effectiveness(output_file=strategy_file)

        # Query patterns visualization
        patterns_file = os.path.join(output_dir, "query_patterns.png")
        learning_metrics.visualize_query_patterns(output_file=patterns_file)

        # Learning performance visualization
        performance_file = os.path.join(output_dir, "learning_performance.png")
        learning_metrics.visualize_learning_performance(output_file=performance_file)

        # Generate interactive dashboard
        logger.info("Generating integrated dashboard...")
        dashboard = RAGQueryDashboard(
            metrics_collector=query_metrics,
            visualizer=EnhancedQueryVisualizer(query_metrics)
        )

        # Generate both interactive and static dashboards
        for dash_type in ["interactive", "static"]:
            is_interactive = dash_type == "interactive"
            if not interactive and is_interactive:
                continue

            dashboard_file = os.path.join(output_dir, f"rag_optimizer_{dash_type}_dashboard.html")
            dashboard.generate_integrated_dashboard(
                output_file=dashboard_file,
                learning_metrics_collector=learning_metrics,
                title=f"RAG Query Optimizer Learning Dashboard ({dash_type})",
                include_performance=True,
                include_learning_metrics=True,
                interactive=is_interactive,
                theme="light"
            )
            logger.info(f"Generated {dash_type} dashboard at: {dashboard_file}")

        # Also save the raw metrics data for future reference
        metrics_file = os.path.join(output_dir, "learning_metrics.json")
        with open(metrics_file, 'w') as f:
            f.write(learning_metrics.to_json())
        logger.info(f"Saved raw metrics data to: {metrics_file}")

        # Return the path to the main dashboard
        main_dashboard = os.path.join(output_dir,
                                    "rag_optimizer_interactive_dashboard.html" if interactive
                                    else "rag_optimizer_static_dashboard.html")
        return main_dashboard

    except Exception as e:
        logger.error(f"Error in simulation: {str(e)}", exc_info=True)
        return None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Simulate RAG optimizer learning process')
    parser.add_argument('--output-dir', '-o', type=str, default=None,
                      help='Directory for output files (default: temporary directory)')
    parser.add_argument('--cycles', '-c', type=int, default=3,
                      help='Number of learning cycles to simulate (default: 3)')
    parser.add_argument('--queries', '-q', type=int, default=10,
                      help='Number of queries per learning cycle (default: 10)')
    parser.add_argument('--static', '-s', action='store_true',
                      help='Generate static visualizations only (no interactive)')
    args = parser.parse_args()

    dashboard_file = simulate_rag_optimizer_learning(
        output_dir=args.output_dir,
        num_cycles=args.cycles,
        queries_per_cycle=args.queries,
        interactive=not args.static
    )

    if dashboard_file:
        print(f"\nSimulation complete! Dashboard available at: {dashboard_file}")
        print(f"To view, open this file in a web browser.")
    else:
        print("\nSimulation failed. Check the logs for details.")
        sys.exit(1)
