"""
RAG Query Optimizer Live Visualization Demo

This script demonstrates the live visualization of RAG query optimizer learning metrics.
It creates a simulated optimizer with learning data and visualizes the metrics.
"""

import os
import sys
import time
import argparse
import logging
import tempfile

# Add the parent directory to the path
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

# Import the necessary modules
from ipfs_datasets_py.optimizers.optimizer_visualization_integration import (
    LiveOptimizerVisualization,
    setup_optimizer_visualization
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='RAG Query Optimizer Visualization Demo')
    parser.add_argument(
        '--output-dir',
        type=str,
        default=None,
        help='Directory for output visualizations (default: temp directory)'
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=300,  # 5 minutes
        help='Update interval in seconds for visualizations (default: 300)'
    )
    parser.add_argument(
        '--cycles',
        type=int,
        default=15,
        help='Number of learning cycles to simulate (default: 15)'
    )
    parser.add_argument(
        '--adaptations',
        type=int,
        default=30,
        help='Number of parameter adaptations to simulate (default: 30)'
    )
    parser.add_argument(
        '--strategies',
        type=int,
        default=45,
        help='Number of strategy evaluations to simulate (default: 45)'
    )
    parser.add_argument(
        '--run-time',
        type=int,
        default=600,  # 10 minutes
        help='Total run time in seconds (default: 600)'
    )
    parser.add_argument(
        '--dashboard-name',
        type=str,
        default='optimizer_learning_dashboard.html',
        help='Filename for the HTML dashboard (default: optimizer_learning_dashboard.html)'
    )

    return parser.parse_args()

def main():
    """Run the main demo."""
    args = parse_arguments()

    # Create output directory
    if args.output_dir:
        output_dir = args.output_dir
        os.makedirs(output_dir, exist_ok=True)
    else:
        # Create a temporary directory
        output_dir = tempfile.mkdtemp(prefix="rag_optimizer_vis_")

    logger.info(f"Using output directory: {output_dir}")

    # Create visualization system
    visualization = LiveOptimizerVisualization(
        metrics_dir=os.path.join(output_dir, "metrics"),
        visualization_dir=os.path.join(output_dir, "visualizations"),
        visualization_interval=args.interval,
        dashboard_filename=args.dashboard_name
    )

    # Inject sample data
    logger.info("Injecting initial sample data...")
    visualization.inject_sample_data(
        num_cycles=args.cycles,
        num_adaptations=args.adaptations,
        num_strategies=args.strategies
    )

    # Update visualizations
    logger.info("Generating initial visualizations...")
    result_files = visualization.update_visualizations()

    # Print visualization file paths
    logger.info("Generated visualization files:")
    for name, path in result_files.items():
        logger.info(f"  - {name}: {path}")

    # Start auto-update
    logger.info(f"Starting auto-update with interval {args.interval} seconds...")
    visualization.start_auto_update()

    # Simulate periodic updates
    logger.info(f"Running demo for {args.run_time} seconds with visualization updates...")

    start_time = time.time()
    num_updates = 0

    try:
        while time.time() - start_time < args.run_time:
            # Sleep for 1/4 of the update interval
            time.sleep(args.interval / 4)

            # Every other cycle, add some more sample data
            if num_updates % 2 == 0:
                visualization.inject_sample_data(
                    num_cycles=max(1, args.cycles // 5),
                    num_adaptations=max(2, args.adaptations // 5),
                    num_strategies=max(3, args.strategies // 5)
                )
                logger.info(f"Injected additional sample data (update {num_updates+1})")

            num_updates += 1

            # Give an update on remaining time
            elapsed = time.time() - start_time
            remaining = args.run_time - elapsed
            logger.info(f"Demo running... {int(remaining)}s remaining")

    except KeyboardInterrupt:
        logger.info("Demo interrupted by user")
    finally:
        # Stop the auto-update thread
        visualization.stop_auto_update()

        # Generate final visualizations
        logger.info("Generating final visualizations...")
        final_results = visualization.update_visualizations()

        # Print final dashboard path
        if 'dashboard' in final_results:
            dashboard_path = final_results['dashboard']
            logger.info(f"Final dashboard available at: {dashboard_path}")

            # Try to open the dashboard in a browser
            try:
                import webbrowser
                webbrowser.open(f"file://{os.path.abspath(dashboard_path)}")
                logger.info("Opened dashboard in web browser")
            except:
                logger.warning("Could not open dashboard in web browser automatically")

        logger.info(f"Demo complete! All visualization files are in {output_dir}")
        logger.info(f"To view the dashboard directly, open: {os.path.join(output_dir, 'visualizations', args.dashboard_name)}")

if __name__ == "__main__":
    main()
