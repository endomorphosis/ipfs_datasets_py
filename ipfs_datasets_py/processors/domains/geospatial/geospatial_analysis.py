"""Geospatial analysis core implementation.

This module contains the reusable geospatial analysis logic.
Thin wrappers in `ipfs_datasets_py.mcp_server.tools` should delegate to these
functions.

Note: This is intentionally a lightweight, dependency-free implementation that
uses simple pattern matching and a small built-in coordinate mapping.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class GeographicEntity:
    entity: str
    frequency: int
    documents: List[Dict[str, Any]]
    confidence: float
    coordinates: Optional[List[float]]
    context_snippet: str


class GeospatialAnalysisTools:
    """Tools for geographic entity extraction and spatial-temporal analysis."""

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        # Mock geocoding database for demonstration
        self.location_coordinates: Dict[str, List[float]] = {
            "new york": [40.7128, -74.0060],
            "new york city": [40.7128, -74.0060],
            "nyc": [40.7128, -74.0060],
            "manhattan": [40.7831, -73.9712],
            "wall street": [40.7074, -74.0113],
            "washington dc": [38.9072, -77.0369],
            "washington": [38.9072, -77.0369],
            "capitol hill": [38.8899, -77.0091],
            "london": [51.5074, -0.1278],
            "london financial district": [51.5138, -0.0981],
            "the city": [51.5138, -0.0981],
            "silicon valley": [37.4419, -122.1430],
            "san francisco": [37.7749, -122.4194],
            "chicago": [41.8781, -87.6298],
            "los angeles": [34.0522, -118.2437],
            "boston": [42.3601, -71.0589],
            "federal reserve": [38.8921, -77.0450],
            "nyse": [40.7074, -74.0113],
            "nasdaq": [40.7589, -73.9851],
            "goldman sachs": [40.7505, -73.9934],
            "jpmorgan": [40.7505, -73.9782],
            "bank of england": [51.5142, -0.0881],
            "european central bank": [50.1109, 8.6821],
            "tokyo": [35.6762, 139.6503],
            "hong kong": [22.3193, 114.1694],
            "singapore": [1.3521, 103.8198],
        }

    def extract_geographic_entities(
        self,
        corpus_data: str | Dict[str, Any] | List[Dict[str, Any]],
        confidence_threshold: float = 0.7,
        include_coordinates: bool = True,
    ) -> Dict[str, Any]:
        """Extract geographic entities from corpus data and geocode them."""
        try:
            corpus = json.loads(corpus_data) if isinstance(corpus_data, str) else corpus_data

            entity_frequencies: Dict[str, Dict[str, Any]] = {}
            total_documents = len(corpus) if isinstance(corpus, list) else 1
            documents = corpus if isinstance(corpus, list) else [corpus]

            for doc_idx, document in enumerate(documents):
                content = (document.get("content", "") or "") + " " + (document.get("title", "") or "")
                locations = self._extract_locations_from_text(content)

                for location in locations:
                    location_key = location.lower()
                    coordinates = None
                    if include_coordinates and location_key in self.location_coordinates:
                        coordinates = self.location_coordinates[location_key]

                    confidence = self._calculate_location_confidence(location, content)
                    if confidence < confidence_threshold:
                        continue

                    if location_key not in entity_frequencies:
                        entity_frequencies[location_key] = {
                            "entity": location,
                            "frequency": 0,
                            "documents": [],
                            "confidence": confidence,
                            "coordinates": coordinates,
                            "context_snippet": self._extract_context(location, content),
                        }

                    entity_frequencies[location_key]["frequency"] += 1
                    entity_frequencies[location_key]["documents"].append(
                        {
                            "id": document.get("id", doc_idx),
                            "title": document.get("title", f"Document {doc_idx}"),
                        }
                    )

            entities_list = list(entity_frequencies.values())
            entities_list.sort(key=lambda x: x["frequency"], reverse=True)

            regions = set()
            for entity in entities_list:
                if entity.get("coordinates"):
                    lat, lng = entity["coordinates"]
                    if lat > 49:
                        regions.add("Europe" if lng < 30 else "Asia")
                    elif lat > 25:
                        regions.add("North America")
                    else:
                        regions.add("Other")

            mappable_entities = sum(1 for e in entities_list if e.get("coordinates"))

            result = {
                "total_entities": len(entities_list),
                "mappable_entities": mappable_entities,
                "geographic_coverage": {
                    "regions": list(regions),
                    "coverage_percentage": (mappable_entities / len(entities_list) * 100) if entities_list else 0,
                },
                "entities": entities_list,
                "extraction_metadata": {
                    "confidence_threshold": confidence_threshold,
                    "documents_processed": total_documents,
                    "extraction_method": "pattern_matching",
                    "timestamp": datetime.now().isoformat(),
                },
            }

            self.logger.info(
                "Extracted %s geographic entities from %s documents",
                len(entities_list),
                total_documents,
            )
            return result

        except Exception as e:
            self.logger.error("Error extracting geographic entities: %s", e)
            return {
                "total_entities": 0,
                "mappable_entities": 0,
                "entities": [],
                "error": str(e),
            }

    def map_spatiotemporal_events(
        self,
        corpus_data: str | Dict[str, Any] | List[Dict[str, Any]],
        time_range: Optional[Dict[str, str]] = None,
        clustering_distance: float = 50.0,
        temporal_resolution: str = "day",
    ) -> Dict[str, Any]:
        """Map events with spatial-temporal clustering analysis."""
        try:
            corpus = json.loads(corpus_data) if isinstance(corpus_data, str) else corpus_data

            events: List[Dict[str, Any]] = []
            spatial_clusters: Dict[str, List[List[float]]] = {}
            temporal_clusters: Dict[str, List[str]] = {}

            documents = corpus if isinstance(corpus, list) else [corpus]

            for doc_idx, document in enumerate(documents):
                content = (document.get("content", "") or "") + " " + (document.get("title", "") or "")
                doc_date = document.get("date", datetime.now().isoformat())

                locations = self._extract_locations_from_text(content)
                event_types = self._extract_event_types(content)

                for location in locations:
                    location_key = location.lower()
                    coordinates = self.location_coordinates.get(location_key)
                    if not coordinates:
                        continue

                    for event_type in event_types:
                        event = {
                            "entity": location,
                            "event_type": event_type,
                            "latitude": coordinates[0],
                            "longitude": coordinates[1],
                            "timestamp": doc_date,
                            "confidence": self._calculate_event_confidence(event_type, content),
                            "context": self._extract_context(f"{event_type} {location}", content),
                            "document_id": document.get("id", doc_idx),
                            "source": document.get("source", "unknown"),
                        }

                        if time_range:
                            event_time = datetime.fromisoformat(doc_date.replace("Z", "+00:00"))
                            start_time = datetime.fromisoformat(time_range["start"].replace("Z", "+00:00"))
                            end_time = datetime.fromisoformat(time_range["end"].replace("Z", "+00:00"))
                            if not (start_time <= event_time <= end_time):
                                continue

                        events.append(event)

                        spatial_cluster = self._assign_spatial_cluster(
                            coordinates, spatial_clusters, clustering_distance
                        )
                        event["spatial_cluster"] = spatial_cluster

                        temporal_cluster = self._assign_temporal_cluster(
                            doc_date, temporal_clusters, temporal_resolution
                        )
                        event["temporal_cluster"] = temporal_cluster

            cluster_stats = {cluster_name: len(points) for cluster_name, points in spatial_clusters.items()}

            result = {
                "total_events": len(events),
                "spatial_clusters": cluster_stats,
                "temporal_clusters": {k: len(v) for k, v in temporal_clusters.items()},
                "events": events,
                "clustering_metadata": {
                    "clustering_distance": clustering_distance,
                    "temporal_resolution": temporal_resolution,
                    "time_range": time_range,
                    "timestamp": datetime.now().isoformat(),
                },
            }

            self.logger.info(
                "Mapped %s spatiotemporal events with %s spatial clusters",
                len(events),
                len(cluster_stats),
            )
            return result

        except Exception as e:
            self.logger.error("Error mapping spatiotemporal events: %s", e)
            return {
                "total_events": 0,
                "spatial_clusters": {},
                "events": [],
                "error": str(e),
            }

    def query_geographic_context(
        self,
        query: str,
        corpus_data: str | Dict[str, Any] | List[Dict[str, Any]],
        radius_km: float = 100.0,
        center_location: Optional[str] = None,
        include_related_entities: bool = True,
        temporal_context: bool = True,
    ) -> Dict[str, Any]:
        """Perform natural language geographic queries with relationship discovery."""
        try:
            corpus = json.loads(corpus_data) if isinstance(corpus_data, str) else corpus_data

            query_terms = self._parse_geographic_query(query)
            query_locations = query_terms.get("locations", [])

            center_coords = None
            if center_location:
                center_coords = self.location_coordinates.get(center_location.lower())
            elif query_locations:
                center_coords = self.location_coordinates.get(query_locations[0].lower())

            results: List[Dict[str, Any]] = []
            documents = corpus if isinstance(corpus, list) else [corpus]

            for doc_idx, document in enumerate(documents):
                content = (document.get("content", "") or "") + " " + (document.get("title", "") or "")

                relevance_score = self._calculate_query_relevance(query_terms, content)
                if relevance_score <= 0.1:
                    continue

                locations = self._extract_locations_from_text(content)
                for location in locations:
                    location_key = location.lower()
                    coordinates = self.location_coordinates.get(location_key)
                    if not coordinates:
                        continue

                    if center_coords:
                        distance = self._calculate_distance(center_coords, coordinates)
                        if distance > radius_km:
                            continue

                    result_entry: Dict[str, Any] = {
                        "entity": location,
                        "entity_type": "location",
                        "coordinates": coordinates,
                        "confidence": self._calculate_location_confidence(location, content),
                        "context_snippet": self._extract_context(location, content),
                        "relevance_score": relevance_score,
                        "document_id": document.get("id", doc_idx),
                        "document_title": document.get("title", f"Document {doc_idx}"),
                    }

                    if include_related_entities:
                        result_entry["related_entities"] = self._find_related_entities(location, content)

                    if temporal_context:
                        result_entry["temporal_context"] = {
                            "document_date": document.get("date", datetime.now().isoformat()),
                            "temporal_references": self._extract_temporal_references(content),
                        }

                    results.append(result_entry)

            results.sort(key=lambda x: x["relevance_score"], reverse=True)

            geographic_scope = None
            if results:
                lats = [r["coordinates"][0] for r in results]
                lngs = [r["coordinates"][1] for r in results]
                geographic_scope = {
                    "center": [sum(lats) / len(lats), sum(lngs) / len(lngs)],
                    "bounds": {
                        "north": max(lats),
                        "south": min(lats),
                        "east": max(lngs),
                        "west": min(lngs),
                    },
                }

            query_result = {
                "query": query,
                "total_results": len(results),
                "results": results,
                "query_metadata": {
                    "parsed_terms": query_terms,
                    "center_location": center_location,
                    "radius_km": radius_km,
                    "geographic_scope": geographic_scope,
                    "timestamp": datetime.now().isoformat(),
                },
            }

            self.logger.info("Geographic query '%s' returned %s results", query, len(results))
            return query_result

        except Exception as e:
            self.logger.error("Error processing geographic query: %s", e)
            return {
                "query": query,
                "total_results": 0,
                "results": [],
                "error": str(e),
            }

    def _extract_locations_from_text(self, text: str) -> List[str]:
        locations: List[str] = []

        location_patterns = [
            r"\b(?:New York|NYC|Manhattan|Wall Street)\b",
            r"\b(?:Washington|Washington DC|Capitol Hill)\b",
            r"\b(?:London|The City|City of London)\b",
            r"\b(?:Silicon Valley|San Francisco|SF)\b",
            r"\b(?:Chicago|Los Angeles|Boston|Tokyo|Hong Kong|Singapore)\b",
            r"\b(?:Federal Reserve|NYSE|NASDAQ|Goldman Sachs|JPMorgan)\b",
        ]

        for pattern in location_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            locations.extend(matches)

        return list(set(locations))

    def _extract_event_types(self, text: str) -> List[str]:
        event_patterns = {
            "trading": r"\b(?:trading|trade|market|exchange)\b",
            "announcement": r"\b(?:announce|announcement|declare|statement)\b",
            "meeting": r"\b(?:meeting|conference|summit|gathering)\b",
            "decision": r"\b(?:decision|ruling|verdict|judgment)\b",
            "investment": r"\b(?:investment|funding|capital|finance)\b",
            "regulation": r"\b(?:regulation|policy|law|compliance)\b",
        }

        events: List[str] = []
        for event_type, pattern in event_patterns.items():
            if re.search(pattern, text, re.IGNORECASE):
                events.append(event_type)

        return events if events else ["general"]

    def _calculate_location_confidence(self, location: str, context: str) -> float:
        base_confidence = 0.7

        financial_terms = ["financial", "bank", "trading", "market", "exchange"]
        context_lower = context.lower()
        for term in financial_terms:
            if term in context_lower:
                base_confidence += 0.05

        if location and location[0].isupper():
            base_confidence += 0.1

        return min(base_confidence, 1.0)

    def _calculate_event_confidence(self, event_type: str, context: str) -> float:
        base_confidence = 0.6
        if event_type in context.lower():
            base_confidence += 0.2
        return min(base_confidence, 1.0)

    def _extract_context(self, entity: str, text: str, window: int = 50) -> str:
        entity_lower = entity.lower()
        text_lower = text.lower()

        start_pos = text_lower.find(entity_lower)
        if start_pos == -1:
            return (text[:100] + "...") if len(text) > 100 else text

        start = max(0, start_pos - window)
        end = min(len(text), start_pos + len(entity) + window)

        snippet = text[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."

        return snippet

    def _assign_spatial_cluster(
        self,
        coordinates: List[float],
        clusters: Dict[str, List[List[float]]],
        max_distance: float,
    ) -> str:
        for cluster_name, cluster_points in clusters.items():
            for point in cluster_points:
                if self._calculate_distance(coordinates, point) <= max_distance:
                    cluster_points.append(coordinates)
                    return cluster_name

        cluster_name = f"cluster_{len(clusters) + 1}"
        clusters[cluster_name] = [coordinates]
        return cluster_name

    def _assign_temporal_cluster(
        self,
        timestamp: str,
        clusters: Dict[str, List[str]],
        resolution: str,
    ) -> str:
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

            if resolution == "hour":
                cluster_key = dt.strftime("%Y-%m-%d-%H")
            elif resolution == "day":
                cluster_key = dt.strftime("%Y-%m-%d")
            elif resolution == "week":
                cluster_key = f"{dt.year}-W{dt.isocalendar()[1]}"
            elif resolution == "month":
                cluster_key = dt.strftime("%Y-%m")
            else:
                cluster_key = dt.strftime("%Y-%m-%d")

            clusters.setdefault(cluster_key, []).append(timestamp)
            return cluster_key

        except Exception:
            return "unknown"

    def _calculate_distance(self, coord1: List[float], coord2: List[float]) -> float:
        lat1, lon1 = math.radians(coord1[0]), math.radians(coord1[1])
        lat2, lon2 = math.radians(coord2[0]), math.radians(coord2[1])

        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))

        return 6371 * c

    def _parse_geographic_query(self, query: str) -> Dict[str, List[str]]:
        query_lower = query.lower()

        locations: List[str] = []
        for location in self.location_coordinates.keys():
            if location in query_lower:
                locations.append(location)

        events: List[str] = []
        event_keywords = {
            "financial": ["financial", "finance", "money", "investment", "trading"],
            "political": ["political", "government", "policy", "regulation"],
            "business": ["business", "corporate", "company", "merger"],
            "legal": ["legal", "lawsuit", "court", "litigation"],
        }

        for event_type, keywords in event_keywords.items():
            if any(keyword in query_lower for keyword in keywords):
                events.append(event_type)

        entities: List[str] = []
        entity_patterns = [
            r"\b[A-Z][a-z]+ [A-Z][a-z]+\b",
            r"\b[A-Z]{2,}\b",
        ]

        for pattern in entity_patterns:
            entities.extend(re.findall(pattern, query))

        return {
            "locations": locations,
            "events": events,
            "entities": entities,
            "raw_query": query,
        }

    def _calculate_query_relevance(self, query_terms: Dict[str, Any], content: str) -> float:
        content_lower = content.lower()
        score = 0.0

        for location in query_terms.get("locations", []):
            if location in content_lower:
                score += 0.3

        for event in query_terms.get("events", []):
            if event in content_lower:
                score += 0.2

        for entity in query_terms.get("entities", []):
            if str(entity).lower() in content_lower:
                score += 0.1

        return min(score, 1.0)

    def _find_related_entities(self, location: str, content: str) -> List[Dict[str, str]]:
        related: List[Dict[str, str]] = []

        org_patterns = [
            r"\b[A-Z][a-z]+ [A-Z][a-z]+ (?:Bank|Corp|Inc|LLC|Ltd)\b",
            r"\b(?:Goldman Sachs|JPMorgan|Morgan Stanley|Federal Reserve)\b",
        ]

        for pattern in org_patterns:
            for match in re.findall(pattern, content):
                related.append({"entity": match, "type": "organization"})

        return related[:5]

    def _extract_temporal_references(self, content: str) -> List[str]:
        temporal_patterns = [
            r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b",
            r"\b\d{4}-\d{2}-\d{2}\b",
            r"\b(?:today|yesterday|tomorrow|this week|last week|next week)\b",
        ]

        references: List[str] = []
        for pattern in temporal_patterns:
            references.extend(re.findall(pattern, content, re.IGNORECASE))

        return references[:3]


_geospatial_tools = GeospatialAnalysisTools()


def extract_geographic_entities(
    corpus_data: str | Dict[str, Any] | List[Dict[str, Any]],
    confidence_threshold: float = 0.7,
    include_coordinates: bool = True,
) -> Dict[str, Any]:
    return _geospatial_tools.extract_geographic_entities(
        corpus_data,
        confidence_threshold=confidence_threshold,
        include_coordinates=include_coordinates,
    )


def map_spatiotemporal_events(
    corpus_data: str | Dict[str, Any] | List[Dict[str, Any]],
    time_range: Optional[Dict[str, str]] = None,
    clustering_distance: float = 50.0,
    temporal_resolution: str = "day",
) -> Dict[str, Any]:
    return _geospatial_tools.map_spatiotemporal_events(
        corpus_data,
        time_range=time_range,
        clustering_distance=clustering_distance,
        temporal_resolution=temporal_resolution,
    )


def query_geographic_context(
    query: str,
    corpus_data: str | Dict[str, Any] | List[Dict[str, Any]],
    radius_km: float = 100.0,
    center_location: Optional[str] = None,
    include_related_entities: bool = True,
    temporal_context: bool = True,
) -> Dict[str, Any]:
    return _geospatial_tools.query_geographic_context(
        query,
        corpus_data,
        radius_km=radius_km,
        center_location=center_location,
        include_related_entities=include_related_entities,
        temporal_context=temporal_context,
    )
