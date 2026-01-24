"""
Performance Optimization Engine for Website GraphRAG Processing

Provides adaptive processing pipeline optimization based on content complexity
and available system resources.
"""

import anyio
import os
import psutil
import logging
from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta

from ipfs_datasets_py.content_discovery import ContentManifest

# Set up logging
logger = logging.getLogger(__name__)


@dataclass
class OptimizedProcessingPlan:
    """Optimized processing plan based on resource analysis"""
    batch_strategy: Dict[str, int]
    cache_strategy: Dict[str, Any]
    processing_order: List[str]
    estimated_time_minutes: float
    memory_requirements_gb: float
    recommended_parallel_workers: int


@dataclass
class ProcessingMetrics:
    """Processing performance metrics"""
    total_items: int
    processing_time_seconds: float
    memory_peak_gb: float
    cpu_usage_percent: float
    success_rate: float
    errors: List[str]


class ContentCacheManager:
    """Manages intelligent caching of processed content"""
    
    def __init__(self):
        self.cache_stats = {}
        self.cache_policies = self._get_default_policies()
    
    def _get_default_policies(self) -> Dict[str, Any]:
        """Get default caching policies"""
        return {
            'html_content_ttl': 3600 * 24,  # 24 hours
            'pdf_content_ttl': 3600 * 24 * 7,  # 7 days
            'media_transcripts_ttl': 3600 * 24 * 30,  # 30 days
            'embeddings_ttl': 3600 * 24 * 14,  # 14 days
            'max_cache_size_gb': 10
        }
    
    async def should_cache_content(self, content_type: str, size_bytes: int) -> bool:
        """Determine if content should be cached based on policies"""
        # Stub implementation
        if content_type == 'html' and size_bytes > 1024 * 1024:  # > 1MB
            return False
        return True
    
    async def get_cache_key(self, url: str, content_type: str) -> str:
        """Generate cache key for content"""
        import hashlib
        key_data = f"{url}:{content_type}"
        return hashlib.md5(key_data.encode()).hexdigest()


class ResourceMonitor:
    """Monitors system resources for optimization decisions"""
    
    def __init__(self):
        self.monitoring_interval = 5  # seconds
        self.history_length = 100
        self.cpu_history = []
        self.memory_history = []
    
    async def get_current_resources(self) -> Dict[str, Any]:
        """Get current system resource utilization"""
        return {
            'cpu_percent': psutil.cpu_percent(interval=1),
            'memory_percent': psutil.virtual_memory().percent,
            'available_memory_gb': psutil.virtual_memory().available / (1024**3),
            'disk_usage_percent': psutil.disk_usage('/').percent,
            'load_average': psutil.getloadavg()[0] if hasattr(psutil, 'getloadavg') else 0
        }
    
    async def predict_resource_usage(self, planned_operations: Dict[str, int]) -> Dict[str, float]:
        """Predict resource usage for planned operations"""
        # Stub implementation with basic estimates
        estimated_cpu = planned_operations.get('media_processing', 0) * 20  # 20% per media file
        estimated_memory = (
            planned_operations.get('pdf_processing', 0) * 0.1 +  # 100MB per PDF
            planned_operations.get('html_processing', 0) * 0.01 +  # 10MB per HTML
            planned_operations.get('media_processing', 0) * 0.5  # 500MB per media file
        )
        
        return {
            'cpu_percent': estimated_cpu,
            'memory_gb': estimated_memory,
            'processing_time_minutes': self._estimate_time(planned_operations)
        }
    
    def _estimate_time(self, operations: Dict[str, int]) -> float:
        """Estimate processing time for operations"""
        # Basic time estimates per operation type
        time_estimates = {
            'html_processing': 0.5,  # 30 seconds per HTML page
            'pdf_processing': 2.0,   # 2 minutes per PDF
            'media_processing': 5.0  # 5 minutes per media file
        }
        
        total_time = sum(
            count * time_estimates.get(op_type, 1.0)
            for op_type, count in operations.items()
        )
        
        return total_time


class WebsiteProcessingOptimizer:
    """
    Advanced performance optimization for large-scale website processing.
    
    Features:
    - Adaptive batching based on content types
    - Dynamic resource allocation
    - Smart caching strategies
    - Processing pipeline optimization
    """
    
    def __init__(self):
        self.metrics_collector = self._create_metrics_collector()
        self.cache_manager = ContentCacheManager()
        self.resource_monitor = ResourceMonitor()
        self.optimization_history = []
    
    def _create_metrics_collector(self):
        """Create metrics collector for tracking performance"""
        # Stub implementation
        return {"processing_times": [], "success_rates": []}
    
    async def optimize_processing_pipeline(
        self,
        content_manifest: ContentManifest,
        available_resources: Optional[Dict[str, Any]] = None
    ) -> OptimizedProcessingPlan:
        """
        Create optimized processing plan based on content and resources
        
        Optimization Strategies:
        1. Content-type prioritization
        2. Parallel processing optimization
        3. Memory usage optimization
        4. Caching strategy selection
        """
        
        if available_resources is None:
            available_resources = await self.resource_monitor.get_current_resources()
        
        # Analyze content complexity
        complexity_analysis = self._analyze_content_complexity(content_manifest)
        
        # Determine optimal batch sizes
        batch_strategy = self._calculate_optimal_batching(
            complexity_analysis, available_resources
        )
        
        # Plan caching strategy
        cache_strategy = self._optimize_cache_usage(content_manifest)
        
        # Create processing order
        processing_order = self._optimize_processing_order(content_manifest)
        
        # Calculate resource requirements
        resource_requirements = await self.resource_monitor.predict_resource_usage({
            'html_processing': len(content_manifest.html_pages),
            'pdf_processing': len(content_manifest.pdf_documents),
            'media_processing': len(content_manifest.media_files)
        })
        
        return OptimizedProcessingPlan(
            batch_strategy=batch_strategy,
            cache_strategy=cache_strategy,
            processing_order=processing_order,
            estimated_time_minutes=resource_requirements['processing_time_minutes'],
            memory_requirements_gb=resource_requirements['memory_gb'],
            recommended_parallel_workers=self._calculate_optimal_workers(
                available_resources, resource_requirements
            )
        )
    
    def _analyze_content_complexity(self, manifest: ContentManifest) -> Dict[str, Any]:
        """Analyze content complexity for optimization planning"""
        total_size = 0
        for asset_list in [manifest.html_pages, manifest.pdf_documents, manifest.media_files]:
            total_size += sum(asset.size_bytes for asset in asset_list)
        
        return {
            'html_complexity': len(manifest.html_pages) * 1.0,  # Base complexity
            'pdf_complexity': len(manifest.pdf_documents) * 2.5,  # More complex
            'media_complexity': sum(
                3.0 if asset.content_type == 'video' else 2.0  # Video most complex
                for asset in manifest.media_files
            ),
            'total_size_mb': total_size / (1024 * 1024),
            'estimated_processing_difficulty': self._calculate_difficulty_score(manifest)
        }
    
    def _calculate_difficulty_score(self, manifest: ContentManifest) -> float:
        """Calculate overall processing difficulty score"""
        # Weights for different content types
        weights = {
            'html': 1.0,
            'pdf': 2.0,
            'audio': 3.0,
            'video': 4.0,
            'image': 1.5
        }
        
        total_difficulty = 0
        total_items = 0
        
        for asset_list in [manifest.html_pages, manifest.pdf_documents, manifest.media_files]:
            for asset in asset_list:
                weight = weights.get(asset.content_type, 1.0)
                size_factor = min(asset.size_bytes / (1024*1024), 100) / 100  # Normalize to 0-1
                total_difficulty += weight * (1 + size_factor)
                total_items += 1
        
        return total_difficulty / max(total_items, 1)
    
    def _calculate_optimal_batching(
        self, 
        complexity_analysis: Dict[str, Any], 
        available_resources: Dict[str, Any]
    ) -> Dict[str, int]:
        """Calculate optimal batch sizes for different content types"""
        
        # Base batch sizes
        base_batches = {
            'html_batch_size': 50,
            'pdf_batch_size': 10,
            'media_batch_size': 3
        }
        
        # Adjust based on available memory
        memory_factor = min(available_resources['available_memory_gb'] / 8.0, 2.0)  # Scale with memory
        
        # Adjust based on content complexity
        difficulty = complexity_analysis['estimated_processing_difficulty']
        complexity_factor = max(0.5, 2.0 - difficulty)  # Lower batch size for complex content
        
        optimized_batches = {}
        for batch_type, base_size in base_batches.items():
            optimized_size = int(base_size * memory_factor * complexity_factor)
            optimized_batches[batch_type] = max(1, min(optimized_size, base_size * 2))
        
        return optimized_batches
    
    def _optimize_cache_usage(self, manifest: ContentManifest) -> Dict[str, Any]:
        """Optimize caching strategy based on content characteristics"""
        
        # Analyze content for caching decisions
        total_content = len(manifest.html_pages) + len(manifest.pdf_documents) + len(manifest.media_files)
        
        # Determine cache priorities
        cache_priorities = {
            'embeddings': 'high' if total_content > 100 else 'medium',
            'processed_text': 'high',  # Always cache processed text
            'media_transcripts': 'high' if len(manifest.media_files) > 10 else 'medium',
            'knowledge_graphs': 'medium'
        }
        
        return {
            'priorities': cache_priorities,
            'max_cache_items': min(total_content * 2, 1000),  # 2x content items, max 1000
            'cache_compression': total_content > 500,  # Enable compression for large sites
            'distributed_cache': total_content > 1000  # Use distributed cache for very large sites
        }
    
    def _optimize_processing_order(self, manifest: ContentManifest) -> List[str]:
        """Determine optimal processing order for content types"""
        
        # Priority order based on processing speed and dependency
        order = []
        
        # Process HTML first (fastest, no dependencies)
        if manifest.html_pages:
            order.append('html')
        
        # Process PDFs next (medium speed, text-based)
        if manifest.pdf_documents:
            order.append('pdf')
        
        # Process media last (slowest, most resource-intensive)
        if manifest.media_files:
            # Separate audio and video for better resource management
            has_audio = any(asset.content_type == 'audio' for asset in manifest.media_files)
            has_video = any(asset.content_type == 'video' for asset in manifest.media_files)
            
            if has_audio:
                order.append('audio')
            if has_video:
                order.append('video')
        
        return order
    
    def _calculate_optimal_workers(
        self, 
        available_resources: Dict[str, Any], 
        requirements: Dict[str, float]
    ) -> int:
        """Calculate optimal number of parallel workers"""
        
        # Consider CPU cores
        cpu_cores = psutil.cpu_count()
        max_cpu_workers = max(1, int(cpu_cores * 0.8))  # Use 80% of cores
        
        # Consider memory constraints
        available_memory = available_resources['available_memory_gb']
        memory_per_worker = max(1.0, requirements['memory_gb'] / 2)  # Estimate memory per worker
        max_memory_workers = max(1, int(available_memory / memory_per_worker))
        
        # Consider current system load
        current_load = available_resources.get('load_average', 0)
        load_factor = max(0.5, 1.0 - (current_load / cpu_cores))
        
        # Take the most restrictive constraint
        optimal_workers = min(max_cpu_workers, max_memory_workers)
        optimal_workers = int(optimal_workers * load_factor)
        
        return max(1, min(optimal_workers, 10))  # Min 1, max 10 workers
    
    async def monitor_processing_performance(
        self,
        processing_plan: OptimizedProcessingPlan,
        actual_metrics: ProcessingMetrics
    ) -> Dict[str, Any]:
        """Monitor and analyze processing performance against plan"""
        
        performance_analysis = {
            'plan_vs_actual': {
                'estimated_time': processing_plan.estimated_time_minutes,
                'actual_time': actual_metrics.processing_time_seconds / 60,
                'time_accuracy': self._calculate_accuracy(
                    processing_plan.estimated_time_minutes,
                    actual_metrics.processing_time_seconds / 60
                ),
                'memory_estimate': processing_plan.memory_requirements_gb,
                'actual_memory': actual_metrics.memory_peak_gb,
                'memory_accuracy': self._calculate_accuracy(
                    processing_plan.memory_requirements_gb,
                    actual_metrics.memory_peak_gb
                )
            },
            'recommendations': []
        }
        
        # Generate optimization recommendations
        if actual_metrics.processing_time_seconds > processing_plan.estimated_time_minutes * 60 * 1.2:
            performance_analysis['recommendations'].append(
                "Processing took longer than expected. Consider increasing batch sizes or parallel workers."
            )
        
        if actual_metrics.memory_peak_gb > processing_plan.memory_requirements_gb * 1.5:
            performance_analysis['recommendations'].append(
                "Memory usage exceeded estimates. Consider reducing batch sizes or enabling memory optimization."
            )
        
        if actual_metrics.success_rate < 0.95:
            performance_analysis['recommendations'].append(
                "Low success rate detected. Review error logs and consider adjusting timeout settings."
            )
        
        # Store metrics for future optimization
        self.optimization_history.append({
            'timestamp': datetime.now(),
            'plan': processing_plan,
            'metrics': actual_metrics,
            'analysis': performance_analysis
        })
        
        return performance_analysis
    
    def _calculate_accuracy(self, estimated: float, actual: float) -> float:
        """Calculate accuracy percentage between estimated and actual values"""
        if estimated == 0:
            return 0.0
        
        error = abs(estimated - actual) / estimated
        accuracy = max(0, 1 - error)
        return accuracy * 100
    
    async def get_optimization_recommendations(self) -> Dict[str, Any]:
        """
        Get optimization recommendations based on current system state.
        
        Returns:
            Dict containing optimization recommendations and settings
        """
        try:
            # Get current resource state
            resources = await self.monitor_resources()
            
            # Analyze historical performance if available
            recommendations = {
                'strategy': 'balanced',  # fast, balanced, comprehensive
                'batch_size': 10,
                'parallel_workers': 4,
                'cache_policy': 'intelligent',
                'optimization_level': 'medium'
            }
            
            # Adjust based on available resources
            if resources['cpu_percent'] < 30 and resources['memory_percent'] < 50:
                recommendations['strategy'] = 'comprehensive'
                recommendations['parallel_workers'] = 6
                recommendations['optimization_level'] = 'high'
            elif resources['cpu_percent'] > 80 or resources['memory_percent'] > 80:
                recommendations['strategy'] = 'fast'
                recommendations['parallel_workers'] = 2
                recommendations['optimization_level'] = 'low'
            
            return recommendations
            
        except Exception as e:
            logger.error(f"Failed to get optimization recommendations: {e}")
            return {
                'strategy': 'balanced',
                'batch_size': 5,
                'parallel_workers': 2,
                'error': str(e)
            }
    
    async def monitor_resources(self) -> Dict[str, Any]:
        """
        Monitor current system resources.
        
        Returns:
            Dict containing current resource usage metrics
        """
        try:
            import psutil
            
            # Get CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # Get memory usage
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            memory_available_gb = memory.available / (1024**3)
            
            # Get disk usage
            disk = psutil.disk_usage('/')
            disk_percent = (disk.used / disk.total) * 100
            disk_free_gb = disk.free / (1024**3)
            
            # Get load average (Unix systems)
            try:
                load_avg = os.getloadavg()
            except (AttributeError, OSError):
                load_avg = [0.0, 0.0, 0.0]
            
            return {
                'cpu_percent': cpu_percent,
                'memory_percent': memory_percent,
                'memory_available_gb': memory_available_gb,
                'disk_percent': disk_percent,
                'disk_free_gb': disk_free_gb,
                'load_average': load_avg,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Resource monitoring failed: {e}")
            return {
                'cpu_percent': 0.0,
                'memory_percent': 0.0,
                'memory_available_gb': 0.0,
                'disk_percent': 0.0,
                'disk_free_gb': 0.0,
                'load_average': [0.0, 0.0, 0.0],
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }


# Example usage and testing
if __name__ == "__main__":
    async def main():
        """Example usage of WebsiteProcessingOptimizer"""
        # Create mock content manifest
        from ipfs_datasets_py.content_discovery import ContentAsset, ContentManifest
        
        mock_manifest = ContentManifest(
            base_url="https://example.com",
            html_pages=[ContentAsset("https://example.com/page1", "html", "text/html", 1024*10)],
            pdf_documents=[ContentAsset("https://example.com/doc1.pdf", "pdf", "application/pdf", 1024*1024)],
            media_files=[ContentAsset("https://example.com/video1.mp4", "video", "video/mp4", 1024*1024*50)],
            total_assets=3,
            discovery_timestamp=datetime.now()
        )
        
        # Initialize optimizer
        optimizer = WebsiteProcessingOptimizer()
        
        # Create optimization plan
        plan = await optimizer.optimize_processing_pipeline(mock_manifest)
        
        print(f"Optimization Plan:")
        print(f"  Batch Strategy: {plan.batch_strategy}")
        print(f"  Estimated Time: {plan.estimated_time_minutes:.1f} minutes")
        print(f"  Memory Required: {plan.memory_requirements_gb:.1f} GB")
        print(f"  Recommended Workers: {plan.recommended_parallel_workers}")
        print(f"  Processing Order: {' -> '.join(plan.processing_order)}")
    
    anyio.run(main())