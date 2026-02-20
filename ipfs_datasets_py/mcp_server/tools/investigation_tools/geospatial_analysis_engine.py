"""
Geospatial Analysis Engine

Business logic for geographic entity extraction, spatiotemporal event mapping,
and geographic context queries.
"""
from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

KNOWN_COORDINATES: Dict[str, Tuple[float, float]] = {
    "new york": (40.7128, -74.0060),
    "washington": (38.9072, -77.0369),
    "london": (51.5074, -0.1278),
    "paris": (48.8566, 2.3522),
    "tokyo": (35.6762, 139.6503),
    "moscow": (55.7558, 37.6176),
    "beijing": (39.9042, 116.4074),
    "berlin": (52.5200, 13.4050),
    "sydney": (-33.8688, 151.2093),
    "los angeles": (34.0522, -118.2437),
    "chicago": (41.8781, -87.6298),
    "miami": (25.7617, -80.1918),
    "toronto": (43.6532, -79.3832),
    "mexico city": (19.4326, -99.1332),
    "brazil": (-14.2350, -51.9253),
    "india": (20.5937, 78.9629),
    "china": (35.8617, 104.1954),
    "russia": (61.5240, 105.3188),
    "united states": (39.8283, -98.5795),
    "united kingdom": (55.3781, -3.4360),
    "france": (46.6034, 1.8883),
    "germany": (51.1657, 10.4515),
    "japan": (36.2048, 138.2529),
    "australia": (-25.2744, 133.7751),
}

LOCATION_KEYWORDS: List[str] = [
    "afghanistan", "albania", "algeria", "argentina", "australia", "austria",
    "bangladesh", "belgium", "brazil", "canada", "chile", "china", "colombia",
    "denmark", "egypt", "finland", "france", "germany", "greece", "india",
    "indonesia", "iran", "iraq", "ireland", "israel", "italy", "japan",
    "jordan", "kenya", "korea", "lebanon", "malaysia", "mexico", "netherlands",
    "nigeria", "norway", "pakistan", "philippines", "poland", "portugal",
    "russia", "saudi arabia", "singapore", "south africa", "spain", "sweden",
    "switzerland", "thailand", "turkey", "ukraine", "united kingdom",
    "united states", "venezuela", "vietnam", "new york", "washington",
    "london", "paris", "tokyo", "moscow", "beijing", "berlin", "sydney",
    "los angeles", "chicago", "miami",
]


class GeospatialAnalysisEngine:
    """Engine for geospatial analysis operations."""

    def extract_geographic_entities(
        self,
        corpus_data: Any,
        confidence_threshold: float = 0.8,
        entity_types: Optional[List[str]] = None,
        include_coordinates: bool = True,
        geographic_scope: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Extract and geocode location entities from corpus data."""
        try:
            if isinstance(corpus_data, str):
                import json
                corpus = json.loads(corpus_data)
            else:
                corpus = corpus_data
            if entity_types is None:
                entity_types = ["GPE", "LOC", "FACILITY", "CITY", "COUNTRY", "STATE"]
            geographic_entities: List[Dict[str, Any]] = []
            entity_frequency: Dict[str, int] = {}
            location_patterns = [
                r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)*),\s*([A-Z]{2})\b",
                r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)*),\s*([A-Z][a-z]+(?: [A-Z][a-z]+)*)\b",
                r"\bin\s+([A-Z][a-z]+(?: [A-Z][a-z]+)*)\b",
                r"\bat\s+([A-Z][a-z]+(?: [A-Z][a-z]+)*)\b",
                r"\bfrom\s+([A-Z][a-z]+(?: [A-Z][a-z]+)*)\b",
                r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:City|State|Country|Province|Region))\b",
            ]
            documents = (
                corpus.get("documents", []) if isinstance(corpus, dict) else corpus
            )
            for doc_idx, document in enumerate(documents):
                doc_text = (
                    document.get("content", "") if isinstance(document, dict) else str(document)
                )
                doc_id = (
                    document.get("id", f"doc_{doc_idx}")
                    if isinstance(document, dict)
                    else f"doc_{doc_idx}"
                )
                doc_timestamp = (
                    document.get("timestamp") if isinstance(document, dict) else None
                )
                extracted_locations: set = set()
                for pattern in location_patterns:
                    for match in re.finditer(pattern, doc_text):
                        location = (
                            match.group(1).strip() if match.groups() else match.group(0).strip()
                        )
                        if len(location) > 2 and location.lower() not in ["the", "and", "for", "with"]:
                            extracted_locations.add(location.lower())
                for keyword in LOCATION_KEYWORDS:
                    if keyword in doc_text.lower():
                        extracted_locations.add(keyword)
                for location in extracted_locations:
                    location_key = location.lower().strip()
                    entity_frequency[location_key] = entity_frequency.get(location_key, 0) + 1
                    if entity_frequency[location_key] < confidence_threshold:
                        continue
                    if geographic_scope and geographic_scope.lower() not in location_key:
                        continue
                    coordinates = None
                    if include_coordinates:
                        coordinates = self._geocode_location(location_key)
                    entity_data: Dict[str, Any] = {
                        "entity": location.title(),
                        "entity_type": "LOCATION",
                        "confidence": min(entity_frequency[location_key] / 10.0, 1.0),
                        "frequency": entity_frequency[location_key],
                        "coordinates": coordinates,
                        "latitude": coordinates[0] if coordinates else None,
                        "longitude": coordinates[1] if coordinates else None,
                        "documents": [doc_id],
                        "timestamp": doc_timestamp,
                        "context_snippet": self._extract_context(doc_text, location, 100),
                    }
                    existing = next(
                        (e for e in geographic_entities if e["entity"].lower() == location_key),
                        None,
                    )
                    if existing:
                        existing["frequency"] += 1
                        existing["confidence"] = min(existing["frequency"] / 10.0, 1.0)
                        if doc_id not in existing["documents"]:
                            existing["documents"].append(doc_id)
                    else:
                        geographic_entities.append(entity_data)
            geographic_entities.sort(
                key=lambda x: (x["confidence"], x["frequency"]), reverse=True
            )
            mappable_entities = [e for e in geographic_entities if e["coordinates"] is not None]
            return {
                "total_entities": len(geographic_entities),
                "mappable_entities": len(mappable_entities),
                "entities": geographic_entities,
                "geographic_coverage": {
                    "regions": self._analyze_geographic_coverage(mappable_entities),
                    "coordinate_bounds": self._calculate_bounds(mappable_entities),
                },
                "extraction_stats": {
                    "confidence_threshold": confidence_threshold,
                    "entity_types": entity_types,
                    "geographic_scope": geographic_scope,
                    "timestamp": datetime.now().isoformat(),
                },
            }
        except Exception as e:
            logger.error(f"Error extracting geographic entities: {e}")
            return {
                "error": f"Geographic entity extraction failed: {e}",
                "total_entities": 0,
                "mappable_entities": 0,
                "entities": [],
                "timestamp": datetime.now().isoformat(),
            }

    def map_spatiotemporal_events(
        self,
        entities_data: List[Dict[str, Any]],
        time_range: Optional[Dict[str, str]] = None,
        resolution: str = "day",
    ) -> Dict[str, Any]:
        """Map events with spatial and temporal dimensions."""
        try:
            spatiotemporal_events: List[Dict[str, Any]] = []
            temporal_clusters: Dict[str, List[str]] = {}
            event_patterns = [
                r"\b(attacked|bombing|explosion|protest|meeting|conference|agreement|"
                r"deal|arrest|conviction)\b",
                r"\b(happened|occurred|took place|held at|located in)\b",
                r"\b(announced|declared|signed|launched|opened|closed)\b",
            ]
            for entity in entities_data:
                if not entity.get("coordinates"):
                    continue
                lat, lng = entity["coordinates"]
                event_time_str = entity.get("timestamp") or datetime.now().isoformat()
                try:
                    event_time = datetime.fromisoformat(
                        str(event_time_str).replace("Z", "+00:00")
                    )
                except (ValueError, AttributeError, TypeError):
                    event_time = datetime.now()
                if time_range:
                    start_time = datetime.fromisoformat(time_range["start"])
                    end_time = datetime.fromisoformat(time_range["end"])
                    if not (start_time <= event_time <= end_time):
                        continue
                context = entity.get("context_snippet", "")
                events_in_entity = []
                for pattern in event_patterns:
                    for match in re.finditer(pattern, context, re.IGNORECASE):
                        events_in_entity.append(match.group().lower())
                if not events_in_entity:
                    events_in_entity = ["occurrence"]
                for event_type in events_in_entity:
                    event_id = f"{entity['entity']}_{event_type}_{event_time.date()}"
                    temporal_cluster = self._get_temporal_cluster(event_time, resolution)
                    spatial_cluster = f"cluster_{int(lat)}"
                    spatiotemporal_events.append({
                        "event_id": event_id,
                        "entity": entity["entity"],
                        "event_type": event_type,
                        "latitude": lat,
                        "longitude": lng,
                        "timestamp": event_time.isoformat(),
                        "confidence": entity.get("confidence", 0.0),
                        "temporal_cluster": temporal_cluster,
                        "spatial_cluster": spatial_cluster,
                    })
                    if temporal_cluster not in temporal_clusters:
                        temporal_clusters[temporal_cluster] = []
                    temporal_clusters[temporal_cluster].append(event_id)
            spatial_clusters: Dict[str, List[str]] = {}
            for event in spatiotemporal_events:
                cid = event["spatial_cluster"]
                if cid not in spatial_clusters:
                    spatial_clusters[cid] = []
                spatial_clusters[cid].append(event["event_id"])
            return {
                "total_events": len(spatiotemporal_events),
                "events": spatiotemporal_events,
                "temporal_clusters": temporal_clusters,
                "spatial_clusters": spatial_clusters,
                "parameters": {"time_range": time_range, "resolution": resolution},
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Error mapping spatiotemporal events: {e}")
            return {
                "error": f"Spatiotemporal event mapping failed: {e}",
                "total_events": 0,
                "events": [],
                "timestamp": datetime.now().isoformat(),
            }

    def query_geographic_context(
        self,
        location_query: str,
        entities: List[Dict[str, Any]],
        radius_km: float = 100.0,
        entity_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Query geographic context for a location."""
        try:
            query_lower = location_query.lower()
            query_results = []
            center_coordinates = None
            for entity in entities:
                if location_query.lower() in entity["entity"].lower() and entity.get("coordinates"):
                    center_coordinates = entity["coordinates"]
                    break
            for entity in entities:
                if not entity.get("coordinates"):
                    continue
                if entity_types and entity.get("entity_type") not in entity_types:
                    continue
                relevance_score = 0.0
                query_keywords = query_lower.split()
                entity_name = entity["entity"].lower()
                for keyword in query_keywords:
                    if keyword in entity_name:
                        relevance_score += 2.0
                    if keyword in entity.get("context_snippet", "").lower():
                        relevance_score += 1.0
                distance_km = None
                if center_coordinates and entity["coordinates"]:
                    distance_km = self._calculate_distance(
                        center_coordinates[0], center_coordinates[1],
                        entity["coordinates"][0], entity["coordinates"][1],
                    )
                    if distance_km <= radius_km:
                        relevance_score += max(0, (radius_km - distance_km) / radius_km * 3.0)
                if relevance_score > 0.5:
                    query_results.append({
                        **entity,
                        "relevance_score": relevance_score,
                        "distance_from_center": distance_km,
                    })
            query_results.sort(key=lambda x: x["relevance_score"], reverse=True)
            return {
                "query": location_query,
                "total_results": len(query_results),
                "results": query_results,
                "center_coordinates": center_coordinates,
                "search_radius_km": radius_km,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Error querying geographic context: {e}")
            return {
                "error": f"Geographic context query failed: {e}",
                "query": location_query,
                "total_results": 0,
                "results": [],
                "timestamp": datetime.now().isoformat(),
            }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _geocode_location(self, location_name: str) -> Optional[Tuple[float, float]]:
        """Return coordinates for a known location name."""
        location_lower = location_name.lower().strip()
        if location_lower in KNOWN_COORDINATES:
            return KNOWN_COORDINATES[location_lower]
        us_states = {
            "california": (36.7783, -119.4179),
            "texas": (31.9686, -99.9018),
            "florida": (27.7663, -82.6404),
            "new york": (40.7128, -74.0060),
            "pennsylvania": (41.2033, -77.1945),
            "illinois": (40.6331, -89.3985),
        }
        if location_lower in us_states:
            return us_states[location_lower]
        if "united states" in location_lower or "usa" in location_lower:
            return (39.8283, -98.5795)
        if "united kingdom" in location_lower or "uk" in location_lower:
            return (55.3781, -3.4360)
        return None

    def _calculate_distance(
        self, lat1: float, lon1: float, lat2: float, lon2: float
    ) -> float:
        """Calculate haversine distance in kilometres."""
        R = 6371.0
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)
        a = (
            math.sin(delta_lat / 2) ** 2
            + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    def _extract_context(self, text: str, entity: str, context_length: int = 100) -> str:
        entity_pos = text.lower().find(entity.lower())
        if entity_pos == -1:
            return text[:context_length]
        start = max(0, entity_pos - context_length // 2)
        end = min(len(text), entity_pos + len(entity) + context_length // 2)
        return text[start:end].strip()

    def _analyze_geographic_coverage(self, entities: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not entities:
            return {"regions": [], "continents": [], "countries": []}
        regions: set = set()
        countries: set = set()
        for entity in entities:
            if entity.get("coordinates"):
                lat, lng = entity["coordinates"]
                if -180 <= lng <= -30:
                    regions.add("Americas")
                elif -30 <= lng <= 60:
                    regions.add("Europe/Africa")
                elif 60 <= lng <= 180:
                    regions.add("Asia/Pacific")
            entity_name = entity["entity"].lower()
            for country in ["united states", "china", "russia", "india", "brazil",
                             "germany", "france", "japan"]:
                if country in entity_name:
                    countries.add(country.title())
        return {
            "regions": list(regions),
            "countries": list(countries),
            "total_regions": len(regions),
            "total_countries": len(countries),
        }

    def _calculate_bounds(
        self, entities: List[Dict[str, Any]]
    ) -> Optional[Dict[str, float]]:
        coords = [e["coordinates"] for e in entities if e.get("coordinates")]
        if not coords:
            return None
        lats = [c[0] for c in coords]
        lngs = [c[1] for c in coords]
        return {
            "north": max(lats),
            "south": min(lats),
            "east": max(lngs),
            "west": min(lngs),
        }

    def _get_temporal_cluster(self, timestamp: datetime, resolution: str) -> str:
        if resolution == "hour":
            return timestamp.strftime("%Y-%m-%d-%H")
        elif resolution == "day":
            return timestamp.strftime("%Y-%m-%d")
        elif resolution == "week":
            week_start = timestamp - timedelta(days=timestamp.weekday())
            return week_start.strftime("%Y-W%U")
        elif resolution == "month":
            return timestamp.strftime("%Y-%m")
        return timestamp.strftime("%Y-%m-%d")
