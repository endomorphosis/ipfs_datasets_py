#!/usr/bin/env python3
"""
Advanced Performance Optimizer for GraphRAG Systems

This module provides comprehensive performance optimization capabilities for
GraphRAG website processing, including:
- Adaptive processing pipeline optimization
- Resource monitoring and management
- Intelligent batching strategies
- Memory optimization and garbage collection
- Processing time prediction and optimization
- Quality vs. speed trade-off management
"""

import os
import gc
import time
import psutil
import threading
from typing import Dict, List, Optional, Any, Tuple, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
import logging
import json

logger = logging.getLogger(__name__)


@dataclass
class ResourceMetrics:
    """Current system resource metrics"""
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_available_gb: float = 0.0
    disk_usage_percent: float = 0.0
    network_io: Dict[str, int] = field(default_factory=dict)
    process_memory_mb: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ProcessingProfile:
    """Performance profile for different processing scenarios"""
    name: str = "default"
    max_parallel_workers: int = 4
    chunk_size: int = 1000
    memory_threshold_percent: float = 80.0
    cpu_threshold_percent: float = 90.0
    enable_aggressive_gc: bool = False
    quality_vs_speed_ratio: float = 0.7  # 0.0 = speed, 1.0 = quality
    batch_size: int = 10
    processing_timeout_seconds: int = 300
    enable_caching: bool = True
    cache_size_mb: int = 100


@dataclass
class OptimizationRecommendation:
    """Recommendation for performance optimization"""
    category: str  # 'memory', 'cpu', 'io', 'configuration'
    priority: str  # 'critical', 'high', 'medium', 'low'
    description: str
    action: str
    impact_estimate: str
    implementation_difficulty: str


class AdvancedPerformanceOptimizer:
    """
    Advanced performance optimizer for GraphRAG systems with adaptive
    optimization strategies and comprehensive resource monitoring.
    """
    
    def __init__(self, target_profile: ProcessingProfile = None):
        """
        Initialize the performance optimizer
        
        Args:
            target_profile: Target processing profile for optimization
        """
        self.target_profile = target_profile or ProcessingProfile()
        
        # Resource monitoring
        self.resource_history = deque(maxlen=100)  # Keep last 100 measurements
        self.monitoring_active = False
        self.monitoring_thread = None
        self.monitoring_interval = 5.0  # seconds
        
        # Performance tracking
        self.processing_history = deque(maxlen=50)  # Last 50 processing operations
        
        # Current optimization state
        self.current_recommendations = []
        self.applied_optimizations = []
        
        # Adaptive parameters
        self.adaptive_parameters = {
            'current_batch_size': self.target_profile.batch_size,
            'current_workers': self.target_profile.max_parallel_workers,
            'current_quality_threshold': 0.6,
            'gc_frequency': 10,  # Run GC every N operations
            'operation_count': 0
        }
        
        logger.info(f"AdvancedPerformanceOptimizer initialized with profile: {self.target_profile.name}")
    
    def start_monitoring(self):
        """Start continuous resource monitoring"""
        if self.monitoring_active:
            logger.warning("Monitoring already active")
            return
        
        self.monitoring_active = True
        self.monitoring_thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self.monitoring_thread.start()
        
        logger.info("Resource monitoring started")
    
    def stop_monitoring(self):
        """Stop resource monitoring"""
        if not self.monitoring_active:
            return
        
        self.monitoring_active = False
        if self.monitoring_thread:
            self.monitoring_thread.join(timeout=10)
        
        logger.info("Resource monitoring stopped")
    
    def _monitoring_loop(self):
        """Continuous monitoring loop"""
        while self.monitoring_active:
            try:
                metrics = self._collect_resource_metrics()
                self.resource_history.append(metrics)
                
                # Check for critical resource conditions
                self._check_critical_conditions(metrics)
                
                time.sleep(self.monitoring_interval)
                
            except Exception as e:
                logger.error(f"Monitoring loop error: {e}")
                time.sleep(self.monitoring_interval * 2)  # Back off on error
    
    def _collect_resource_metrics(self) -> ResourceMetrics:
        """Collect current system resource metrics"""
        try:
            # System metrics
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory_info = psutil.virtual_memory()
            disk_info = psutil.disk_usage('/')
            
            # Process metrics
            process = psutil.Process()
            process_memory = process.memory_info().rss / (1024 * 1024)  # MB
            
            # Network I/O (optional)
            try:
                net_io = psutil.net_io_counters()
                network_io = {
                    'bytes_sent': net_io.bytes_sent,
                    'bytes_recv': net_io.bytes_recv
                }
            except:
                network_io = {}
            
            return ResourceMetrics(
                cpu_percent=cpu_percent,
                memory_percent=memory_info.percent,
                memory_available_gb=memory_info.available / (1024**3),
                disk_usage_percent=disk_info.percent,
                network_io=network_io,
                process_memory_mb=process_memory,
                timestamp=datetime.now()
            )
            
        except Exception as e:
            logger.error(f"Failed to collect resource metrics: {e}")
            return ResourceMetrics()
    
    def _check_critical_conditions(self, metrics: ResourceMetrics):
        """Check for critical resource conditions and take immediate action"""
        
        # Critical memory condition
        if metrics.memory_percent > 95.0:
            logger.warning(f"Critical memory usage: {metrics.memory_percent:.1f}%")
            self._emergency_memory_cleanup()
        
        # High memory condition
        elif metrics.memory_percent > self.target_profile.memory_threshold_percent:
            logger.info(f"High memory usage: {metrics.memory_percent:.1f}%, triggering GC")
            gc.collect()
        
        # Critical CPU condition
        if metrics.cpu_percent > 95.0:
            logger.warning(f"Critical CPU usage: {metrics.cpu_percent:.1f}%")
            self._reduce_processing_load()
    
    def optimize_for_processing(
        self,
        content_count: int,
        estimated_content_size_mb: float,
        processing_type: str = "standard"
    ) -> Dict[str, Any]:
        """
        Optimize system configuration for upcoming processing task
        
        Args:
            content_count: Number of content items to process
            estimated_content_size_mb: Estimated total content size in MB
            processing_type: Type of processing ('fast', 'standard', 'quality')
            
        Returns:
            Optimized configuration parameters
        """
        logger.info(f"Optimizing for {content_count} items, ~{estimated_content_size_mb:.1f}MB, type: {processing_type}")
        
        # Get current resources
        current_metrics = self._collect_resource_metrics()
        
        # Calculate optimal parameters
        optimal_config = self._calculate_optimal_config(
            content_count, estimated_content_size_mb, processing_type, current_metrics
        )
        
        # Apply optimizations
        self._apply_configuration(optimal_config)
        
        # Generate recommendations
        recommendations = self._generate_recommendations(current_metrics, optimal_config)
        
        return {
            'optimal_config': optimal_config,
            'recommendations': recommendations,
            'current_metrics': current_metrics.__dict__,
            'estimated_processing_time': self._estimate_processing_time(
                content_count, estimated_content_size_mb, optimal_config
            )
        }
    
    def _calculate_optimal_config(
        self,
        content_count: int,
        estimated_size_mb: float,
        processing_type: str,
        metrics: ResourceMetrics
    ) -> Dict[str, Any]:
        """Calculate optimal configuration based on current conditions"""
        
        # Base configuration
        config = {
            'batch_size': self.target_profile.batch_size,
            'max_workers': self.target_profile.max_parallel_workers,
            'chunk_size': self.target_profile.chunk_size,
            'enable_caching': self.target_profile.enable_caching,
            'quality_threshold': 0.6,
            'processing_timeout': self.target_profile.processing_timeout_seconds,
            'gc_frequency': 10
        }
        
        # Adjust based on available memory
        available_memory_gb = metrics.memory_available_gb
        
        if available_memory_gb < 1.0:  # Less than 1GB available
            # Conservative settings
            config['batch_size'] = min(config['batch_size'], 5)
            config['max_workers'] = min(config['max_workers'], 2)
            config['enable_caching'] = False
            config['gc_frequency'] = 5
            
        elif available_memory_gb > 4.0:  # More than 4GB available
            # Aggressive settings
            config['batch_size'] = min(config['batch_size'] * 2, 50)
            config['max_workers'] = min(config['max_workers'] * 2, psutil.cpu_count())
            config['enable_caching'] = True
            
        # Adjust based on CPU load
        if metrics.cpu_percent > 80:
            config['max_workers'] = max(1, config['max_workers'] // 2)
        elif metrics.cpu_percent < 30:
            config['max_workers'] = min(config['max_workers'] * 2, psutil.cpu_count())
        
        # Adjust based on content characteristics
        if content_count > 100:
            # Large batch - optimize for throughput
            config['batch_size'] = min(config['batch_size'] * 2, content_count // 10)
            config['quality_threshold'] = 0.5  # Lower quality threshold for speed
            
        if estimated_size_mb > 100:
            # Large content - optimize memory usage
            config['chunk_size'] = min(config['chunk_size'], 500)
            config['gc_frequency'] = 5
            
        # Processing type adjustments
        if processing_type == "fast":
            config['quality_threshold'] = 0.4
            config['processing_timeout'] = 60
            config['enable_caching'] = False
            
        elif processing_type == "quality":
            config['quality_threshold'] = 0.8
            config['processing_timeout'] = 600
            config['batch_size'] = max(1, config['batch_size'] // 2)
            
        return config
    
    def _apply_configuration(self, config: Dict[str, Any]):
        """Apply configuration to adaptive parameters"""
        self.adaptive_parameters.update({
            'current_batch_size': config['batch_size'],
            'current_workers': config['max_workers'],
            'current_quality_threshold': config['quality_threshold'],
            'gc_frequency': config['gc_frequency']
        })
        
        logger.info(f"Applied configuration: batch_size={config['batch_size']}, "
                   f"workers={config['max_workers']}, quality={config['quality_threshold']:.2f}")
    
    def _generate_recommendations(
        self,
        metrics: ResourceMetrics,
        config: Dict[str, Any]
    ) -> List[OptimizationRecommendation]:
        """Generate optimization recommendations based on current state"""
        
        recommendations = []
        
        # Memory recommendations
        if metrics.memory_percent > 85:
            recommendations.append(OptimizationRecommendation(
                category="memory",
                priority="high",
                description=f"High memory usage: {metrics.memory_percent:.1f}%",
                action="Reduce batch size and enable aggressive garbage collection",
                impact_estimate="10-30% memory reduction",
                implementation_difficulty="Easy"
            ))
        
        # CPU recommendations
        if metrics.cpu_percent > 90:
            recommendations.append(OptimizationRecommendation(
                category="cpu",
                priority="high",
                description=f"High CPU usage: {metrics.cpu_percent:.1f}%",
                action="Reduce number of parallel workers",
                impact_estimate="20-40% CPU reduction",
                implementation_difficulty="Easy"
            ))
        
        # Configuration recommendations
        if config['batch_size'] < 5 and metrics.memory_available_gb > 2:
            recommendations.append(OptimizationRecommendation(
                category="configuration",
                priority="medium",
                description="Low batch size with available memory",
                action="Increase batch size to improve throughput",
                impact_estimate="15-25% speed improvement",
                implementation_difficulty="Easy"
            ))
        
        # Processing recommendations based on history
        if len(self.processing_history) > 10:
            avg_processing_time = sum(h['duration'] for h in self.processing_history) / len(self.processing_history)
            
            if avg_processing_time > 30:  # Slow processing
                recommendations.append(OptimizationRecommendation(
                    category="performance",
                    priority="medium",
                    description=f"Slow average processing: {avg_processing_time:.1f}s per batch",
                    action="Consider reducing quality threshold or enabling caching",
                    impact_estimate="20-40% speed improvement",
                    implementation_difficulty="Medium"
                ))
        
        self.current_recommendations = recommendations
        return recommendations
    
    def _estimate_processing_time(
        self,
        content_count: int,
        estimated_size_mb: float,
        config: Dict[str, Any]
    ) -> Dict[str, float]:
        """Estimate processing time based on configuration and historical data"""
        
        # Base processing rates (items per second)
        base_rate_per_worker = 0.5  # Conservative estimate
        
        # Adjust based on configuration
        workers = config['max_workers']
        batch_size = config['batch_size']
        quality_threshold = config['quality_threshold']
        
        # Quality adjustment (higher quality = slower processing)
        quality_factor = 1.0 + (quality_threshold - 0.5) * 0.5
        
        # Size adjustment (larger content = slower processing)
        size_factor = 1.0 + (estimated_size_mb / 100) * 0.2
        
        # Calculate estimated time
        effective_rate = (base_rate_per_worker * workers) / (quality_factor * size_factor)
        estimated_seconds = content_count / effective_rate
        
        # Add overhead for batching
        batch_overhead = (content_count / batch_size) * 2  # 2 seconds per batch overhead
        total_seconds = estimated_seconds + batch_overhead
        
        return {
            'estimated_seconds': total_seconds,
            'estimated_minutes': total_seconds / 60,
            'estimated_hours': total_seconds / 3600,
            'items_per_second': effective_rate,
            'confidence': 0.7  # Estimation confidence
        }
    
    def track_processing_operation(
        self,
        operation_type: str,
        duration: float,
        items_processed: int,
        success_rate: float,
        memory_used_mb: float = 0
    ):
        """Track a processing operation for performance analysis"""
        
        operation_record = {
            'timestamp': datetime.now().isoformat(),
            'operation_type': operation_type,
            'duration': duration,
            'items_processed': items_processed,
            'items_per_second': items_processed / max(duration, 0.1),
            'success_rate': success_rate,
            'memory_used_mb': memory_used_mb
        }
        
        self.processing_history.append(operation_record)
        self.adaptive_parameters['operation_count'] += 1
        
        # Trigger garbage collection if needed
        if (self.adaptive_parameters['operation_count'] % 
            self.adaptive_parameters['gc_frequency'] == 0):
            gc.collect()
        
        # Adaptive optimization based on recent performance
        if len(self.processing_history) >= 5:
            self._adaptive_optimization()
        
        logger.info(f"Tracked operation: {operation_type}, "
                   f"{duration:.2f}s, {items_processed} items, "
                   f"{success_rate:.1%} success rate")
    
    def _adaptive_optimization(self):
        """Perform adaptive optimization based on recent performance"""
        
        recent_operations = list(self.processing_history)[-5:]
        
        # Calculate performance metrics
        avg_items_per_second = sum(op['items_per_second'] for op in recent_operations) / len(recent_operations)
        avg_success_rate = sum(op['success_rate'] for op in recent_operations) / len(recent_operations)
        avg_memory_used = sum(op['memory_used_mb'] for op in recent_operations) / len(recent_operations)
        
        # Get current resource state
        current_metrics = self._collect_resource_metrics()
        
        # Adaptive adjustments
        if avg_success_rate < 0.8:  # Low success rate
            # Reduce load
            self.adaptive_parameters['current_batch_size'] = max(1, 
                self.adaptive_parameters['current_batch_size'] - 2)
            self.adaptive_parameters['current_workers'] = max(1,
                self.adaptive_parameters['current_workers'] - 1)
            
        elif avg_success_rate > 0.95 and current_metrics.memory_percent < 70:
            # High success rate and low memory - can increase load
            self.adaptive_parameters['current_batch_size'] = min(50,
                self.adaptive_parameters['current_batch_size'] + 2)
            
        # Memory-based adjustments
        if current_metrics.memory_percent > 85:
            self.adaptive_parameters['gc_frequency'] = max(1,
                self.adaptive_parameters['gc_frequency'] - 2)
        elif current_metrics.memory_percent < 50:
            self.adaptive_parameters['gc_frequency'] = min(20,
                self.adaptive_parameters['gc_frequency'] + 2)
        
        logger.debug(f"Adaptive optimization applied: batch_size={self.adaptive_parameters['current_batch_size']}, "
                    f"workers={self.adaptive_parameters['current_workers']}")
    
    def _emergency_memory_cleanup(self):
        """Emergency memory cleanup procedures"""
        logger.warning("Executing emergency memory cleanup")
        
        # Force garbage collection
        collected = gc.collect()
        logger.info(f"Garbage collection freed {collected} objects")
        
        # Clear processing history to free memory
        if len(self.processing_history) > 10:
            # Keep only the last 10 records
            self.processing_history = deque(list(self.processing_history)[-10:], maxlen=50)
        
        # Clear resource history
        if len(self.resource_history) > 20:
            self.resource_history = deque(list(self.resource_history)[-20:], maxlen=100)
        
        # Reduce adaptive parameters
        self.adaptive_parameters['current_batch_size'] = max(1,
            self.adaptive_parameters['current_batch_size'] // 2)
        self.adaptive_parameters['current_workers'] = max(1,
            self.adaptive_parameters['current_workers'] // 2)
        self.adaptive_parameters['gc_frequency'] = 1
        
        logger.info("Emergency memory cleanup completed")
    
    def _reduce_processing_load(self):
        """Reduce processing load due to high CPU usage"""
        logger.info("Reducing processing load due to high CPU usage")
        
        self.adaptive_parameters['current_workers'] = max(1,
            self.adaptive_parameters['current_workers'] - 1)
        self.adaptive_parameters['current_batch_size'] = max(1,
            self.adaptive_parameters['current_batch_size'] - 2)
        
        # Brief pause to let CPU recover
        time.sleep(2)
    
    def get_current_optimization_state(self) -> Dict[str, Any]:
        """Get current optimization state and recommendations"""
        
        current_metrics = self._collect_resource_metrics()
        
        return {
            'current_metrics': current_metrics.__dict__,
            'adaptive_parameters': self.adaptive_parameters.copy(),
            'target_profile': self.target_profile.__dict__,
            'recommendations': [rec.__dict__ for rec in self.current_recommendations],
            'processing_history_length': len(self.processing_history),
            'resource_history_length': len(self.resource_history),
            'monitoring_active': self.monitoring_active
        }
    
    def get_performance_report(self) -> Dict[str, Any]:
        """Generate comprehensive performance report"""
        
        if not self.processing_history:
            return {'error': 'No processing history available'}
        
        operations = list(self.processing_history)
        
        # Calculate statistics
        total_items = sum(op['items_processed'] for op in operations)
        total_duration = sum(op['duration'] for op in operations)
        avg_items_per_second = sum(op['items_per_second'] for op in operations) / len(operations)
        avg_success_rate = sum(op['success_rate'] for op in operations) / len(operations)
        
        # Recent vs. historical performance
        recent_ops = operations[-5:] if len(operations) >= 5 else operations
        recent_avg_speed = sum(op['items_per_second'] for op in recent_ops) / len(recent_ops)
        
        # Resource utilization
        if self.resource_history:
            recent_resources = list(self.resource_history)[-5:]
            avg_cpu = sum(r.cpu_percent for r in recent_resources) / len(recent_resources)
            avg_memory = sum(r.memory_percent for r in recent_resources) / len(recent_resources)
        else:
            avg_cpu = 0
            avg_memory = 0
        
        return {
            'summary': {
                'total_operations': len(operations),
                'total_items_processed': total_items,
                'total_duration_minutes': total_duration / 60,
                'average_items_per_second': avg_items_per_second,
                'average_success_rate': avg_success_rate,
                'recent_performance_trend': 'improving' if recent_avg_speed > avg_items_per_second else 'declining'
            },
            'resource_utilization': {
                'average_cpu_percent': avg_cpu,
                'average_memory_percent': avg_memory,
                'current_batch_size': self.adaptive_parameters['current_batch_size'],
                'current_workers': self.adaptive_parameters['current_workers']
            },
            'recommendations': [rec.__dict__ for rec in self.current_recommendations],
            'optimization_opportunities': self._identify_optimization_opportunities(operations)
        }
    
    def _identify_optimization_opportunities(self, operations: List[Dict]) -> List[str]:
        """Identify optimization opportunities based on performance history"""
        
        opportunities = []
        
        if len(operations) < 3:
            return opportunities
        
        # Check for consistent slow performance
        slow_operations = [op for op in operations if op['items_per_second'] < 0.5]
        if len(slow_operations) > len(operations) * 0.5:
            opportunities.append("Consider upgrading hardware or reducing quality settings")
        
        # Check for memory issues
        high_memory_ops = [op for op in operations if op.get('memory_used_mb', 0) > 500]
        if len(high_memory_ops) > len(operations) * 0.3:
            opportunities.append("Consider implementing memory streaming or reducing batch sizes")
        
        # Check for success rate issues
        failed_ops = [op for op in operations if op['success_rate'] < 0.9]
        if len(failed_ops) > len(operations) * 0.2:
            opportunities.append("Investigate and fix processing errors to improve throughput")
        
        # Check for underutilized resources
        current_metrics = self._collect_resource_metrics()
        if current_metrics.cpu_percent < 50 and current_metrics.memory_percent < 60:
            opportunities.append("System resources are underutilized - consider increasing batch size or workers")
        
        return opportunities
    
    def export_performance_data(self, filepath: str = None) -> str:
        """Export performance data for analysis"""
        
        if filepath is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = f"performance_data_{timestamp}.json"
        
        data = {
            'export_timestamp': datetime.now().isoformat(),
            'processing_history': list(self.processing_history),
            'resource_history': [r.__dict__ for r in self.resource_history],
            'adaptive_parameters': self.adaptive_parameters.copy(),
            'target_profile': self.target_profile.__dict__,
            'recommendations': [rec.__dict__ for rec in self.current_recommendations]
        }
        
        try:
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            
            logger.info(f"Performance data exported to: {filepath}")
            return filepath
            
        except Exception as e:
            logger.error(f"Failed to export performance data: {e}")
            raise


# Example usage and testing
if __name__ == "__main__":
    def test_performance_optimizer():
        """Test the advanced performance optimizer"""
        
        print("⚡ Advanced Performance Optimizer Test")
        print("=" * 60)
        
        # Create custom processing profile
        profile = ProcessingProfile(
            name="test_profile",
            max_parallel_workers=2,
            batch_size=5,
            memory_threshold_percent=75.0,
            quality_vs_speed_ratio=0.6
        )
        
        # Initialize optimizer
        optimizer = AdvancedPerformanceOptimizer(profile)
        
        # Start monitoring
        optimizer.start_monitoring()
        time.sleep(2)  # Let monitoring collect some data
        
        print("📊 Initial System State:")
        state = optimizer.get_current_optimization_state()
        metrics = state['current_metrics']
        print(f"   • CPU: {metrics['cpu_percent']:.1f}%")
        print(f"   • Memory: {metrics['memory_percent']:.1f}%")
        print(f"   • Available Memory: {metrics['memory_available_gb']:.2f} GB")
        
        # Optimize for a sample processing task
        print("\n🔧 Optimizing for Sample Task:")
        optimization = optimizer.optimize_for_processing(
            content_count=25,
            estimated_content_size_mb=50.0,
            processing_type="standard"
        )
        
        optimal_config = optimization['optimal_config']
        print(f"   • Recommended batch size: {optimal_config['batch_size']}")
        print(f"   • Recommended workers: {optimal_config['max_workers']}")
        print(f"   • Quality threshold: {optimal_config['quality_threshold']:.2f}")
        print(f"   • Enable caching: {optimal_config['enable_caching']}")
        
        # Show time estimates
        time_estimate = optimization['estimated_processing_time']
        print(f"\n⏱️  Time Estimates:")
        print(f"   • Estimated duration: {time_estimate['estimated_minutes']:.1f} minutes")
        print(f"   • Processing rate: {time_estimate['items_per_second']:.2f} items/sec")
        print(f"   • Confidence: {time_estimate['confidence']:.1%}")
        
        # Show recommendations
        recommendations = optimization['recommendations']
        if recommendations:
            print(f"\n💡 Recommendations ({len(recommendations)}):")
            for i, rec in enumerate(recommendations, 1):
                print(f"   {i}. [{rec['priority'].upper()}] {rec['description']}")
                print(f"      Action: {rec['action']}")
                print(f"      Impact: {rec['impact_estimate']}")
        
        # Simulate some processing operations
        print("\n🏃 Simulating Processing Operations:")
        
        for i in range(3):
            # Simulate processing
            start_time = time.time()
            time.sleep(1)  # Simulate work
            duration = time.time() - start_time
            
            # Track the operation
            optimizer.track_processing_operation(
                operation_type="test_processing",
                duration=duration,
                items_processed=5,
                success_rate=0.9,
                memory_used_mb=50
            )
            
            print(f"   • Operation {i+1}: {duration:.2f}s, 5 items, 90% success")
        
        # Generate performance report
        time.sleep(1)
        
        print("\n📈 Performance Report:")
        report = optimizer.get_performance_report()
        
        summary = report['summary']
        print(f"   • Total operations: {summary['total_operations']}")
        print(f"   • Items processed: {summary['total_items_processed']}")
        print(f"   • Avg items/sec: {summary['average_items_per_second']:.2f}")
        print(f"   • Avg success rate: {summary['average_success_rate']:.1%}")
        
        utilization = report['resource_utilization']
        print(f"   • Current batch size: {utilization['current_batch_size']}")
        print(f"   • Current workers: {utilization['current_workers']}")
        
        # Show optimization opportunities
        opportunities = report.get('optimization_opportunities', [])
        if opportunities:
            print(f"\n🎯 Optimization Opportunities:")
            for opp in opportunities:
                print(f"   • {opp}")
        
        # Export performance data
        export_file = optimizer.export_performance_data()
        print(f"\n💾 Performance data exported to: {export_file}")
        
        # Stop monitoring
        optimizer.stop_monitoring()
        
        print("\n✅ Performance optimizer test completed!")
        
        return optimizer
    
    # Run test
    test_performance_optimizer()