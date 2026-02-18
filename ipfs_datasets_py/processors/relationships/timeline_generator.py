#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Timeline Generator

Core business logic for generating and analyzing entity timelines.
Reusable by CLI, MCP tools, and third-party packages.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List
from collections import defaultdict, Counter

logger = logging.getLogger(__name__)


class TimelineGenerator:
    """
    Generates and analyzes entity timelines from document corpora.
    
    Provides methods for:
    - Timeline event extraction
    - Time distribution analysis
    - Temporal clustering
    - Pattern detection
    
    Example:
        >>> generator = TimelineGenerator()
        >>> events = await generator.extract_timeline_events(corpus, "entity_1", ["mention", "action"])
        >>> distribution = generator.analyze_time_distribution(events, "day")
    """
    
    def __init__(self):
        """Initialize the TimelineGenerator."""
        pass
    
    async def extract_entity_timeline_events(
        self,
        corpus: Dict[str, Any],
        entity_id: str,
        event_types: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Extract timeline events for a specific entity.
        
        Args:
            corpus: Dictionary containing document corpus data
            entity_id: Entity to extract timeline for
            event_types: Types of events to extract
            
        Returns:
            List of timeline event dictionaries
        """
        events = []
        
        if "documents" not in corpus:
            return events
        
        for doc_id, document in enumerate(corpus["documents"]):
            content = document.get("content", "")
            title = document.get("title", "")
            date = document.get("date", datetime.now().isoformat())
            
            # Check if entity is mentioned
            if entity_id in content or entity_id in title:
                # Extract events based on types
                for event_type in event_types:
                    if event_type == "mention":
                        events.append({
                            "event_id": f"event_{doc_id}_{event_type}",
                            "entity_id": entity_id,
                            "type": "mention",
                            "timestamp": date,
                            "document_id": doc_id,
                            "description": f"Entity mentioned in {title}",
                            "context": content[:100] if content else title
                        })
                    elif event_type == "action":
                        events.append({
                            "event_id": f"event_{doc_id}_{event_type}",
                            "entity_id": entity_id,
                            "type": "action",
                            "timestamp": date,
                            "document_id": doc_id,
                            "description": f"Entity performed action in {title}",
                            "action_type": "generic_action"
                        })
                    elif event_type == "relationship":
                        events.append({
                            "event_id": f"event_{doc_id}_{event_type}",
                            "entity_id": entity_id,
                            "type": "relationship",
                            "timestamp": date,
                            "document_id": doc_id,
                            "description": f"Relationship event in {title}",
                            "relationship_type": "associated_with"
                        })
                    elif event_type == "property_change":
                        events.append({
                            "event_id": f"event_{doc_id}_{event_type}",
                            "entity_id": entity_id,
                            "type": "property_change",
                            "timestamp": date,
                            "document_id": doc_id,
                            "description": f"Property changed in {title}",
                            "property": "status",
                            "old_value": "unknown",
                            "new_value": "active"
                        })
        
        # Sort events by timestamp
        events.sort(key=lambda e: e["timestamp"])
        
        return events
    
    def analyze_time_distribution(
        self,
        events: List[Dict[str, Any]],
        granularity: str
    ) -> Dict[str, Any]:
        """
        Analyze time distribution of events.
        
        Args:
            events: List of timeline events
            granularity: Time granularity (hour, day, week, month)
            
        Returns:
            Dictionary containing time distribution analysis
        """
        if not events:
            return {}
        
        # Group events by time period
        time_buckets = defaultdict(int)
        event_types_by_time = defaultdict(lambda: defaultdict(int))
        
        for event in events:
            timestamp = event["timestamp"]
            time_key = self._get_time_bucket(timestamp, granularity)
            time_buckets[time_key] += 1
            event_types_by_time[time_key][event["type"]] += 1
        
        return {
            "granularity": granularity,
            "total_events": len(events),
            "time_buckets": dict(time_buckets),
            "event_types_by_time": {k: dict(v) for k, v in event_types_by_time.items()},
            "peak_activity_time": max(time_buckets.items(), key=lambda x: x[1])[0] if time_buckets else None,
            "average_events_per_period": len(events) / len(time_buckets) if time_buckets else 0
        }
    
    def _get_time_bucket(self, timestamp: str, granularity: str) -> str:
        """Get time bucket key based on granularity."""
        try:
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        except:
            dt = datetime.now()
        
        if granularity == "hour":
            return dt.strftime("%Y-%m-%d %H:00")
        elif granularity == "day":
            return dt.strftime("%Y-%m-%d")
        elif granularity == "week":
            return dt.strftime("%Y-W%U")
        elif granularity == "month":
            return dt.strftime("%Y-%m")
        else:
            return dt.strftime("%Y-%m-%d")
    
    def detect_temporal_clusters(
        self,
        events: List[Dict[str, Any]],
        granularity: str
    ) -> List[Dict[str, Any]]:
        """
        Detect temporal clusters of events.
        
        Args:
            events: List of timeline events
            granularity: Time granularity for clustering
            
        Returns:
            List of temporal cluster dictionaries
        """
        if not events:
            return []
        
        # Group events by time bucket
        time_buckets = defaultdict(list)
        for event in events:
            time_key = self._get_time_bucket(event["timestamp"], granularity)
            time_buckets[time_key].append(event)
        
        # Identify clusters (periods with above-average activity)
        event_counts = [len(events) for events in time_buckets.values()]
        avg_count = sum(event_counts) / len(event_counts) if event_counts else 0
        
        clusters = []
        for time_key, bucket_events in time_buckets.items():
            if len(bucket_events) > avg_count * 1.5:  # Threshold for cluster
                cluster_types = Counter(e["type"] for e in bucket_events)
                clusters.append({
                    "cluster_id": f"cluster_{time_key}",
                    "time_period": time_key,
                    "event_count": len(bucket_events),
                    "event_types": dict(cluster_types),
                    "intensity": len(bucket_events) / avg_count if avg_count > 0 else 0,
                    "events": bucket_events
                })
        
        return sorted(clusters, key=lambda c: c["event_count"], reverse=True)
    
    async def get_related_entities(
        self,
        corpus: Dict[str, Any],
        entity_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get entities related to a specific entity.
        
        Args:
            corpus: Dictionary containing document corpus data
            entity_id: Entity to find relations for
            
        Returns:
            List of related entity dictionaries
        """
        related = []
        
        if "documents" not in corpus:
            return related
        
        # Find documents containing the entity
        entity_docs = set()
        for doc_id, document in enumerate(corpus["documents"]):
            content = document.get("content", "") + " " + document.get("title", "")
            if entity_id in content:
                entity_docs.add(doc_id)
        
        # Find other entities in those documents (mock)
        for doc_id in entity_docs:
            for i in range(2):  # Mock related entities
                related.append({
                    "id": f"related_entity_{doc_id}_{i}",
                    "name": f"RelatedEntity_{doc_id}_{i}",
                    "type": "PERSON",
                    "relationship": "co_occurs_with",
                    "strength": 0.7 + (i * 0.1)
                })
        
        # Deduplicate
        seen = set()
        unique_related = []
        for entity in related:
            if entity["id"] not in seen:
                seen.add(entity["id"])
                unique_related.append(entity)
        
        return unique_related[:5]  # Limit results
    
    def detect_temporal_patterns(
        self,
        events: List[Dict[str, Any]],
        granularity: str
    ) -> Dict[str, Any]:
        """
        Detect temporal patterns in events.
        
        Args:
            events: List of timeline events
            granularity: Time granularity for pattern detection
            
        Returns:
            Dictionary of detected temporal patterns
        """
        if not events:
            return {}
        
        # Analyze event frequency patterns
        time_buckets = defaultdict(int)
        for event in events:
            time_key = self._get_time_bucket(event["timestamp"], granularity)
            time_buckets[time_key] += 1
        
        counts = list(time_buckets.values())
        avg_count = sum(counts) / len(counts) if counts else 0
        std_dev = (sum((c - avg_count) ** 2 for c in counts) / len(counts)) ** 0.5 if counts else 0
        
        # Detect pattern types
        patterns = {
            "periodicity": self._detect_periodicity(time_buckets),
            "trend": self._detect_trend(list(time_buckets.values())),
            "bursts": [k for k, v in time_buckets.items() if v > avg_count + (2 * std_dev)],
            "quiet_periods": [k for k, v in time_buckets.items() if v < avg_count - std_dev],
            "statistics": {
                "average_events": avg_count,
                "std_deviation": std_dev,
                "max_events": max(counts) if counts else 0,
                "min_events": min(counts) if counts else 0
            }
        }
        
        return patterns
    
    def _detect_periodicity(self, time_buckets: Dict[str, int]) -> str:
        """Detect if events show periodic pattern."""
        counts = list(time_buckets.values())
        if len(counts) < 3:
            return "insufficient_data"
        
        # Simple periodicity check (would use FFT in production)
        avg = sum(counts) / len(counts)
        variance = sum((c - avg) ** 2 for c in counts) / len(counts)
        
        if variance < avg * 0.1:
            return "regular"
        elif variance > avg * 2:
            return "irregular"
        else:
            return "moderate"
    
    def _detect_trend(self, counts: List[int]) -> str:
        """Detect overall trend in event counts."""
        if len(counts) < 2:
            return "stable"
        
        # Simple trend detection
        first_half = sum(counts[:len(counts)//2]) / (len(counts)//2)
        second_half = sum(counts[len(counts)//2:]) / (len(counts) - len(counts)//2)
        
        if second_half > first_half * 1.2:
            return "increasing"
        elif second_half < first_half * 0.8:
            return "decreasing"
        else:
            return "stable"
