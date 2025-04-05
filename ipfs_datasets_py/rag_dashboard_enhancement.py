"""
Enhancement for RAGQueryDashboard to include learning metrics visualizations.

This module extends the RAGQueryDashboard to incorporate learning metrics
visualizations from the OptimizerLearningMetricsCollector.
"""

import os
import logging
from typing import Dict, Any, Optional

# Setup logging
logger = logging.getLogger(__name__)

# Import visualization libraries if available
try:
    import matplotlib.pyplot as plt
    VISUALIZATION_AVAILABLE = True
except ImportError:
    logger.warning("Matplotlib not available. Static visualizations will not work.")
    VISUALIZATION_AVAILABLE = False

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    INTERACTIVE_VISUALIZATION_AVAILABLE = True
except ImportError:
    logger.warning("Plotly not available. Interactive visualizations will not work.")
    INTERACTIVE_VISUALIZATION_AVAILABLE = False


def enhance_dashboard_with_learning_metrics(dashboard_class):
    """
    Enhance a RAGQueryDashboard class with learning metrics visualization.
    
    This function decorates a dashboard class to add learning metrics visualization
    capabilities. It preserves the original interface while adding new functionality.
    
    Args:
        dashboard_class: The dashboard class to enhance
        
    Returns:
        The enhanced dashboard class
    """
    # Store the original generate_integrated_dashboard method
    original_generate_integrated_dashboard = getattr(
        dashboard_class,
        'generate_integrated_dashboard',
        None
    )
    
    # Define the enhanced method
    def enhanced_generate_integrated_dashboard(
        self,
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
        theme: str = 'light'
    ) -> str:
        """
        Generate an integrated dashboard with learning metrics.
        
        This enhanced method extends the original to include learning metrics
        visualizations from the OptimizerLearningMetricsCollector.
        
        Args:
            output_file: Path to save the dashboard HTML file
            audit_metrics_aggregator: Audit metrics for security correlation
            learning_metrics_collector: Learning metrics for optimizer insights
            title: Dashboard title
            include_performance: Whether to include performance metrics
            include_security: Whether to include security metrics
            include_security_correlation: Whether to correlate security with performance
            include_query_audit_timeline: Whether to include query-audit timeline
            include_learning_metrics: Whether to include learning metrics
            interactive: Whether to use interactive visualizations
            theme: Visual theme ('light' or 'dark')
            
        Returns:
            str: Path to the generated dashboard file
        """
        # Check if we can use the original method
        if original_generate_integrated_dashboard is None:
            logger.error("Original generate_integrated_dashboard method not found.")
            return output_file
        
        # Create a list of arguments to pass to the original method
        original_kwargs = {
            'output_file': output_file,
            'audit_metrics_aggregator': audit_metrics_aggregator,
            'title': title,
            'include_performance': include_performance,
            'include_security': include_security,
            'include_security_correlation': include_security_correlation,
            'include_query_audit_timeline': include_query_audit_timeline,
            'interactive': interactive,
            'theme': theme
        }
        
        # Check if learning metrics should be included
        if not include_learning_metrics or learning_metrics_collector is None:
            # Just use the original method without learning metrics
            return original_generate_integrated_dashboard(self, **original_kwargs)
        
        # Get output directory for visualization files
        output_dir = os.path.dirname(output_file)
        base_name = os.path.splitext(os.path.basename(output_file))[0]
        
        # Generate learning metrics visualizations
        visualization_files = {}
        visualization_html = {}
        
        try:
            # For interactive visualizations
            if interactive and INTERACTIVE_VISUALIZATION_AVAILABLE:
                try:
                    # Generate interactive visualizations
                    visualization_html['learning_cycles'] = self._generate_interactive_learning_cycles(
                        learning_metrics_collector
                    )
                    
                    visualization_html['parameter_adaptations'] = self._generate_interactive_parameter_adaptations(
                        learning_metrics_collector
                    )
                    
                    visualization_html['strategy_effectiveness'] = self._generate_interactive_strategy_effectiveness(
                        learning_metrics_collector
                    )
                    
                    visualization_html['learning_performance'] = self._generate_interactive_learning_performance(
                        learning_metrics_collector
                    )
                    
                except Exception as e:
                    logger.error(f"Error generating interactive learning visualizations: {str(e)}")
            
            # For static visualizations (or as fallback)
            if (not interactive or not INTERACTIVE_VISUALIZATION_AVAILABLE) and VISUALIZATION_AVAILABLE:
                try:
                    # Generate static visualizations
                    visualization_files['learning_cycles'] = os.path.join(
                        output_dir, f"{base_name}_learning_cycles.png"
                    )
                    learning_metrics_collector.visualize_learning_cycles(
                        output_file=visualization_files['learning_cycles']
                    )
                    
                    visualization_files['parameter_adaptations'] = os.path.join(
                        output_dir, f"{base_name}_parameter_adaptations.png"
                    )
                    learning_metrics_collector.visualize_parameter_adaptations(
                        output_file=visualization_files['parameter_adaptations']
                    )
                    
                    visualization_files['strategy_effectiveness'] = os.path.join(
                        output_dir, f"{base_name}_strategy_effectiveness.png"
                    )
                    learning_metrics_collector.visualize_strategy_effectiveness(
                        output_file=visualization_files['strategy_effectiveness']
                    )
                    
                    visualization_files['learning_performance'] = os.path.join(
                        output_dir, f"{base_name}_learning_performance.png"
                    )
                    learning_metrics_collector.visualize_learning_performance(
                        output_file=visualization_files['learning_performance']
                    )
                    
                except Exception as e:
                    logger.error(f"Error generating static learning visualizations: {str(e)}")
            
        except Exception as e:
            logger.error(f"Error generating learning visualizations: {str(e)}")
        
        # Call the original method to generate the base dashboard
        dashboard_file = original_generate_integrated_dashboard(self, **original_kwargs)
        
        # Add learning metrics to the dashboard
        try:
            self._add_learning_metrics_to_dashboard(
                dashboard_file=dashboard_file,
                learning_metrics_collector=learning_metrics_collector,
                visualization_files=visualization_files,
                visualization_html=visualization_html,
                interactive=interactive
            )
        except Exception as e:
            logger.error(f"Error adding learning metrics to dashboard: {str(e)}")
        
        return dashboard_file
    
    # Define helper methods for visualization
    def _generate_interactive_learning_cycles(self, learning_metrics_collector):
        """Generate interactive visualization of learning cycles."""
        try:
            if not INTERACTIVE_VISUALIZATION_AVAILABLE:
                return None
                
            # Get data from collector
            learning_cycles = learning_metrics_collector.learning_cycles
            if not learning_cycles:
                return None
                
            # Sort cycles by timestamp
            import datetime
            sorted_cycles = sorted(learning_cycles.items(), key=lambda x: x[1].get("timestamp", 0))
            
            # Extract data for plotting
            timestamps = [datetime.datetime.fromtimestamp(cycle["timestamp"]) for _, cycle in sorted_cycles]
            analyzed_queries = [cycle["analyzed_queries"] for _, cycle in sorted_cycles]
            patterns_identified = [cycle["patterns_identified"] for _, cycle in sorted_cycles]
            param_counts = [len(cycle["parameters_adjusted"]) for _, cycle in sorted_cycles]
            
            # Create figure
            fig = make_subplots(
                rows=2, cols=1,
                subplot_titles=["Queries Analyzed & Patterns Identified", "Parameter Adjustments"]
            )
            
            # Add traces for queries and patterns
            fig.add_trace(
                go.Scatter(
                    x=timestamps,
                    y=analyzed_queries,
                    mode='lines+markers',
                    name='Queries Analyzed',
                    line=dict(color='blue')
                ),
                row=1, col=1
            )
            
            fig.add_trace(
                go.Scatter(
                    x=timestamps,
                    y=patterns_identified,
                    mode='lines+markers',
                    name='Patterns Identified',
                    line=dict(color='green')
                ),
                row=1, col=1
            )
            
            # Add trace for parameter counts
            fig.add_trace(
                go.Scatter(
                    x=timestamps,
                    y=param_counts,
                    mode='lines+markers',
                    name='Parameters Adjusted',
                    line=dict(color='red')
                ),
                row=2, col=1
            )
            
            # Update layout
            fig.update_layout(
                title="Learning Cycles",
                height=600,
                showlegend=True
            )
            
            # Convert to HTML
            return fig.to_html(include_plotlyjs='cdn', full_html=False)
            
        except Exception as e:
            logger.error(f"Error generating interactive learning cycles: {str(e)}")
            return None
    
    def _generate_interactive_parameter_adaptations(self, learning_metrics_collector):
        """Generate interactive visualization of parameter adaptations."""
        try:
            if not INTERACTIVE_VISUALIZATION_AVAILABLE:
                return None
                
            # Get data from collector
            adaptations = learning_metrics_collector.parameter_adaptations
            if not adaptations:
                return None
                
            # Group adaptations by parameter
            param_groups = {}
            for adaptation in adaptations:
                param_name = adaptation["parameter_name"]
                if param_name not in param_groups:
                    param_groups[param_name] = {
                        "timestamps": [],
                        "values": [],
                        "confidences": [],
                        "hover_texts": []
                    }
                
                # Add to group
                import datetime
                param_groups[param_name]["timestamps"].append(
                    datetime.datetime.fromtimestamp(adaptation["timestamp"])
                )
                param_groups[param_name]["values"].append(adaptation["new_value"])
                param_groups[param_name]["confidences"].append(adaptation["confidence"])
                
                # Create hover text
                hover_text = (
                    f"Parameter: {param_name}<br>" +
                    f"Old value: {adaptation['old_value']}<br>" +
                    f"New value: {adaptation['new_value']}<br>" +
                    f"Reason: {adaptation['adaptation_reason']}<br>" +
                    f"Confidence: {adaptation['confidence']:.2f}"
                )
                param_groups[param_name]["hover_texts"].append(hover_text)
            
            # Calculate subplot size
            num_params = len(param_groups)
            if num_params == 0:
                return None
                
            # Create figure
            fig = make_subplots(
                rows=num_params, cols=2,
                subplot_titles=[f"{param} Value" for param in param_groups.keys()] +
                              [f"{param} Confidence" for param in param_groups.keys()]
            )
            
            # Add traces for each parameter
            for i, (param_name, param_data) in enumerate(param_groups.items(), 1):
                # Value trace
                fig.add_trace(
                    go.Scatter(
                        x=param_data["timestamps"],
                        y=param_data["values"],
                        mode='lines+markers',
                        name=f'{param_name} Value',
                        line=dict(color='blue'),
                        text=param_data["hover_texts"],
                        hoverinfo='text'
                    ),
                    row=i, col=1
                )
                
                # Confidence trace
                fig.add_trace(
                    go.Scatter(
                        x=param_data["timestamps"],
                        y=param_data["confidences"],
                        mode='lines+markers',
                        name=f'{param_name} Confidence',
                        line=dict(color='green'),
                        text=param_data["hover_texts"],
                        hoverinfo='text'
                    ),
                    row=i, col=2
                )
            
            # Update layout
            fig.update_layout(
                title="Parameter Adaptations",
                height=300 * num_params,
                showlegend=True
            )
            
            # Add y-axis range for confidence plots
            for i in range(1, num_params + 1):
                fig.update_yaxes(range=[0, 1.05], row=i, col=2)
            
            # Convert to HTML
            return fig.to_html(include_plotlyjs='cdn', full_html=False)
            
        except Exception as e:
            logger.error(f"Error generating interactive parameter adaptations: {str(e)}")
            return None
    
    def _generate_interactive_strategy_effectiveness(self, learning_metrics_collector):
        """Generate interactive visualization of strategy effectiveness."""
        try:
            if not INTERACTIVE_VISUALIZATION_AVAILABLE:
                return None
                
            # Get data from collector
            effectiveness_data = learning_metrics_collector.get_effectiveness_by_strategy()
            if not effectiveness_data:
                return None
                
            # Extract data
            strategies = list(effectiveness_data.keys())
            avg_scores = [data["avg_score"] for data in effectiveness_data.values()]
            avg_times = [data["avg_time"] for data in effectiveness_data.values()]
            
            # Create figure
            fig = make_subplots(
                rows=1, cols=2,
                subplot_titles=["Effectiveness Score by Strategy", "Execution Time by Strategy"]
            )
            
            # Add bar charts
            fig.add_trace(
                go.Bar(
                    x=strategies,
                    y=avg_scores,
                    name='Effectiveness Score',
                    marker_color='blue',
                    text=[f"{score:.2f}" for score in avg_scores],
                    textposition='auto'
                ),
                row=1, col=1
            )
            
            fig.add_trace(
                go.Bar(
                    x=strategies,
                    y=avg_times,
                    name='Execution Time (s)',
                    marker_color='green',
                    text=[f"{time:.2f}s" for time in avg_times],
                    textposition='auto'
                ),
                row=1, col=2
            )
            
            # Update layout
            fig.update_layout(
                title="Strategy Effectiveness",
                height=400,
                showlegend=True
            )
            
            # Set y-axis range for effectiveness scores
            fig.update_yaxes(range=[0, 1.05], row=1, col=1)
            
            # Convert to HTML
            return fig.to_html(include_plotlyjs='cdn', full_html=False)
            
        except Exception as e:
            logger.error(f"Error generating interactive strategy effectiveness: {str(e)}")
            return None
    
    def _generate_interactive_learning_performance(self, learning_metrics_collector):
        """Generate interactive visualization of learning performance."""
        try:
            if not INTERACTIVE_VISUALIZATION_AVAILABLE:
                return None
                
            # Get data from collector
            learning_cycles = learning_metrics_collector.learning_cycles
            if not learning_cycles:
                return None
                
            # Sort cycles by timestamp
            import datetime
            sorted_cycles = sorted(learning_cycles.items(), key=lambda x: x[1].get("timestamp", 0))
            
            # Extract data for plotting
            timestamps = [datetime.datetime.fromtimestamp(cycle["timestamp"]) for _, cycle in sorted_cycles]
            execution_times = [cycle["execution_time"] for _, cycle in sorted_cycles]
            
            # Calculate patterns per query
            patterns_per_query = []
            for _, cycle in sorted_cycles:
                if cycle["analyzed_queries"] > 0:
                    ratio = cycle["patterns_identified"] / cycle["analyzed_queries"]
                else:
                    ratio = 0
                patterns_per_query.append(ratio)
            
            # Calculate cumulative patterns
            cumulative_patterns = []
            total = 0
            for _, cycle in sorted_cycles:
                total += cycle["patterns_identified"]
                cumulative_patterns.append(total)
            
            # Create figure
            fig = make_subplots(
                rows=2, cols=2,
                subplot_titles=[
                    "Learning Cycle Execution Time",
                    "Patterns per Query",
                    "Cumulative Patterns Identified",
                    "Parameter Adjustment Trend"
                ]
            )
            
            # Add traces
            fig.add_trace(
                go.Scatter(
                    x=timestamps,
                    y=execution_times,
                    mode='lines+markers',
                    name='Execution Time (s)',
                    line=dict(color='blue')
                ),
                row=1, col=1
            )
            
            fig.add_trace(
                go.Scatter(
                    x=timestamps,
                    y=patterns_per_query,
                    mode='lines+markers',
                    name='Patterns per Query',
                    line=dict(color='green')
                ),
                row=1, col=2
            )
            
            fig.add_trace(
                go.Scatter(
                    x=timestamps,
                    y=cumulative_patterns,
                    mode='lines+markers',
                    name='Cumulative Patterns',
                    line=dict(color='purple')
                ),
                row=2, col=1
            )
            
            # Get parameter adaptation trend
            adaptations = learning_metrics_collector.parameter_adaptations
            if adaptations:
                param_timestamps = [datetime.datetime.fromtimestamp(a["timestamp"]) for a in adaptations]
                param_confidences = [a["confidence"] for a in adaptations]
                
                fig.add_trace(
                    go.Scatter(
                        x=param_timestamps,
                        y=param_confidences,
                        mode='markers',
                        name='Adaptation Confidence',
                        marker=dict(
                            size=10,
                            color=param_confidences,
                            colorscale='Viridis',
                            showscale=True,
                            colorbar=dict(title="Confidence")
                        )
                    ),
                    row=2, col=2
                )
            
            # Update layout
            fig.update_layout(
                title="Learning Performance Metrics",
                height=800,
                showlegend=True
            )
            
            # Convert to HTML
            return fig.to_html(include_plotlyjs='cdn', full_html=False)
            
        except Exception as e:
            logger.error(f"Error generating interactive learning performance: {str(e)}")
            return None
    
    def _add_learning_metrics_to_dashboard(
        self,
        dashboard_file,
        learning_metrics_collector,
        visualization_files,
        visualization_html,
        interactive
    ):
        """Add learning metrics to an existing dashboard file."""
        try:
            # Read the dashboard file
            with open(dashboard_file, 'r', encoding='utf-8') as f:
                dashboard_html = f.read()
            
            # Check if the dashboard already has a body closing tag
            body_closing_tag = '</body>'
            if body_closing_tag in dashboard_html:
                # Create the learning metrics HTML to insert
                learning_metrics_html = self._create_learning_metrics_html(
                    learning_metrics_collector,
                    visualization_files,
                    visualization_html,
                    interactive
                )
                
                # Insert before the body closing tag
                dashboard_html = dashboard_html.replace(
                    body_closing_tag,
                    learning_metrics_html + '\n' + body_closing_tag
                )
                
                # Write back to the file
                with open(dashboard_file, 'w', encoding='utf-8') as f:
                    f.write(dashboard_html)
            else:
                logger.warning("Could not find </body> tag in dashboard HTML. Learning metrics not added.")
        except Exception as e:
            logger.error(f"Error adding learning metrics to dashboard: {str(e)}")
    
    def _create_learning_metrics_html(
        self,
        learning_metrics_collector,
        visualization_files,
        visualization_html,
        interactive
    ):
        """Create HTML for learning metrics section."""
        # Get learning metrics summary
        metrics = learning_metrics_collector.get_learning_metrics()
        
        # Create HTML
        html = '''
        <div class="dashboard-section">
            <h2>Optimizer Learning Metrics</h2>
            
            <div class="metrics-grid">
                <div class="metric-card">
                    <div class="metric-title">Learning Cycles</div>
                    <div class="metric-value">{total_learning_cycles}</div>
                </div>
                
                <div class="metric-card">
                    <div class="metric-title">Queries Analyzed</div>
                    <div class="metric-value">{total_analyzed_queries}</div>
                </div>
                
                <div class="metric-card">
                    <div class="metric-title">Patterns Identified</div>
                    <div class="metric-value">{total_patterns_identified}</div>
                </div>
                
                <div class="metric-card">
                    <div class="metric-title">Parameters Adjusted</div>
                    <div class="metric-value">{total_parameters_adjusted}</div>
                </div>
                
                <div class="metric-card">
                    <div class="metric-title">Avg Cycle Time</div>
                    <div class="metric-value">{average_cycle_time:.2f}s</div>
                </div>
            </div>
        '''.format(
            total_learning_cycles=metrics.total_learning_cycles,
            total_analyzed_queries=metrics.total_analyzed_queries,
            total_patterns_identified=metrics.total_patterns_identified,
            total_parameters_adjusted=metrics.total_parameters_adjusted,
            average_cycle_time=metrics.average_cycle_time
        )
        
        # Add visualizations
        if interactive and visualization_html:
            html += '''
            <div class="visualization-container">
                <div class="visualization-tabs">
                    <div class="tab-buttons">
                        <button class="tab-button active" onclick="openTab(event, 'cycles-tab')">Learning Cycles</button>
                        <button class="tab-button" onclick="openTab(event, 'params-tab')">Parameter Adaptations</button>
                        <button class="tab-button" onclick="openTab(event, 'strategies-tab')">Strategy Effectiveness</button>
                        <button class="tab-button" onclick="openTab(event, 'performance-tab')">Learning Performance</button>
                    </div>
                    
                    <div id="cycles-tab" class="tab-content active">
                        {learning_cycles_html}
                    </div>
                    
                    <div id="params-tab" class="tab-content">
                        {parameter_adaptations_html}
                    </div>
                    
                    <div id="strategies-tab" class="tab-content">
                        {strategy_effectiveness_html}
                    </div>
                    
                    <div id="performance-tab" class="tab-content">
                        {learning_performance_html}
                    </div>
                </div>
            </div>
            '''.format(
                learning_cycles_html=visualization_html.get('learning_cycles', 'No data available'),
                parameter_adaptations_html=visualization_html.get('parameter_adaptations', 'No data available'),
                strategy_effectiveness_html=visualization_html.get('strategy_effectiveness', 'No data available'),
                learning_performance_html=visualization_html.get('learning_performance', 'No data available')
            )
        elif visualization_files:
            # Static images
            html += '''
            <div class="visualization-section">
                <h3>Learning Cycles</h3>
                <img src="{learning_cycles}" alt="Learning Cycles" class="visualization-image">
                
                <h3>Parameter Adaptations</h3>
                <img src="{parameter_adaptations}" alt="Parameter Adaptations" class="visualization-image">
                
                <h3>Strategy Effectiveness</h3>
                <img src="{strategy_effectiveness}" alt="Strategy Effectiveness" class="visualization-image">
                
                <h3>Learning Performance</h3>
                <img src="{learning_performance}" alt="Learning Performance" class="visualization-image">
            </div>
            '''.format(
                learning_cycles=os.path.basename(visualization_files.get('learning_cycles', '')),
                parameter_adaptations=os.path.basename(visualization_files.get('parameter_adaptations', '')),
                strategy_effectiveness=os.path.basename(visualization_files.get('strategy_effectiveness', '')),
                learning_performance=os.path.basename(visualization_files.get('learning_performance', ''))
            )
        else:
            html += '<p>No learning metrics visualizations available.</p>'
        
        # Add tab script if using interactive visualizations
        if interactive and visualization_html:
            html += '''
            <script>
            function openTab(evt, tabName) {
                // Declare variables
                var i, tabContent, tabButtons;
                
                // Get all elements with class="tab-content" and hide them
                tabContent = document.getElementsByClassName("tab-content");
                for (i = 0; i < tabContent.length; i++) {
                    tabContent[i].classList.remove("active");
                }
                
                // Get all elements with class="tab-button" and remove "active" class
                tabButtons = document.getElementsByClassName("tab-button");
                for (i = 0; i < tabButtons.length; i++) {
                    tabButtons[i].classList.remove("active");
                }
                
                // Show the current tab and add "active" class to the button that opened the tab
                document.getElementById(tabName).classList.add("active");
                evt.currentTarget.classList.add("active");
            }
            </script>
            '''
        
        # Close the section
        html += '</div>'
        
        # Add some CSS to ensure proper styling
        html += '''
        <style>
            .dashboard-section {
                background-color: #ffffff;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                margin-bottom: 20px;
                padding: 20px;
                width: 100%;
            }
            
            .metrics-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
                gap: 15px;
                margin-bottom: 20px;
            }
            
            .metric-card {
                background-color: #f5f5f5;
                border-radius: 6px;
                padding: 15px;
                text-align: center;
            }
            
            .metric-title {
                color: #666;
                font-size: 14px;
                margin-bottom: 5px;
            }
            
            .metric-value {
                color: #333;
                font-size: 24px;
                font-weight: bold;
            }
            
            .visualization-container {
                margin-top: 20px;
                width: 100%;
            }
            
            .visualization-tabs {
                width: 100%;
            }
            
            .tab-buttons {
                display: flex;
                overflow-x: auto;
                border-bottom: 1px solid #ddd;
                margin-bottom: 15px;
            }
            
            .tab-button {
                background-color: inherit;
                border: none;
                outline: none;
                cursor: pointer;
                padding: 10px 15px;
                transition: 0.3s;
                font-size: 14px;
                margin-right: 2px;
            }
            
            .tab-button:hover {
                background-color: #ddd;
            }
            
            .tab-button.active {
                background-color: #f0f0f0;
                border-bottom: 2px solid #4CAF50;
            }
            
            .tab-content {
                display: none;
                padding: 15px;
                width: 100%;
            }
            
            .tab-content.active {
                display: block;
            }
            
            .visualization-section {
                display: flex;
                flex-direction: column;
                gap: 20px;
            }
            
            .visualization-image {
                max-width: 100%;
                height: auto;
                border-radius: 6px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            }
        </style>
        '''
        
        return html
    
    # Replace the original method with our enhanced version
    if original_generate_integrated_dashboard is not None:
        setattr(dashboard_class, 'generate_integrated_dashboard', enhanced_generate_integrated_dashboard)
    
    # Add the helper methods
    setattr(dashboard_class, '_generate_interactive_learning_cycles', _generate_interactive_learning_cycles)
    setattr(dashboard_class, '_generate_interactive_parameter_adaptations', _generate_interactive_parameter_adaptations)
    setattr(dashboard_class, '_generate_interactive_strategy_effectiveness', _generate_interactive_strategy_effectiveness)
    setattr(dashboard_class, '_generate_interactive_learning_performance', _generate_interactive_learning_performance)
    setattr(dashboard_class, '_add_learning_metrics_to_dashboard', _add_learning_metrics_to_dashboard)
    setattr(dashboard_class, '_create_learning_metrics_html', _create_learning_metrics_html)
    
    # Return the enhanced class
    return dashboard_class


def enhance_existing_dashboard(dashboard_instance):
    """
    Enhance an existing dashboard instance with learning metrics visualization.
    
    This function adds learning metrics visualization capabilities to an existing
    dashboard instance by adding new methods and enhancing existing ones.
    
    Args:
        dashboard_instance: The dashboard instance to enhance
        
    Returns:
        The enhanced dashboard instance
    """
    # Get the dashboard class
    dashboard_class = dashboard_instance.__class__
    
    # Enhance the class
    enhanced_class = enhance_dashboard_with_learning_metrics(dashboard_class)
    
    # Return the enhanced instance
    return dashboard_instance