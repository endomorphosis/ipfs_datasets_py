# Alert and Visualization System Integration

This directory contains an example demonstrating the integration between the RAG Query Optimizer's alert system and visualization system. The integration provides a comprehensive monitoring solution that can detect anomalies in the optimizer's learning process and visualize them alongside performance metrics.

## Components

### 1. `alert_visualization_integration.py`

This script demonstrates how to integrate the optimizer alert system with the visualization system. It includes:

- A simulated optimizer that generates learning metrics
- A metrics collector that adapts the optimizer's data for the alert system
- An alert system that detects anomalies in the learning process
- A visualization system that displays learning metrics
- A custom alert handler that connects the alert system to the visualization system
- A dashboard that combines metrics and alerts into a single view

### 2. Alert System

The alert system (`LearningAlertSystem`) detects various types of anomalies in the optimizer's learning process:

- **Parameter Oscillations**: When parameters change back and forth frequently
- **Performance Declines**: When success rates drop or latencies increase
- **Strategy Effectiveness Issues**: When certain strategies become less effective
- **Learning Stalls**: When no parameter adjustments occur despite query pattern changes

### 3. Visualization System

The visualization system (`LiveOptimizerVisualization`) provides visualizations of the optimizer's learning metrics:

- **Learning Cycles**: Visualizes how the optimizer learns over time
- **Parameter Adaptations**: Shows how parameters are adjusted
- **Strategy Effectiveness**: Displays the effectiveness of different query strategies

### 4. Integration Points

The main integration points between the systems include:

- A custom alert handler that adds alerts to the visualization system
- A shared metrics collection mechanism
- A combined dashboard that displays both metrics and alerts

## Running the Example

To run the integration example, use the following command:

```bash
python examples/alert_visualization_integration.py --duration <seconds> --output-dir <directory>
```

Options:
- `--duration`: Duration of the simulation in seconds (default: 300)
- `--output-dir`: Directory to save visualization outputs (default: ./visualizations)
- `--anomaly-free`: Run the simulation without injecting anomalies

## Example Output

The example generates several outputs:

1. **Integrated Dashboard**: An HTML dashboard that combines metrics and alerts
2. **Alert Data**: A JSON file containing detected anomalies
3. **Visualizations**: Various visualization files (PNG, HTML) for learning metrics
4. **Log Files**: Alert and visualization logs

## Extending the Integration

To extend the integration for your own use case:

1. Replace the simulated optimizer with your actual RAG query optimizer
2. Adapt the metrics collector to your specific data formats
3. Customize the alert thresholds and types
4. Enhance the dashboard with additional visualizations

## Benefits

This integrated approach provides several benefits:

1. **Proactive Monitoring**: Detect issues before they impact performance
2. **Visual Context**: See anomalies in the context of performance metrics
3. **Comprehensive View**: Unified dashboard for all monitoring information
4. **Actionable Insights**: Clear indicators of what issues need attention

## Integration with Production Systems

For integration with production systems:

1. Set up periodic background checks for anomalies
2. Configure alerting channels (email, Slack, monitoring systems)
3. Schedule regular dashboard updates
4. Add user-configurable alert thresholds
5. Implement historical comparison for trend analysis