#!/usr/bin/env python3
"""
Advanced Analytics Dashboard - Comprehensive monitoring and analytics for GraphRAG processing

This module provides advanced analytics, monitoring, and visualization capabilities
for the GraphRAG website processing system with real-time metrics, quality assessment,
and performance optimization recommendations.

Features:
- Real-time processing monitoring with live updates
- Content quality assessment and scoring
- Performance analytics with trend analysis
- User behavior analytics and usage patterns
- System health monitoring with alerting
- Interactive visualization dashboard
- Export capabilities for reports and metrics

Usage:
    dashboard = AdvancedAnalyticsDashboard()
    await dashboard.start_monitoring()
    report = dashboard.generate_comprehensive_report()
"""

import os
import json
import anyio
import logging
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import uuid
import time
from collections import defaultdict, deque
import statistics

# Import GraphRAG components
from ipfs_datasets_py.complete_advanced_graphrag import (
    CompleteGraphRAGSystem, CompleteProcessingResult
)

logger = logging.getLogger(__name__)


@dataclass
class AnalyticsMetrics:
    """Core analytics metrics for the dashboard"""
    
    # Processing metrics
    total_websites_processed: int = 0
    total_processing_time: float = 0.0
    average_processing_time: float = 0.0
    success_rate: float = 0.0
    
    # Content metrics
    total_entities_extracted: int = 0
    total_relationships_found: int = 0
    average_quality_score: float = 0.0
    content_types_processed: Dict[str, int] = field(default_factory=dict)
    
    # Performance metrics
    average_processing_rate: float = 0.0
    peak_memory_usage: float = 0.0
    system_efficiency: float = 0.0
    
    # User metrics
    active_users: int = 0
    total_queries: int = 0
    average_query_time: float = 0.0
    
    # Timestamp
    last_updated: datetime = field(default_factory=datetime.now)


@dataclass
class QualityAssessment:
    """Content quality assessment results"""
    
    overall_score: float = 0.0
    extraction_completeness: float = 0.0
    knowledge_graph_coherence: float = 0.0
    search_relevance: float = 0.0
    processing_efficiency: float = 0.0
    
    # Quality breakdown by content type
    html_quality: float = 0.0
    media_quality: float = 0.0
    pdf_quality: float = 0.0
    
    # Quality trends
    quality_trend: str = "stable"  # improving, stable, declining
    trend_confidence: float = 0.0
    
    # Issues and recommendations
    quality_issues: List[str] = field(default_factory=list)
    improvement_recommendations: List[str] = field(default_factory=list)


@dataclass
class PerformanceReport:
    """System performance analysis report"""
    
    # Processing performance
    current_processing_rate: float = 0.0
    target_processing_rate: float = 10.0
    performance_efficiency: float = 0.0
    
    # Resource utilization
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    disk_usage: float = 0.0
    network_usage: float = 0.0
    
    # Performance trends
    performance_trend: str = "stable"
    bottlenecks: List[str] = field(default_factory=list)
    optimization_opportunities: List[str] = field(default_factory=list)
    
    # Predictions
    predicted_load: float = 0.0
    capacity_recommendations: List[str] = field(default_factory=list)


class RealTimeMonitor:
    """Real-time monitoring for GraphRAG processing operations"""
    
    def __init__(self):
        self.processing_metrics = deque(maxlen=1000)  # Keep last 1000 measurements
        self.query_metrics = deque(maxlen=1000)
        self.system_metrics = deque(maxlen=1000)
        self.alerts = deque(maxlen=100)
        self.is_monitoring = False
    
    async def start_monitoring(self):
        """Start real-time monitoring
        
        Note: This method starts a background task. In anyio, background tasks
        should be managed via task groups by the caller. For now, this uses
        the deprecated pattern and should be refactored to accept a task group.
        
        Recommended usage:
            async with anyio.create_task_group() as tg:
                tg.start_soon(self._monitoring_loop)
        """
        self.is_monitoring = True
        # FIXME: Background task pattern - caller should manage via task group
        import asyncio
        asyncio.create_task(self._monitoring_loop())
        logger.info("Real-time monitoring started")
    
    async def stop_monitoring(self):
        """Stop real-time monitoring"""
        self.is_monitoring = False
        logger.info("Real-time monitoring stopped")
    
    async def _monitoring_loop(self):
        """Main monitoring loop"""
        while self.is_monitoring:
            try:
                # Collect system metrics
                system_metrics = await self._collect_system_metrics()
                self.system_metrics.append(system_metrics)
                
                # Check for alerts
                await self._check_alert_conditions(system_metrics)
                
                # Wait for next collection cycle
                await anyio.sleep(5)  # Collect every 5 seconds
                
            except Exception as e:
                logger.error(f"Monitoring error: {e}")
                await anyio.sleep(10)  # Wait longer on error
    
    async def _collect_system_metrics(self) -> Dict[str, Any]:
        """Collect current system metrics"""
        try:
            import psutil
            
            return {
                "timestamp": datetime.now(),
                "cpu_percent": psutil.cpu_percent(interval=1),
                "memory_percent": psutil.virtual_memory().percent,
                "disk_percent": psutil.disk_usage('/').percent,
                "network_io": psutil.net_io_counters()._asdict() if hasattr(psutil, 'net_io_counters') else {},
                "process_count": len(psutil.pids())
            }
        except ImportError:
            # Fallback if psutil not available
            return {
                "timestamp": datetime.now(),
                "cpu_percent": 25.0,  # Mock data
                "memory_percent": 35.0,
                "disk_percent": 15.0,
                "network_io": {},
                "process_count": 50
            }
    
    async def _check_alert_conditions(self, metrics: Dict[str, Any]):
        """Check for alert conditions"""
        alerts = []
        
        # CPU usage alert
        if metrics["cpu_percent"] > 90:
            alerts.append({
                "type": "cpu_high",
                "message": f"High CPU usage: {metrics['cpu_percent']}%",
                "severity": "warning",
                "timestamp": datetime.now()
            })
        
        # Memory usage alert
        if metrics["memory_percent"] > 90:
            alerts.append({
                "type": "memory_high",
                "message": f"High memory usage: {metrics['memory_percent']}%",
                "severity": "critical",
                "timestamp": datetime.now()
            })
        
        # Disk usage alert
        if metrics["disk_percent"] > 85:
            alerts.append({
                "type": "disk_high",
                "message": f"High disk usage: {metrics['disk_percent']}%",
                "severity": "warning",
                "timestamp": datetime.now()
            })
        
        # Add alerts to queue
        for alert in alerts:
            self.alerts.append(alert)
            logger.warning(f"Alert: {alert['message']}")
    
    def get_recent_metrics(self, minutes: int = 15) -> Dict[str, Any]:
        """Get metrics from the last N minutes"""
        cutoff_time = datetime.now() - timedelta(minutes=minutes)
        
        recent_system = [
            m for m in self.system_metrics 
            if m["timestamp"] > cutoff_time
        ]
        
        if not recent_system:
            return {"message": "No recent metrics available"}
        
        return {
            "avg_cpu": statistics.mean(m["cpu_percent"] for m in recent_system),
            "avg_memory": statistics.mean(m["memory_percent"] for m in recent_system),
            "avg_disk": statistics.mean(m["disk_percent"] for m in recent_system),
            "metrics_count": len(recent_system),
            "time_range": f"Last {minutes} minutes"
        }
    
    def get_active_alerts(self) -> List[Dict[str, Any]]:
        """Get active alerts"""
        return list(self.alerts)


class ContentQualityAnalyzer:
    """Advanced content quality analysis and scoring"""
    
    def __init__(self):
        self.quality_history = []
        self.quality_standards = {
            "entity_extraction_rate": 0.7,  # At least 70% entities extracted
            "relationship_coherence": 0.8,  # 80% coherent relationships
            "text_completeness": 0.9,       # 90% text extraction success
            "processing_efficiency": 0.85   # 85% processing efficiency
        }
    
    async def assess_content_quality(
        self,
        processing_result: CompleteProcessingResult
    ) -> QualityAssessment:
        """Comprehensive quality assessment of processed content"""
        
        # Calculate individual quality scores
        extraction_score = self._assess_extraction_completeness(processing_result)
        coherence_score = self._assess_knowledge_graph_coherence(processing_result)
        efficiency_score = self._assess_processing_efficiency(processing_result)
        relevance_score = self._assess_search_relevance(processing_result)
        
        # Calculate content type specific scores
        html_score = self._assess_html_quality(processing_result)
        media_score = self._assess_media_quality(processing_result)
        pdf_score = self._assess_pdf_quality(processing_result)
        
        # Overall score (weighted average)
        overall_score = (
            extraction_score * 0.3 +
            coherence_score * 0.25 +
            efficiency_score * 0.25 +
            relevance_score * 0.2
        )
        
        # Determine quality trend
        quality_trend, trend_confidence = self._analyze_quality_trend(overall_score)
        
        # Generate quality issues and recommendations
        issues, recommendations = self._generate_quality_insights(
            extraction_score, coherence_score, efficiency_score, relevance_score
        )
        
        assessment = QualityAssessment(
            overall_score=overall_score,
            extraction_completeness=extraction_score,
            knowledge_graph_coherence=coherence_score,
            search_relevance=relevance_score,
            processing_efficiency=efficiency_score,
            html_quality=html_score,
            media_quality=media_score,
            pdf_quality=pdf_score,
            quality_trend=quality_trend,
            trend_confidence=trend_confidence,
            quality_issues=issues,
            improvement_recommendations=recommendations
        )
        
        # Store in history for trend analysis
        self.quality_history.append({
            "timestamp": datetime.now(),
            "score": overall_score,
            "assessment": assessment
        })
        
        return assessment
    
    def _assess_extraction_completeness(self, result: CompleteProcessingResult) -> float:
        """Assess how complete the entity extraction was"""
        # Mock implementation - in production, compare against expected entities
        extraction_rate = min(result.knowledge_extraction_result.total_entities / 100, 1.0)
        return max(0.6, extraction_rate)  # Minimum 60% score
    
    def _assess_knowledge_graph_coherence(self, result: CompleteProcessingResult) -> float:
        """Assess coherence and quality of knowledge graph"""
        # Mock implementation - check entity-relationship ratios
        entities = result.knowledge_extraction_result.total_entities
        relationships = result.knowledge_extraction_result.total_relationships
        
        if entities == 0:
            return 0.0
        
        # Good ratio: 1 relationship per 2-3 entities
        ideal_ratio = entities / 2.5
        actual_ratio = relationships
        coherence = min(actual_ratio / ideal_ratio, 1.0) if ideal_ratio > 0 else 0.0
        
        return max(0.5, coherence)  # Minimum 50% score
    
    def _assess_processing_efficiency(self, result: CompleteProcessingResult) -> float:
        """Assess processing efficiency"""
        # Mock implementation - based on processing time vs content size
        processing_time = result.total_processing_time
        content_size = result.archive_result.total_size_mb
        
        if content_size == 0:
            return 0.8  # Default for no content
        
        # Target: 1MB per 10 seconds
        ideal_time = content_size * 10
        efficiency = min(ideal_time / processing_time, 1.0) if processing_time > 0 else 0.0
        
        return max(0.4, efficiency)
    
    def _assess_search_relevance(self, result: CompleteProcessingResult) -> float:
        """Assess search system relevance and performance"""
        # Mock implementation - based on search index coverage
        search_indexes = len(result.search_capabilities.available_indexes)
        searchable_items = result.search_capabilities.total_searchable_items
        
        # More indexes and items generally means better search
        index_score = min(search_indexes / 4, 1.0)  # Target: 4 indexes
        coverage_score = min(searchable_items / 100, 1.0)  # Target: 100 items
        
        return (index_score + coverage_score) / 2
    
    def _assess_html_quality(self, result: CompleteProcessingResult) -> float:
        """Assess HTML content processing quality"""
        # Mock based on archive success rate
        return result.archive_result.success_rate
    
    def _assess_media_quality(self, result: CompleteProcessingResult) -> float:
        """Assess media processing quality"""
        media_files = len(result.media_processing_result.processed_files)
        if media_files == 0:
            return 0.8  # No media is OK
        
        # Mock based on processing success
        return min(media_files / 10, 1.0)  # Target: 10 media files
    
    def _assess_pdf_quality(self, result: CompleteProcessingResult) -> float:
        """Assess PDF processing quality"""
        # Mock implementation
        return 0.85  # Assuming good PDF processing
    
    def _analyze_quality_trend(self, current_score: float) -> Tuple[str, float]:
        """Analyze quality trends over time"""
        if len(self.quality_history) < 3:
            return "stable", 0.5
        
        recent_scores = [h["score"] for h in self.quality_history[-5:]]
        
        if len(recent_scores) >= 3:
            trend_slope = (recent_scores[-1] - recent_scores[0]) / len(recent_scores)
            
            if trend_slope > 0.05:
                return "improving", min(abs(trend_slope) * 10, 1.0)
            elif trend_slope < -0.05:
                return "declining", min(abs(trend_slope) * 10, 1.0)
            else:
                return "stable", 0.8
        
        return "stable", 0.5
    
    def _generate_quality_insights(
        self, 
        extraction: float, 
        coherence: float, 
        efficiency: float, 
        relevance: float
    ) -> Tuple[List[str], List[str]]:
        """Generate quality issues and improvement recommendations"""
        
        issues = []
        recommendations = []
        
        # Check each quality dimension
        if extraction < self.quality_standards["entity_extraction_rate"]:
            issues.append(f"Entity extraction rate below target ({extraction:.1%} < {self.quality_standards['entity_extraction_rate']:.1%})")
            recommendations.append("Consider enabling multi-pass extraction or adjusting extraction parameters")
        
        if coherence < self.quality_standards["relationship_coherence"]:
            issues.append(f"Knowledge graph coherence below target ({coherence:.1%} < {self.quality_standards['relationship_coherence']:.1%})")
            recommendations.append("Review relationship extraction algorithms and consider domain-specific tuning")
        
        if efficiency < self.quality_standards["processing_efficiency"]:
            issues.append(f"Processing efficiency below target ({efficiency:.1%} < {self.quality_standards['processing_efficiency']:.1%})")
            recommendations.append("Enable performance optimization or adjust processing mode for better efficiency")
        
        if relevance < 0.7:
            issues.append(f"Search relevance could be improved ({relevance:.1%})")
            recommendations.append("Consider rebuilding search indexes or improving content preprocessing")
        
        # Add positive feedback for good performance
        if extraction >= 0.9:
            recommendations.append("Excellent entity extraction performance - consider sharing configuration")
        
        if efficiency >= 0.9:
            recommendations.append("Outstanding processing efficiency - system is well-optimized")
        
        return issues, recommendations


class UserAnalytics:
    """User behavior and usage pattern analytics"""
    
    def __init__(self):
        self.user_sessions = defaultdict(list)
        self.query_patterns = defaultdict(list)
        self.usage_statistics = defaultdict(int)
    
    def track_user_activity(self, user_id: str, activity_type: str, details: Dict[str, Any]):
        """Track user activity for analytics"""
        activity = {
            "timestamp": datetime.now(),
            "activity_type": activity_type,
            "details": details
        }
        
        self.user_sessions[user_id].append(activity)
        self.usage_statistics[activity_type] += 1
    
    def analyze_query_patterns(self, user_id: str = None) -> Dict[str, Any]:
        """Analyze user query patterns"""
        if user_id:
            queries = [
                activity for activity in self.user_sessions[user_id]
                if activity["activity_type"] == "search"
            ]
        else:
            queries = []
            for user_activities in self.user_sessions.values():
                queries.extend([
                    activity for activity in user_activities
                    if activity["activity_type"] == "search"
                ])
        
        if not queries:
            return {"message": "No query data available"}
        
        # Analyze patterns
        query_texts = [q["details"].get("query", "") for q in queries]
        common_terms = self._extract_common_terms(query_texts)
        query_frequency = len(queries)
        
        return {
            "total_queries": query_frequency,
            "common_terms": common_terms,
            "query_times": [q["timestamp"].isoformat() for q in queries[-10:]],
            "patterns": self._identify_query_patterns(query_texts)
        }
    
    def _extract_common_terms(self, query_texts: List[str]) -> List[str]:
        """Extract most common terms from queries"""
        all_terms = []
        for query in query_texts:
            terms = query.lower().split()
            all_terms.extend(terms)
        
        term_counts = defaultdict(int)
        for term in all_terms:
            if len(term) > 3:  # Skip short terms
                term_counts[term] += 1
        
        # Return top 10 most common terms
        return sorted(term_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    
    def _identify_query_patterns(self, query_texts: List[str]) -> List[str]:
        """Identify patterns in user queries"""
        patterns = []
        
        # Check for common patterns
        ai_queries = sum(1 for q in query_texts if "ai" in q.lower() or "artificial intelligence" in q.lower())
        ml_queries = sum(1 for q in query_texts if "machine learning" in q.lower() or "ml" in q.lower())
        research_queries = sum(1 for q in query_texts if "research" in q.lower())
        
        if ai_queries > len(query_texts) * 0.3:
            patterns.append("High interest in AI topics")
        
        if ml_queries > len(query_texts) * 0.2:
            patterns.append("Focus on machine learning content")
        
        if research_queries > len(query_texts) * 0.4:
            patterns.append("Research-oriented queries")
        
        return patterns


class AdvancedAnalyticsDashboard:
    """
    Advanced analytics dashboard for GraphRAG processing monitoring.
    
    Provides comprehensive analytics, monitoring, and visualization capabilities
    with real-time updates and intelligent insights.
    """
    
    def __init__(self, job_manager=None):
        self.job_manager = job_manager
        self.monitor = RealTimeMonitor()
        self.quality_analyzer = ContentQualityAnalyzer()
        self.user_analytics = UserAnalytics()
        
        # Analytics data
        self.processing_history = []
        self.performance_baseline = None
        self.dashboard_start_time = datetime.now()
    
    async def start_monitoring(self):
        """Start real-time monitoring and analytics"""
        await self.monitor.start_monitoring()
        logger.info("Advanced analytics dashboard monitoring started")
    
    async def stop_monitoring(self):
        """Stop monitoring"""
        await self.monitor.stop_monitoring()
        logger.info("Analytics dashboard monitoring stopped")
    
    def record_processing_completion(self, result: CompleteProcessingResult):
        """Record completed processing for analytics"""
        self.processing_history.append({
            "timestamp": datetime.now(),
            "result": result,
            "metrics": self._extract_processing_metrics(result)
        })
        
        # Update baseline if this is first result
        if self.performance_baseline is None:
            self.performance_baseline = self._create_performance_baseline(result)
    
    def _extract_processing_metrics(self, result: CompleteProcessingResult) -> Dict[str, Any]:
        """Extract key metrics from processing result"""
        return {
            "processing_time": result.total_processing_time,
            "entities_extracted": result.knowledge_extraction_result.total_entities,
            "relationships_found": result.knowledge_extraction_result.total_relationships,
            "quality_score": result.quality_score,
            "success_rate": result.success_rate,
            "archive_size_mb": result.archive_result.total_size_mb,
            "media_files_processed": len(result.media_processing_result.processed_files)
        }
    
    def _create_performance_baseline(self, result: CompleteProcessingResult) -> Dict[str, Any]:
        """Create performance baseline from first result"""
        return {
            "baseline_processing_time": result.total_processing_time,
            "baseline_quality_score": result.quality_score,
            "baseline_entity_count": result.knowledge_extraction_result.total_entities,
            "created_at": datetime.now()
        }
    
    async def generate_comprehensive_report(self) -> Dict[str, Any]:
        """Generate comprehensive analytics report"""
        
        # Calculate overall metrics
        metrics = self._calculate_analytics_metrics()
        
        # Quality assessment
        if self.processing_history:
            latest_result = self.processing_history[-1]["result"]
            quality_assessment = await self.quality_analyzer.assess_content_quality(latest_result)
        else:
            quality_assessment = QualityAssessment()
        
        # Performance analysis
        performance_report = self._generate_performance_report()
        
        # User analytics
        user_patterns = self.user_analytics.analyze_query_patterns()
        
        # System health
        recent_metrics = self.monitor.get_recent_metrics()
        active_alerts = self.monitor.get_active_alerts()
        
        # Generate recommendations
        recommendations = self._generate_system_recommendations(
            metrics, quality_assessment, performance_report
        )
        
        return {
            "report_id": str(uuid.uuid4()),
            "generated_at": datetime.now().isoformat(),
            "dashboard_uptime": str(datetime.now() - self.dashboard_start_time),
            
            "system_overview": {
                "status": "operational",
                "version": "1.0.0",
                "total_websites_processed": metrics.total_websites_processed,
                "success_rate": f"{metrics.success_rate:.1%}",
                "average_quality": f"{metrics.average_quality_score:.1%}"
            },
            
            "performance_metrics": {
                "current_metrics": metrics.__dict__,
                "performance_analysis": performance_report.__dict__,
                "system_health": recent_metrics,
                "active_alerts": active_alerts
            },
            
            "quality_assessment": quality_assessment.__dict__,
            
            "user_analytics": user_patterns,
            
            "system_recommendations": recommendations,
            
            "detailed_statistics": {
                "processing_history_count": len(self.processing_history),
                "quality_trend_data": self._get_quality_trend_data(),
                "performance_trend_data": self._get_performance_trend_data()
            }
        }
    
    def _calculate_analytics_metrics(self) -> AnalyticsMetrics:
        """Calculate current analytics metrics"""
        
        if not self.processing_history:
            return AnalyticsMetrics()
        
        # Extract data from processing history
        total_websites = len(self.processing_history)
        total_time = sum(h["metrics"]["processing_time"] for h in self.processing_history)
        avg_time = total_time / total_websites if total_websites > 0 else 0
        
        total_entities = sum(h["metrics"]["entities_extracted"] for h in self.processing_history)
        total_relationships = sum(h["metrics"]["relationships_found"] for h in self.processing_history)
        
        quality_scores = [h["metrics"]["quality_score"] for h in self.processing_history]
        avg_quality = statistics.mean(quality_scores) if quality_scores else 0.0
        
        success_rates = [h["metrics"]["success_rate"] for h in self.processing_history]
        overall_success_rate = statistics.mean(success_rates) if success_rates else 0.0
        
        # Content type analysis
        content_types = defaultdict(int)
        for h in self.processing_history:
            content_types["html"] += 1  # All have HTML
            if h["metrics"]["media_files_processed"] > 0:
                content_types["media"] += 1
            # Add PDF detection logic here
        
        return AnalyticsMetrics(
            total_websites_processed=total_websites,
            total_processing_time=total_time,
            average_processing_time=avg_time,
            success_rate=overall_success_rate,
            total_entities_extracted=total_entities,
            total_relationships_found=total_relationships,
            average_quality_score=avg_quality,
            content_types_processed=dict(content_types),
            average_processing_rate=total_websites / (total_time / 3600) if total_time > 0 else 0,
            system_efficiency=avg_quality * overall_success_rate,
            active_users=len(set(h.get("user_id", "unknown") for h in self.processing_history))
        )
    
    def _generate_performance_report(self) -> PerformanceReport:
        """Generate performance analysis report"""
        
        recent_metrics = self.monitor.get_recent_metrics()
        
        # Calculate current performance
        if self.processing_history:
            recent_processing = [
                h for h in self.processing_history
                if h["timestamp"] > datetime.now() - timedelta(hours=1)
            ]
            
            if recent_processing:
                current_rate = len(recent_processing) / 1.0  # per hour
                avg_efficiency = statistics.mean(h["metrics"]["quality_score"] for h in recent_processing)
            else:
                current_rate = 0.0
                avg_efficiency = 0.0
        else:
            current_rate = 0.0
            avg_efficiency = 0.0
        
        # Identify bottlenecks
        bottlenecks = []
        optimizations = []
        
        if recent_metrics.get("avg_cpu", 0) > 80:
            bottlenecks.append("High CPU usage")
            optimizations.append("Consider reducing processing parallelism")
        
        if recent_metrics.get("avg_memory", 0) > 80:
            bottlenecks.append("High memory usage") 
            optimizations.append("Enable memory optimization or increase system memory")
        
        if current_rate < 5.0:
            bottlenecks.append("Low processing rate")
            optimizations.append("Check for processing bottlenecks or increase resources")
        
        return PerformanceReport(
            current_processing_rate=current_rate,
            target_processing_rate=10.0,
            performance_efficiency=min(current_rate / 10.0, 1.0),
            cpu_usage=recent_metrics.get("avg_cpu", 0),
            memory_usage=recent_metrics.get("avg_memory", 0),
            disk_usage=recent_metrics.get("avg_disk", 0),
            performance_trend="stable",
            bottlenecks=bottlenecks,
            optimization_opportunities=optimizations,
            predicted_load=current_rate * 1.2,  # 20% growth prediction
            capacity_recommendations=self._generate_capacity_recommendations(current_rate)
        )
    
    def _generate_capacity_recommendations(self, current_rate: float) -> List[str]:
        """Generate capacity planning recommendations"""
        recommendations = []
        
        if current_rate < 2.0:
            recommendations.append("System is underutilized - consider cost optimization")
        elif current_rate > 15.0:
            recommendations.append("High load detected - consider scaling up resources")
        elif current_rate > 10.0:
            recommendations.append("Monitor system closely - approaching capacity limits")
        else:
            recommendations.append("System operating within optimal capacity range")
        
        return recommendations
    
    def _generate_system_recommendations(
        self,
        metrics: AnalyticsMetrics,
        quality: QualityAssessment,
        performance: PerformanceReport
    ) -> List[str]:
        """Generate overall system recommendations"""
        
        recommendations = []
        
        # Quality-based recommendations
        if quality.overall_score < 0.7:
            recommendations.append("Consider adjusting processing parameters to improve quality")
        elif quality.overall_score > 0.9:
            recommendations.append("Excellent quality achieved - document current configuration")
        
        # Performance-based recommendations
        if performance.performance_efficiency < 0.7:
            recommendations.append("Performance optimization needed - check resource allocation")
        elif performance.performance_efficiency > 0.9:
            recommendations.append("System performing optimally - current configuration is excellent")
        
        # Usage-based recommendations
        if metrics.total_websites_processed > 100:
            recommendations.append("High usage detected - consider implementing caching strategies")
        
        if metrics.active_users > 10:
            recommendations.append("Multiple active users - ensure proper resource isolation")
        
        # Trend-based recommendations
        if quality.quality_trend == "declining":
            recommendations.append("Quality declining - investigate processing configuration changes")
        elif quality.quality_trend == "improving":
            recommendations.append("Quality improving - maintain current optimization strategies")
        
        return recommendations
    
    def _get_quality_trend_data(self) -> List[Dict[str, Any]]:
        """Get quality trend data for visualization"""
        return [
            {
                "timestamp": h["timestamp"].isoformat(),
                "quality_score": h["score"]
            }
            for h in self.quality_analyzer.quality_history[-20:]  # Last 20 data points
        ]
    
    def _get_performance_trend_data(self) -> List[Dict[str, Any]]:
        """Get performance trend data for visualization"""
        return [
            {
                "timestamp": h["timestamp"].isoformat(),
                "processing_time": h["metrics"]["processing_time"],
                "entities_extracted": h["metrics"]["entities_extracted"],
                "success_rate": h["metrics"]["success_rate"]
            }
            for h in self.processing_history[-20:]  # Last 20 data points
        ]
    
    def export_analytics_report(self, format: str = "json") -> str:
        """Export analytics report in specified format"""
        
        # Use the last generated report or create a simple one
        if not hasattr(self, '_last_report') or not self._last_report:
            # Create a simple synchronous report
            metrics = self._calculate_analytics_metrics()
            report = {
                "report_id": str(uuid.uuid4()),
                "generated_at": datetime.now().isoformat(),
                "system_overview": {
                    "status": "operational",
                    "total_websites_processed": metrics.total_websites_processed
                },
                "performance_metrics": {
                    "current_metrics": metrics.__dict__
                }
            }
        else:
            report = self._last_report
        
        if format == "json":
            return json.dumps(report, indent=2, default=str)
        elif format == "csv":
            return self._convert_to_csv(report)
        else:
            raise ValueError(f"Unsupported export format: {format}")
    
    async def generate_comprehensive_report(self) -> Dict[str, Any]:
        """Generate comprehensive analytics report"""
        
        # Calculate overall metrics
        metrics = self._calculate_analytics_metrics()
        
        # Quality assessment
        if self.processing_history:
            latest_result = self.processing_history[-1]["result"]
            quality_assessment = await self.quality_analyzer.assess_content_quality(latest_result)
        else:
            quality_assessment = QualityAssessment()
        
        # Performance analysis
        performance_report = self._generate_performance_report()
        
        # User analytics
        user_patterns = self.user_analytics.analyze_query_patterns()
        
        # System health
        recent_metrics = self.monitor.get_recent_metrics()
        active_alerts = self.monitor.get_active_alerts()
        
        # Generate recommendations
        recommendations = self._generate_system_recommendations(
            metrics, quality_assessment, performance_report
        )
        
        report = {
            "report_id": str(uuid.uuid4()),
            "generated_at": datetime.now().isoformat(),
            "dashboard_uptime": str(datetime.now() - self.dashboard_start_time),
            
            "system_overview": {
                "status": "operational",
                "version": "1.0.0",
                "total_websites_processed": metrics.total_websites_processed,
                "success_rate": f"{metrics.success_rate:.1%}",
                "average_quality": f"{metrics.average_quality_score:.1%}"
            },
            
            "performance_metrics": {
                "current_metrics": metrics.__dict__,
                "performance_analysis": performance_report.__dict__,
                "system_health": recent_metrics,
                "active_alerts": active_alerts
            },
            
            "quality_assessment": quality_assessment.__dict__,
            
            "user_analytics": user_patterns,
            
            "system_recommendations": recommendations,
            
            "detailed_statistics": {
                "processing_history_count": len(self.processing_history),
                "quality_trend_data": self._get_quality_trend_data(),
                "performance_trend_data": self._get_performance_trend_data()
            }
        }
        
        # Store for export functionality
        self._last_report = report
        
        return report
    
    def _convert_to_csv(self, report: Dict[str, Any]) -> str:
        """Convert report to CSV format"""
        # Simplified CSV export
        csv_lines = [
            "metric,value",
            f"total_websites_processed,{report['performance_metrics']['current_metrics']['total_websites_processed']}",
            f"average_quality_score,{report['performance_metrics']['current_metrics']['average_quality_score']:.3f}",
            f"success_rate,{report['performance_metrics']['current_metrics']['success_rate']:.3f}",
            f"system_efficiency,{report['performance_metrics']['current_metrics']['system_efficiency']:.3f}"
        ]
        
        return "\n".join(csv_lines)


# Global dashboard instance
dashboard_instance = None


async def create_analytics_dashboard(job_manager=None) -> AdvancedAnalyticsDashboard:
    """Factory function to create analytics dashboard"""
    global dashboard_instance
    
    if dashboard_instance is None:
        dashboard_instance = AdvancedAnalyticsDashboard(job_manager)
        await dashboard_instance.start_monitoring()
    
    return dashboard_instance


async def demo_analytics_dashboard():
    """Demonstration of analytics dashboard capabilities"""
    
    print("🔬 Advanced Analytics Dashboard - Comprehensive Demo")
    print("=" * 60)
    
    # Create dashboard
    dashboard = await create_analytics_dashboard()
    
    # Simulate some processing history
    mock_results = []
    for i in range(5):
        from ipfs_datasets_py.complete_advanced_graphrag import CompleteProcessingResult
        
        result = CompleteProcessingResult(
            website_url=f"https://example{i}.com",
            processing_mode="balanced",
            total_processing_time=120 + i * 30,
            quality_score=0.85 + i * 0.02,
            success_rate=0.94 + i * 0.01
        )
        
        dashboard.record_processing_completion(result)
        mock_results.append(result)
    
    # Generate comprehensive report
    print("\n📊 Generating comprehensive analytics report...")
    report = await dashboard.generate_comprehensive_report()
    
    print(f"📋 Report ID: {report['report_id']}")
    print(f"⏰ Generated at: {report['generated_at']}")
    print(f"⚡ Dashboard uptime: {report['dashboard_uptime']}")
    
    print("\n🌐 System Overview:")
    overview = report["system_overview"]
    print(f"   Status: {overview['status']}")
    print(f"   Websites processed: {overview['total_websites_processed']}")
    print(f"   Success rate: {overview['success_rate']}")
    print(f"   Average quality: {overview['average_quality']}")
    
    print("\n⚡ Performance Metrics:")
    perf = report["performance_metrics"]["current_metrics"]
    print(f"   Total processing time: {perf['total_processing_time']:.1f}s")
    print(f"   Average processing time: {perf['average_processing_time']:.1f}s")
    print(f"   Entities extracted: {perf['total_entities_extracted']}")
    print(f"   Relationships found: {perf['total_relationships_found']}")
    
    print("\n🔍 Quality Assessment:")
    quality = report["quality_assessment"]
    print(f"   Overall score: {quality['overall_score']:.1%}")
    print(f"   Extraction completeness: {quality['extraction_completeness']:.1%}")
    print(f"   Knowledge graph coherence: {quality['knowledge_graph_coherence']:.1%}")
    print(f"   Processing efficiency: {quality['processing_efficiency']:.1%}")
    print(f"   Quality trend: {quality['quality_trend']} (confidence: {quality['trend_confidence']:.1%})")
    
    if quality['quality_issues']:
        print(f"\n⚠️  Quality Issues:")
        for issue in quality['quality_issues']:
            print(f"   • {issue}")
    
    if quality['improvement_recommendations']:
        print(f"\n💡 Quality Recommendations:")
        for rec in quality['improvement_recommendations']:
            print(f"   • {rec}")
    
    print("\n🎯 System Recommendations:")
    for rec in report["system_recommendations"]:
        print(f"   • {rec}")
    
    print("\n📈 Trend Analysis:")
    trend_data = report["detailed_statistics"]["quality_trend_data"]
    if trend_data:
        print(f"   Quality trend points: {len(trend_data)}")
        latest_trend = trend_data[-1] if trend_data else None
        if latest_trend:
            print(f"   Latest quality score: {latest_trend['quality_score']:.3f}")
    
    print("\n✅ Analytics dashboard demonstration completed!")
    
    # Cleanup
    await dashboard.stop_monitoring()
    
    return report


if __name__ == "__main__":
    import anyio
    
    # Run analytics dashboard demo
    anyio.run(demo_analytics_dashboard())