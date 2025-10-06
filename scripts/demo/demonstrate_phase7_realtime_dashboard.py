#!/usr/bin/env python3
"""
Real-Time Analytics Dashboard for Phase 7 - Live ML insights and monitoring

This module provides a real-time analytics dashboard for monitoring and visualizing
the advanced ML and analytics capabilities of Phase 7 GraphRAG system.

Features:
- Real-time ML model performance monitoring
- Live cross-website correlation tracking
- Global knowledge graph visualization
- Quality score trending and alerts
- Interactive recommendation analytics
- Production system health monitoring

Usage:
    dashboard = RealTimeMLAnalyticsDashboard()
    await dashboard.start_monitoring()
    # Access dashboard at http://localhost:8080/dashboard
"""

import os
import json
import asyncio
import logging
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import uuid
from collections import deque, defaultdict
import time

# Web framework imports
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    import uvicorn
    WEB_AVAILABLE = True
except ImportError:
    WEB_AVAILABLE = False

# Import Phase 7 components
from ipfs_datasets_py.ml.content_classification import ContentClassificationPipeline
from ipfs_datasets_py.ml.quality_models import ProductionMLModelServer
from ipfs_datasets_py.analytics.cross_website_analyzer import CrossWebsiteAnalyzer

logger = logging.getLogger(__name__)


@dataclass
class RealTimeMetrics:
    """Real-time metrics for dashboard"""
    
    timestamp: datetime
    ml_predictions_count: int
    average_quality_score: float
    active_analyses: int
    cross_site_correlations: int
    system_health: str
    processing_rate: float  # items per second
    memory_usage_mb: float
    cpu_usage_percent: float


@dataclass
class AlertConfig:
    """Configuration for monitoring alerts"""
    
    quality_threshold: float = 0.5
    correlation_threshold: float = 0.3
    processing_rate_threshold: float = 1.0
    memory_threshold_mb: float = 2000
    cpu_threshold_percent: float = 80.0


class RealTimeMLAnalyticsDashboard:
    """
    Real-time analytics dashboard for Phase 7 ML and analytics monitoring.
    
    Provides live monitoring and visualization of:
    - ML model performance and predictions
    - Cross-website correlation analysis
    - Global knowledge graph growth
    - Quality assessment trends
    - System performance metrics
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or self._default_config()
        
        # Initialize monitoring components
        self.ml_pipeline = ContentClassificationPipeline()
        self.model_server = ProductionMLModelServer()
        self.cross_site_analyzer = CrossWebsiteAnalyzer()
        
        # Real-time data storage
        self.metrics_history = deque(maxlen=1000)  # Last 1000 metrics points
        self.active_sessions = {}
        self.websocket_connections = set()
        
        # Alert system
        self.alert_config = AlertConfig()
        self.active_alerts = []
        
        # Dashboard state
        self.is_monitoring = False
        self.monitoring_task = None
        
        # Initialize web app if available
        if WEB_AVAILABLE:
            self.app = FastAPI(title="Phase 7 ML Analytics Dashboard")
            self._setup_routes()
        else:
            self.app = None
    
    def _default_config(self) -> Dict[str, Any]:
        """Default configuration for dashboard"""
        return {
            'monitoring_interval_seconds': 5,
            'dashboard_port': 8080,
            'enable_websocket_streaming': True,
            'enable_alerts': True,
            'data_retention_hours': 24,
            'enable_export': True
        }
    
    def _setup_routes(self):
        """Setup FastAPI routes for dashboard"""
        
        @self.app.get("/", response_class=HTMLResponse)
        async def dashboard_home():
            """Serve dashboard HTML"""
            return self._generate_dashboard_html()
        
        @self.app.get("/api/metrics")
        async def get_current_metrics():
            """Get current real-time metrics"""
            return await self._collect_current_metrics()
        
        @self.app.get("/api/metrics/history")
        async def get_metrics_history():
            """Get historical metrics data"""
            return {
                'metrics': [
                    {
                        'timestamp': m.timestamp.isoformat(),
                        'ml_predictions': m.ml_predictions_count,
                        'quality_score': m.average_quality_score,
                        'correlations': m.cross_site_correlations,
                        'processing_rate': m.processing_rate,
                        'system_health': m.system_health
                    }
                    for m in list(self.metrics_history)
                ],
                'total_points': len(self.metrics_history)
            }
        
        @self.app.get("/api/model-performance")
        async def get_model_performance():
            """Get ML model performance data"""
            if hasattr(self.model_server, 'get_model_performance_summary'):
                return self.model_server.get_model_performance_summary()
            return {'message': 'Model performance data not available'}
        
        @self.app.get("/api/cross-site-analytics")
        async def get_cross_site_analytics():
            """Get cross-site analytics summary"""
            if hasattr(self.cross_site_analyzer, 'get_cross_site_analytics_summary'):
                return self.cross_site_analyzer.get_cross_site_analytics_summary()
            return {'message': 'Cross-site analytics not available'}
        
        @self.app.get("/api/alerts")
        async def get_active_alerts():
            """Get active monitoring alerts"""
            return {
                'alerts': self.active_alerts,
                'alert_count': len(self.active_alerts),
                'last_check': datetime.now().isoformat()
            }
        
        @self.app.websocket("/ws/metrics")
        async def websocket_metrics(websocket: WebSocket):
            """WebSocket endpoint for real-time metrics streaming"""
            await websocket.accept()
            self.websocket_connections.add(websocket)
            
            try:
                while True:
                    # Send current metrics every few seconds
                    metrics = await self._collect_current_metrics()
                    await websocket.send_json(metrics)
                    await asyncio.sleep(self.config['monitoring_interval_seconds'])
                    
            except WebSocketDisconnect:
                self.websocket_connections.remove(websocket)
    
    def _generate_dashboard_html(self) -> str:
        """Generate dashboard HTML interface"""
        
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Phase 7 ML Analytics Dashboard</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
                .header { background: #2c3e50; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
                .metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
                .metric-card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
                .metric-value { font-size: 2em; font-weight: bold; color: #3498db; }
                .metric-label { color: #7f8c8d; margin-bottom: 10px; }
                .status-good { color: #27ae60; }
                .status-warning { color: #f39c12; }
                .status-error { color: #e74c3c; }
                .chart-placeholder { height: 200px; background: #ecf0f1; border-radius: 4px; display: flex; align-items: center; justify-content: center; color: #7f8c8d; }
            </style>
        </head>
        <body>
            <div class="header">
                <h1>🚀 Phase 7 ML Analytics Dashboard</h1>
                <p>Real-time monitoring of GraphRAG advanced analytics and ML integration</p>
            </div>
            
            <div class="metrics-grid">
                <div class="metric-card">
                    <div class="metric-label">ML Predictions</div>
                    <div class="metric-value" id="ml-predictions">0</div>
                    <div>Total ML predictions processed</div>
                </div>
                
                <div class="metric-card">
                    <div class="metric-label">Average Quality Score</div>
                    <div class="metric-value" id="quality-score">0.00</div>
                    <div>Content quality assessment average</div>
                </div>
                
                <div class="metric-card">
                    <div class="metric-label">Cross-Site Correlations</div>
                    <div class="metric-value" id="correlations">0</div>
                    <div>Website correlation analyses</div>
                </div>
                
                <div class="metric-card">
                    <div class="metric-label">Processing Rate</div>
                    <div class="metric-value" id="processing-rate">0.0</div>
                    <div>Items per second</div>
                </div>
                
                <div class="metric-card">
                    <div class="metric-label">System Health</div>
                    <div class="metric-value status-good" id="system-health">Healthy</div>
                    <div>Overall system status</div>
                </div>
                
                <div class="metric-card">
                    <div class="metric-label">Active Models</div>
                    <div class="metric-value" id="active-models">0</div>
                    <div>Loaded ML models</div>
                </div>
            </div>
            
            <div style="margin-top: 30px;">
                <div class="metric-card">
                    <h3>📊 Quality Score Trend (Last 24 Hours)</h3>
                    <div class="chart-placeholder">Quality trend chart would be displayed here</div>
                </div>
            </div>
            
            <div style="margin-top: 20px;">
                <div class="metric-card">
                    <h3>🌐 Cross-Website Correlation Network</h3>
                    <div class="chart-placeholder">Website correlation network would be displayed here</div>
                </div>
            </div>
            
            <script>
                // Simple real-time updates
                async function updateMetrics() {
                    try {
                        const response = await fetch('/api/metrics');
                        const data = await response.json();
                        
                        document.getElementById('ml-predictions').textContent = data.ml_predictions || 0;
                        document.getElementById('quality-score').textContent = (data.quality_score || 0).toFixed(2);
                        document.getElementById('correlations').textContent = data.correlations || 0;
                        document.getElementById('processing-rate').textContent = (data.processing_rate || 0).toFixed(1);
                        document.getElementById('system-health').textContent = data.system_health || 'Unknown';
                        document.getElementById('active-models').textContent = data.active_models || 0;
                        
                    } catch (error) {
                        console.error('Failed to update metrics:', error);
                    }
                }
                
                // Update every 5 seconds
                setInterval(updateMetrics, 5000);
                updateMetrics(); // Initial load
            </script>
        </body>
        </html>
        """
    
    async def start_monitoring(self, port: int = None) -> bool:
        """Start real-time monitoring and dashboard"""
        
        port = port or self.config.get('dashboard_port', 8080)
        
        try:
            logger.info("Starting Phase 7 real-time analytics dashboard...")
            
            # Initialize ML components
            await self.model_server.load_models()
            
            # Start background monitoring
            if not self.is_monitoring:
                self.monitoring_task = asyncio.create_task(self._monitoring_loop())
                self.is_monitoring = True
            
            # Start web dashboard if available
            if WEB_AVAILABLE and self.app:
                logger.info(f"Dashboard available at http://localhost:{port}")
                config = uvicorn.Config(self.app, host="0.0.0.0", port=port, log_level="info")
                server = uvicorn.Server(config)
                await server.serve()
            else:
                logger.info("Web dashboard not available - monitoring in background mode")
                # Keep monitoring running
                while self.is_monitoring:
                    await asyncio.sleep(10)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start monitoring dashboard: {e}")
            return False
    
    async def _monitoring_loop(self):
        """Background monitoring loop"""
        
        logger.info("Starting real-time monitoring loop...")
        
        while self.is_monitoring:
            try:
                # Collect current metrics
                metrics = await self._collect_current_metrics()
                
                # Store metrics
                real_time_metrics = RealTimeMetrics(
                    timestamp=datetime.now(),
                    ml_predictions_count=metrics.get('ml_predictions', 0),
                    average_quality_score=metrics.get('quality_score', 0.0),
                    active_analyses=metrics.get('active_analyses', 0),
                    cross_site_correlations=metrics.get('correlations', 0),
                    system_health=metrics.get('system_health', 'unknown'),
                    processing_rate=metrics.get('processing_rate', 0.0),
                    memory_usage_mb=metrics.get('memory_usage_mb', 0.0),
                    cpu_usage_percent=metrics.get('cpu_usage_percent', 0.0)
                )
                
                self.metrics_history.append(real_time_metrics)
                
                # Check for alerts
                if self.config.get('enable_alerts', True):
                    await self._check_alerts(real_time_metrics)
                
                # Broadcast to WebSocket connections
                if self.websocket_connections:
                    await self._broadcast_metrics(metrics)
                
                # Wait for next interval
                await asyncio.sleep(self.config['monitoring_interval_seconds'])
                
            except Exception as e:
                logger.error(f"Monitoring loop error: {e}")
                await asyncio.sleep(5)  # Brief pause on error
    
    async def _collect_current_metrics(self) -> Dict[str, Any]:
        """Collect current system metrics"""
        
        metrics = {
            'timestamp': datetime.now().isoformat(),
            'ml_predictions': 0,
            'quality_score': 0.0,
            'active_analyses': 0,
            'correlations': 0,
            'system_health': 'healthy',
            'processing_rate': 0.0,
            'memory_usage_mb': 0.0,
            'cpu_usage_percent': 0.0,
            'active_models': 0
        }
        
        try:
            # Get ML model performance
            if hasattr(self.model_server, 'get_model_performance_summary'):
                model_perf = self.model_server.get_model_performance_summary()
                metrics['ml_predictions'] = model_perf.get('total_predictions', 0)
                metrics['active_models'] = len(model_perf.get('loaded_models', []))
                
                # Calculate average quality from model performance
                model_performance = model_perf.get('model_performance', {})
                quality_scores = []
                for model_data in model_performance.values():
                    if 'average_confidence' in model_data:
                        quality_scores.append(model_data['average_confidence'])
                
                if quality_scores:
                    metrics['quality_score'] = sum(quality_scores) / len(quality_scores)
            
            # Get cross-site analytics
            if hasattr(self.cross_site_analyzer, 'get_cross_site_analytics_summary'):
                cross_analytics = self.cross_site_analyzer.get_cross_site_analytics_summary()
                metrics['correlations'] = cross_analytics.get('total_cross_site_analyses', 0)
            
            # Get ML classification analytics
            if hasattr(self.ml_pipeline, 'get_analytics_summary'):
                ml_analytics = self.ml_pipeline.get_analytics_summary()
                metrics['active_analyses'] = ml_analytics.get('total_analyses', 0)
            
            # Calculate processing rate (simple approximation)
            if len(self.metrics_history) > 1:
                current_predictions = metrics['ml_predictions']
                previous_predictions = self.metrics_history[-1].ml_predictions_count
                time_diff = self.config['monitoring_interval_seconds']
                
                if time_diff > 0:
                    metrics['processing_rate'] = (current_predictions - previous_predictions) / time_diff
            
            # Mock system resource metrics (in production, use psutil)
            metrics['memory_usage_mb'] = 1500.0  # Mock memory usage
            metrics['cpu_usage_percent'] = 25.0  # Mock CPU usage
            
        except Exception as e:
            logger.error(f"Metrics collection failed: {e}")
            metrics['system_health'] = 'error'
        
        return metrics
    
    async def _check_alerts(self, metrics: RealTimeMetrics):
        """Check for alert conditions"""
        
        current_alerts = []
        
        # Quality score alert
        if metrics.average_quality_score < self.alert_config.quality_threshold:
            current_alerts.append({
                'type': 'quality_low',
                'severity': 'warning',
                'message': f"Average quality score ({metrics.average_quality_score:.2f}) below threshold ({self.alert_config.quality_threshold})",
                'timestamp': metrics.timestamp.isoformat()
            })
        
        # Processing rate alert
        if metrics.processing_rate < self.alert_config.processing_rate_threshold:
            current_alerts.append({
                'type': 'processing_rate_low',
                'severity': 'info',
                'message': f"Processing rate ({metrics.processing_rate:.1f}/s) below expected threshold",
                'timestamp': metrics.timestamp.isoformat()
            })
        
        # Memory usage alert
        if metrics.memory_usage_mb > self.alert_config.memory_threshold_mb:
            current_alerts.append({
                'type': 'memory_high',
                'severity': 'warning',
                'message': f"Memory usage ({metrics.memory_usage_mb:.0f}MB) exceeds threshold",
                'timestamp': metrics.timestamp.isoformat()
            })
        
        # CPU usage alert
        if metrics.cpu_usage_percent > self.alert_config.cpu_threshold_percent:
            current_alerts.append({
                'type': 'cpu_high',
                'severity': 'warning',
                'message': f"CPU usage ({metrics.cpu_usage_percent:.1f}%) exceeds threshold",
                'timestamp': metrics.timestamp.isoformat()
            })
        
        # Update active alerts (keep only recent alerts)
        cutoff_time = datetime.now() - timedelta(hours=1)
        self.active_alerts = [
            alert for alert in self.active_alerts + current_alerts
            if datetime.fromisoformat(alert['timestamp']) > cutoff_time
        ]
    
    async def _broadcast_metrics(self, metrics: Dict[str, Any]):
        """Broadcast metrics to WebSocket connections"""
        
        if not self.websocket_connections:
            return
        
        disconnected = set()
        
        for websocket in self.websocket_connections:
            try:
                await websocket.send_json(metrics)
            except:
                disconnected.add(websocket)
        
        # Remove disconnected clients
        self.websocket_connections -= disconnected
    
    async def generate_analytics_report(self) -> Dict[str, Any]:
        """Generate comprehensive analytics report"""
        
        try:
            current_time = datetime.now()
            
            # Calculate time-based metrics
            recent_metrics = [
                m for m in self.metrics_history
                if (current_time - m.timestamp).total_seconds() < 3600  # Last hour
            ]
            
            report = {
                'report_timestamp': current_time.isoformat(),
                'monitoring_period_hours': 24 if self.metrics_history else 0,
                'total_data_points': len(self.metrics_history),
                'recent_data_points': len(recent_metrics),
                'system_summary': await self._collect_current_metrics(),
                'performance_trends': {},
                'alert_summary': {
                    'active_alerts': len(self.active_alerts),
                    'alert_types': list(set(alert['type'] for alert in self.active_alerts))
                },
                'recommendations': []
            }
            
            # Calculate performance trends
            if recent_metrics:
                report['performance_trends'] = {
                    'quality_trend': {
                        'average': sum(m.average_quality_score for m in recent_metrics) / len(recent_metrics),
                        'min': min(m.average_quality_score for m in recent_metrics),
                        'max': max(m.average_quality_score for m in recent_metrics)
                    },
                    'processing_rate_trend': {
                        'average': sum(m.processing_rate for m in recent_metrics) / len(recent_metrics),
                        'peak': max(m.processing_rate for m in recent_metrics)
                    },
                    'correlation_trend': {
                        'total': sum(m.cross_site_correlations for m in recent_metrics),
                        'average_per_analysis': sum(m.cross_site_correlations for m in recent_metrics) / len(recent_metrics)
                    }
                }
            
            # Generate recommendations
            report['recommendations'] = self._generate_performance_recommendations(report)
            
            return report
            
        except Exception as e:
            logger.error(f"Analytics report generation failed: {e}")
            return {
                'error': str(e),
                'report_timestamp': datetime.now().isoformat()
            }
    
    def _generate_performance_recommendations(self, report: Dict[str, Any]) -> List[str]:
        """Generate performance recommendations based on analytics"""
        
        recommendations = []
        
        try:
            trends = report.get('performance_trends', {})
            
            # Quality recommendations
            quality_trend = trends.get('quality_trend', {})
            avg_quality = quality_trend.get('average', 0.5)
            
            if avg_quality < 0.6:
                recommendations.append("Consider improving content preprocessing - quality scores below optimal")
            elif avg_quality > 0.8:
                recommendations.append("Excellent content quality detected - current processing pipeline is optimal")
            
            # Processing rate recommendations
            rate_trend = trends.get('processing_rate_trend', {})
            avg_rate = rate_trend.get('average', 0.0)
            
            if avg_rate < 1.0:
                recommendations.append("Processing rate could be improved - consider optimizing ML model inference")
            elif avg_rate > 10.0:
                recommendations.append("High processing rate achieved - system performing optimally")
            
            # Alert-based recommendations
            alert_summary = report.get('alert_summary', {})
            active_alerts = alert_summary.get('active_alerts', 0)
            
            if active_alerts > 5:
                recommendations.append("Multiple active alerts detected - review system configuration")
            elif active_alerts == 0:
                recommendations.append("No active alerts - system operating within normal parameters")
            
            # Cross-site analysis recommendations
            correlation_trend = trends.get('correlation_trend', {})
            total_correlations = correlation_trend.get('total', 0)
            
            if total_correlations > 50:
                recommendations.append("High cross-site correlation activity - consider global knowledge graph optimization")
            
            if not recommendations:
                recommendations.append("System performance is within expected parameters")
            
        except Exception as e:
            logger.error(f"Recommendation generation failed: {e}")
            recommendations.append("Unable to generate recommendations due to data analysis error")
        
        return recommendations[:5]  # Limit to top 5
    
    async def export_dashboard_data(self, output_format: str = 'json') -> str:
        """Export dashboard data for external analysis"""
        
        try:
            # Generate comprehensive analytics report
            analytics_report = await self.generate_analytics_report()
            
            # Add detailed metrics history
            export_data = {
                'export_metadata': {
                    'export_timestamp': datetime.now().isoformat(),
                    'export_format': output_format,
                    'dashboard_version': '1.0.0'
                },
                'analytics_report': analytics_report,
                'metrics_history': [
                    {
                        'timestamp': m.timestamp.isoformat(),
                        'ml_predictions_count': m.ml_predictions_count,
                        'average_quality_score': m.average_quality_score,
                        'active_analyses': m.active_analyses,
                        'cross_site_correlations': m.cross_site_correlations,
                        'system_health': m.system_health,
                        'processing_rate': m.processing_rate,
                        'memory_usage_mb': m.memory_usage_mb,
                        'cpu_usage_percent': m.cpu_usage_percent
                    }
                    for m in list(self.metrics_history)
                ],
                'configuration': self.config,
                'alert_configuration': {
                    'quality_threshold': self.alert_config.quality_threshold,
                    'correlation_threshold': self.alert_config.correlation_threshold,
                    'processing_rate_threshold': self.alert_config.processing_rate_threshold
                }
            }
            
            # Export to file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"phase7_dashboard_export_{timestamp}.{output_format}"
            output_path = Path(f"/tmp/{filename}")
            
            if output_format == 'json':
                with open(output_path, 'w') as f:
                    json.dump(export_data, f, indent=2, default=str)
            else:
                raise ValueError(f"Unsupported export format: {output_format}")
            
            logger.info(f"Dashboard data exported to {output_path}")
            return str(output_path)
            
        except Exception as e:
            logger.error(f"Dashboard export failed: {e}")
            return f"Export failed: {str(e)}"
    
    async def stop_monitoring(self):
        """Stop real-time monitoring"""
        
        self.is_monitoring = False
        
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Real-time monitoring stopped")
    
    def get_dashboard_summary(self) -> Dict[str, Any]:
        """Get dashboard status summary"""
        
        return {
            'dashboard_status': 'active' if self.is_monitoring else 'inactive',
            'web_dashboard_available': WEB_AVAILABLE,
            'metrics_collected': len(self.metrics_history),
            'active_websocket_connections': len(self.websocket_connections),
            'active_alerts': len(self.active_alerts),
            'monitoring_interval_seconds': self.config['monitoring_interval_seconds'],
            'last_metrics_update': self.metrics_history[-1].timestamp.isoformat() if self.metrics_history else None
        }


# Convenience function for quick dashboard startup
async def start_phase7_dashboard(port: int = 8080, config: Optional[Dict[str, Any]] = None) -> bool:
    """
    Convenience function to start Phase 7 real-time analytics dashboard
    
    Args:
        port: Port for web dashboard
        config: Optional dashboard configuration
        
    Returns:
        True if dashboard started successfully
    """
    
    dashboard = RealTimeMLAnalyticsDashboard(config)
    return await dashboard.start_monitoring(port)


# Example usage and testing  
async def main():
    """Demonstrate real-time analytics dashboard"""
    
    print("📊 Phase 7 Real-Time Analytics Dashboard Demo")
    print("=" * 50)
    
    # Initialize dashboard
    dashboard = RealTimeMLAnalyticsDashboard()
    
    # Initialize components
    await dashboard.model_server.load_models()
    
    print("🔧 Dashboard Components Initialized:")
    print(f"  ML Classification Pipeline: ✅")
    print(f"  Production ML Models: ✅")
    print(f"  Cross-Website Analytics: ✅")
    print(f"  Web Dashboard Available: {'✅' if WEB_AVAILABLE else '❌'}")
    
    # Simulate monitoring for demo
    print(f"\n⏱️ Simulating real-time monitoring (10 iterations)...")
    
    for i in range(10):
        # Collect metrics
        metrics = await dashboard._collect_current_metrics()
        
        # Create real-time metrics
        rt_metrics = RealTimeMetrics(
            timestamp=datetime.now(),
            ml_predictions_count=metrics.get('ml_predictions', 0) + i,
            average_quality_score=0.65 + (i * 0.02),  # Simulate improving quality
            active_analyses=i // 2,
            cross_site_correlations=i // 3,
            system_health='healthy',
            processing_rate=2.5 + (i * 0.1),
            memory_usage_mb=1400 + (i * 50),
            cpu_usage_percent=20 + (i * 2)
        )
        
        dashboard.metrics_history.append(rt_metrics)
        
        # Check alerts
        await dashboard._check_alerts(rt_metrics)
        
        print(f"  📊 Iteration {i+1}: Quality={rt_metrics.average_quality_score:.2f}, Rate={rt_metrics.processing_rate:.1f}/s, Health={rt_metrics.system_health}")
        
        await asyncio.sleep(0.5)  # Short delay for demo
    
    # Generate analytics report
    analytics_report = await dashboard.generate_analytics_report()
    
    print(f"\n📈 Real-Time Analytics Report:")
    print(f"  Data Points Collected: {analytics_report['total_data_points']}")
    print(f"  Monitoring Period: {analytics_report['monitoring_period_hours']} hours")
    print(f"  Active Alerts: {analytics_report['alert_summary']['active_alerts']}")
    
    # Show performance trends
    trends = analytics_report.get('performance_trends', {})
    if trends:
        print(f"\n📊 Performance Trends:")
        
        quality_trend = trends.get('quality_trend', {})
        if quality_trend:
            print(f"  Quality: avg={quality_trend['average']:.2f}, range={quality_trend['min']:.2f}-{quality_trend['max']:.2f}")
        
        rate_trend = trends.get('processing_rate_trend', {})
        if rate_trend:
            print(f"  Processing Rate: avg={rate_trend['average']:.1f}/s, peak={rate_trend['peak']:.1f}/s")
    
    # Show recommendations
    recommendations = analytics_report.get('recommendations', [])
    if recommendations:
        print(f"\n💡 Performance Recommendations:")
        for i, rec in enumerate(recommendations, 1):
            print(f"  {i}. {rec}")
    
    # Export dashboard data
    export_path = await dashboard.export_dashboard_data()
    print(f"\n📁 Dashboard data exported to: {export_path}")
    
    # Dashboard summary
    summary = dashboard.get_dashboard_summary()
    print(f"\n📋 Dashboard Summary:")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    
    print(f"\n✅ Phase 7 Real-Time Analytics Dashboard demonstration completed!")
    
    if WEB_AVAILABLE:
        print(f"\n🌐 To start the web dashboard, run:")
        print(f"   python -c \"import asyncio; from demonstrate_phase7_realtime_dashboard import start_phase7_dashboard; asyncio.run(start_phase7_dashboard())\"")
        print(f"   Then visit: http://localhost:8080")
    
    return True


if __name__ == '__main__':
    asyncio.run(main())