#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Geospatial Analysis MCP Tools

Provides MCP tools for geospatial analysis and mapping of events, entities, and relationships
in investigation workflows with spatial-temporal analysis capabilities.
"""
from __future__ import annotations

import anyio
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import math

from ..tool_wrapper import wrap_function_as_tool

logger = logging.getLogger(__name__)


@wrap_function_as_tool(
    name="extract_geographic_entities",
    description="Extract and geocode location entities from corpus data for mapping",
    category="investigation"
)
async def extract_geographic_entities(
    corpus_data: str,
    confidence_threshold: float = 0.8,
    entity_types: Optional[List[str]] = None,
    include_coordinates: bool = True,
    geographic_scope: Optional[str] = None
) -> Dict[str, Any]:
    """
    Extract geographic entities from corpus and attempt to geocode them.
    
    Args:
        corpus_data: JSON string containing document corpus data
        confidence_threshold: Minimum confidence for location extraction
        entity_types: Types of geographic entities (CITY, COUNTRY, STATE, etc.)
        include_coordinates: Whether to attempt coordinate lookup
        geographic_scope: Geographic scope filter (country, region, etc.)
        
    Returns:
        Dictionary containing geographic entities with coordinates and metadata
    """
    try:
        if isinstance(corpus_data, str):
            corpus = json.loads(corpus_data)
        else:
            corpus = corpus_data

        # Default entity types for geographic extraction
        if entity_types is None:
            entity_types = ["GPE", "LOC", "FACILITY", "CITY", "COUNTRY", "STATE"]

        geographic_entities = []
        entity_frequency = {}
        coordinate_cache = {}

        # Known coordinates for major locations (fallback)
        known_coordinates = {
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
            "australia": (-25.2744, 133.7751)
        }

        documents = corpus.get('documents', []) if isinstance(corpus, dict) else corpus

        for doc_idx, document in enumerate(documents):
            doc_text = document.get('content', '') if isinstance(document, dict) else str(document)
            doc_id = document.get('id', f'doc_{doc_idx}') if isinstance(document, dict) else f'doc_{doc_idx}'
            doc_timestamp = document.get('timestamp') if isinstance(document, dict) else None

            # Extract location entities using pattern matching and NER simulation
            location_patterns = [
                r'\b([A-Z][a-z]+(?: [A-Z][a-z]+)*),\s*([A-Z]{2})\b',  # City, State
                r'\b([A-Z][a-z]+(?: [A-Z][a-z]+)*),\s*([A-Z][a-z]+(?: [A-Z][a-z]+)*)\b',  # City, Country
                r'\bin\s+([A-Z][a-z]+(?: [A-Z][a-z]+)*)\b',  # "in Location"
                r'\bat\s+([A-Z][a-z]+(?: [A-Z][a-z]+)*)\b',  # "at Location"
                r'\bfrom\s+([A-Z][a-z]+(?: [A-Z][a-z]+)*)\b',  # "from Location"
                r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:City|State|Country|Province|Region))\b'  # Location + Type
            ]

            extracted_locations = set()
            
            for pattern in location_patterns:
                matches = re.finditer(pattern, doc_text)
                for match in matches:
                    location = match.group(1).strip() if match.groups() else match.group(0).strip()
                    if len(location) > 2 and location.lower() not in ['the', 'and', 'for', 'with']:
                        extracted_locations.add(location.lower())

            # Add known geographic entities from common location words
            location_keywords = [
                'afghanistan', 'albania', 'algeria', 'argentina', 'australia', 'austria',
                'bangladesh', 'belgium', 'brazil', 'canada', 'chile', 'china', 'colombia',
                'denmark', 'egypt', 'finland', 'france', 'germany', 'greece', 'india',
                'indonesia', 'iran', 'iraq', 'ireland', 'israel', 'italy', 'japan',
                'jordan', 'kenya', 'korea', 'lebanon', 'malaysia', 'mexico', 'netherlands',
                'nigeria', 'norway', 'pakistan', 'philippines', 'poland', 'portugal',
                'russia', 'saudi arabia', 'singapore', 'south africa', 'spain', 'sweden',
                'switzerland', 'thailand', 'turkey', 'ukraine', 'united kingdom', 'united states',
                'venezuela', 'vietnam', 'new york', 'washington', 'london', 'paris', 'tokyo',
                'moscow', 'beijing', 'berlin', 'sydney', 'los angeles', 'chicago', 'miami'
            ]

            for keyword in location_keywords:
                if keyword in doc_text.lower():
                    extracted_locations.add(keyword)

            # Process each extracted location
            for location in extracted_locations:
                location_key = location.lower().strip()
                
                # Update frequency count
                entity_frequency[location_key] = entity_frequency.get(location_key, 0) + 1
                
                # Skip if below confidence threshold based on frequency
                if entity_frequency[location_key] < confidence_threshold:
                    continue

                # Apply geographic scope filter
                if geographic_scope and geographic_scope.lower() not in location_key:
                    continue

                # Get coordinates
                coordinates = None
                if include_coordinates and location_key in known_coordinates:
                    coordinates = known_coordinates[location_key]
                elif include_coordinates:
                    # Attempt to infer coordinates based on context or patterns
                    coordinates = await _infer_coordinates(location_key)

                entity_data = {
                    'entity': location.title(),
                    'entity_type': 'LOCATION',
                    'confidence': min(entity_frequency[location_key] / 10.0, 1.0),
                    'frequency': entity_frequency[location_key],
                    'coordinates': coordinates,
                    'latitude': coordinates[0] if coordinates else None,
                    'longitude': coordinates[1] if coordinates else None,
                    'documents': [doc_id],
                    'timestamp': doc_timestamp,
                    'context_snippet': _extract_context(doc_text, location, 100)
                }

                # Check if entity already exists and merge
                existing_entity = None
                for existing in geographic_entities:
                    if existing['entity'].lower() == location_key:
                        existing_entity = existing
                        break

                if existing_entity:
                    existing_entity['frequency'] += 1
                    existing_entity['confidence'] = min(existing_entity['frequency'] / 10.0, 1.0)
                    if doc_id not in existing_entity['documents']:
                        existing_entity['documents'].append(doc_id)
                else:
                    geographic_entities.append(entity_data)

        # Sort by confidence and frequency
        geographic_entities.sort(key=lambda x: (x['confidence'], x['frequency']), reverse=True)

        # Filter entities with coordinates for mapping
        mappable_entities = [e for e in geographic_entities if e['coordinates'] is not None]

        result = {
            'total_entities': len(geographic_entities),
            'mappable_entities': len(mappable_entities),
            'entities': geographic_entities,
            'geographic_coverage': {
                'regions': _analyze_geographic_coverage(mappable_entities),
                'coordinate_bounds': _calculate_bounds(mappable_entities)
            },
            'extraction_stats': {
                'confidence_threshold': confidence_threshold,
                'entity_types': entity_types,
                'geographic_scope': geographic_scope,
                'timestamp': datetime.now().isoformat()
            }
        }

        logger.info(f"Extracted {len(geographic_entities)} geographic entities, {len(mappable_entities)} mappable")
        return result

    except Exception as e:
        logger.error(f"Error extracting geographic entities: {str(e)}")
        return {
            'error': f"Geographic entity extraction failed: {str(e)}",
            'total_entities': 0,
            'mappable_entities': 0,
            'entities': [],
            'timestamp': datetime.now().isoformat()
        }


@wrap_function_as_tool(
    name="map_spatiotemporal_events",
    description="Map events with both spatial and temporal dimensions for investigation analysis",
    category="investigation"
)
async def map_spatiotemporal_events(
    corpus_data: str,
    time_range: Optional[Dict[str, str]] = None,
    geographic_bounds: Optional[Dict[str, float]] = None,
    event_types: Optional[List[str]] = None,
    clustering_distance: float = 50.0,
    temporal_resolution: str = "day"
) -> Dict[str, Any]:
    """
    Map events with spatial and temporal dimensions for investigation analysis.
    
    Args:
        corpus_data: JSON string containing document corpus data
        time_range: Dict with 'start' and 'end' datetime strings
        geographic_bounds: Dict with 'north', 'south', 'east', 'west' coordinates
        event_types: Types of events to focus on
        clustering_distance: Distance in km for spatial clustering
        temporal_resolution: Temporal clustering resolution (hour, day, week, month)
        
    Returns:
        Dictionary containing spatiotemporal event mapping results
    """
    try:
        if isinstance(corpus_data, str):
            corpus = json.loads(corpus_data)
        else:
            corpus = corpus_data

        # Extract geographic entities first
        geo_result = await extract_geographic_entities(
            json.dumps(corpus) if not isinstance(corpus_data, str) else corpus_data,
            confidence_threshold=0.7,
            include_coordinates=True
        )

        mappable_entities = geo_result.get('entities', [])
        documents = corpus.get('documents', []) if isinstance(corpus, dict) else corpus

        spatiotemporal_events = []
        temporal_clusters = {}
        spatial_clusters = {}

        for doc_idx, document in enumerate(documents):
            doc_text = document.get('content', '') if isinstance(document, dict) else str(document)
            doc_id = document.get('id', f'doc_{doc_idx}') if isinstance(document, dict) else f'doc_{doc_idx}'
            doc_timestamp = document.get('timestamp') if isinstance(document, dict) else datetime.now().isoformat()

            # Parse timestamp
            try:
                if isinstance(doc_timestamp, str):
                    event_time = datetime.fromisoformat(doc_timestamp.replace('Z', '+00:00'))
                else:
                    event_time = datetime.now()
            except (ValueError, AttributeError, TypeError):
                # Use current time if timestamp parsing fails
                event_time = datetime.now()

            # Apply time range filter
            if time_range:
                start_time = datetime.fromisoformat(time_range['start'])
                end_time = datetime.fromisoformat(time_range['end'])
                if not (start_time <= event_time <= end_time):
                    continue

            # Extract events and match with locations
            event_patterns = [
                r'\b(attacked|bombing|explosion|protest|meeting|conference|agreement|deal|arrest|conviction)\b',
                r'\b(happened|occurred|took place|held at|located in)\b',
                r'\b(announced|declared|signed|launched|opened|closed)\b'
            ]

            events_in_doc = []
            for pattern in event_patterns:
                matches = re.finditer(pattern, doc_text, re.IGNORECASE)
                for match in matches:
                    event_context = _extract_context(doc_text, match.group(), 200)
                    events_in_doc.append({
                        'event_type': match.group().lower(),
                        'context': event_context,
                        'position': match.start()
                    })

            # Match events with geographic entities
            for entity in mappable_entities:
                if doc_id in entity['documents'] and entity['coordinates']:
                    lat, lng = entity['coordinates']
                    
                    # Apply geographic bounds filter
                    if geographic_bounds:
                        if not (_is_within_bounds(lat, lng, geographic_bounds)):
                            continue

                    for event in events_in_doc:
                        # Filter by event types
                        if event_types and event['event_type'] not in event_types:
                            continue

                        spatiotemporal_event = {
                            'event_id': f"{doc_id}_{entity['entity']}_{event['event_type']}",
                            'document_id': doc_id,
                            'entity': entity['entity'],
                            'event_type': event['event_type'],
                            'latitude': lat,
                            'longitude': lng,
                            'timestamp': event_time.isoformat(),
                            'context': event['context'],
                            'confidence': entity['confidence'],
                            'temporal_cluster': _get_temporal_cluster(event_time, temporal_resolution),
                            'spatial_cluster': await _get_spatial_cluster(lat, lng, spatiotemporal_events, clustering_distance)
                        }

                        spatiotemporal_events.append(spatiotemporal_event)

        # Generate temporal clusters
        for event in spatiotemporal_events:
            cluster_key = event['temporal_cluster']
            if cluster_key not in temporal_clusters:
                temporal_clusters[cluster_key] = []
            temporal_clusters[cluster_key].append(event['event_id'])

        # Generate spatial clusters  
        spatial_clusters = await _generate_spatial_clusters(spatiotemporal_events, clustering_distance)

        # Calculate statistics
        event_statistics = _calculate_event_statistics(spatiotemporal_events)

        result = {
            'total_events': len(spatiotemporal_events),
            'events': spatiotemporal_events,
            'temporal_clusters': temporal_clusters,
            'spatial_clusters': spatial_clusters,
            'statistics': event_statistics,
            'parameters': {
                'time_range': time_range,
                'geographic_bounds': geographic_bounds,
                'event_types': event_types,
                'clustering_distance': clustering_distance,
                'temporal_resolution': temporal_resolution
            },
            'timestamp': datetime.now().isoformat()
        }

        logger.info(f"Mapped {len(spatiotemporal_events)} spatiotemporal events")
        return result

    except Exception as e:
        logger.error(f"Error mapping spatiotemporal events: {str(e)}")
        return {
            'error': f"Spatiotemporal event mapping failed: {str(e)}",
            'total_events': 0,
            'events': [],
            'timestamp': datetime.now().isoformat()
        }


@wrap_function_as_tool(
    name="query_geographic_context",
    description="Query geographic context and relationships for investigation analysis",
    category="investigation"
)
async def query_geographic_context(
    query: str,
    corpus_data: str,
    radius_km: float = 100.0,
    center_location: Optional[str] = None,
    include_related_entities: bool = True,
    temporal_context: bool = True
) -> Dict[str, Any]:
    """
    Query geographic context and relationships for investigation analysis.
    
    Args:
        query: Natural language query about geographic context
        corpus_data: JSON string containing document corpus data
        radius_km: Search radius in kilometers from center location
        center_location: Center location for geographic search
        include_related_entities: Whether to include related entities
        temporal_context: Whether to include temporal context
        
    Returns:
        Dictionary containing geographic context query results
    """
    try:
        if isinstance(corpus_data, str):
            corpus = json.loads(corpus_data)
        else:
            corpus = corpus_data

        # Extract geographic entities
        geo_result = await extract_geographic_entities(
            json.dumps(corpus) if not isinstance(corpus_data, str) else corpus_data,
            confidence_threshold=0.6
        )

        entities = geo_result.get('entities', [])
        
        # Parse query for location context
        query_lower = query.lower()
        query_results = []
        center_coordinates = None

        # Find center location coordinates
        if center_location:
            for entity in entities:
                if center_location.lower() in entity['entity'].lower() and entity['coordinates']:
                    center_coordinates = entity['coordinates']
                    break

        # Search for relevant entities and documents
        for entity in entities:
            if not entity['coordinates']:
                continue

            relevance_score = 0.0
            
            # Calculate relevance based on query keywords
            query_keywords = query_lower.split()
            entity_name = entity['entity'].lower()
            
            for keyword in query_keywords:
                if keyword in entity_name:
                    relevance_score += 2.0
                if keyword in entity['context_snippet'].lower():
                    relevance_score += 1.0

            # Calculate distance relevance if center location provided
            distance_km = None
            if center_coordinates and entity['coordinates']:
                distance_km = _calculate_distance(
                    center_coordinates[0], center_coordinates[1],
                    entity['coordinates'][0], entity['coordinates'][1]
                )
                
                if distance_km <= radius_km:
                    relevance_score += max(0, (radius_km - distance_km) / radius_km * 3.0)

            if relevance_score > 0.5:  # Threshold for inclusion
                entity_result = {
                    **entity,
                    'relevance_score': relevance_score,
                    'distance_from_center': distance_km,
                    'query_matches': [kw for kw in query_keywords if kw in entity_name or kw in entity['context_snippet'].lower()]
                }

                # Add related entities if requested
                if include_related_entities:
                    related_entities = await _find_related_entities(entity, entities, corpus)
                    entity_result['related_entities'] = related_entities

                # Add temporal context if requested
                if temporal_context:
                    temporal_info = await _get_temporal_context(entity, corpus)
                    entity_result['temporal_context'] = temporal_info

                query_results.append(entity_result)

        # Sort by relevance score
        query_results.sort(key=lambda x: x['relevance_score'], reverse=True)

        result = {
            'query': query,
            'total_results': len(query_results),
            'results': query_results,
            'center_location': center_location,
            'center_coordinates': center_coordinates,
            'search_radius_km': radius_km,
            'geographic_summary': _generate_geographic_summary(query_results),
            'timestamp': datetime.now().isoformat()
        }

        logger.info(f"Geographic context query returned {len(query_results)} results")
        return result

    except Exception as e:
        logger.error(f"Error querying geographic context: {str(e)}")
        return {
            'error': f"Geographic context query failed: {str(e)}",
            'query': query,
            'total_results': 0,
            'results': [],
            'timestamp': datetime.now().isoformat()
        }


# Helper functions

async def _infer_coordinates(location: str) -> Optional[Tuple[float, float]]:
    """Infer coordinates for a location using pattern matching and heuristics."""
    # Simple coordinate inference based on known patterns
    location_lower = location.lower().strip()
    
    # Check for US states
    us_states = {
        'california': (36.7783, -119.4179), 'texas': (31.9686, -99.9018),
        'florida': (27.7663, -82.6404), 'new york': (40.7128, -74.0060),
        'pennsylvania': (41.2033, -77.1945), 'illinois': (40.6331, -89.3985)
    }
    
    if location_lower in us_states:
        return us_states[location_lower]
    
    # Check for major cities with country context
    if 'united states' in location_lower or 'usa' in location_lower:
        return (39.8283, -98.5795)  # US center
    elif 'united kingdom' in location_lower or 'uk' in location_lower:
        return (55.3781, -3.4360)  # UK center
    
    return None


def _extract_context(text: str, entity: str, context_length: int = 100) -> str:
    """Extract context around an entity mention."""
    entity_pos = text.lower().find(entity.lower())
    if entity_pos == -1:
        return text[:context_length]
    
    start = max(0, entity_pos - context_length // 2)
    end = min(len(text), entity_pos + len(entity) + context_length // 2)
    
    return text[start:end].strip()


def _analyze_geographic_coverage(entities: List[Dict]) -> Dict[str, Any]:
    """Analyze geographic coverage of entities."""
    if not entities:
        return {'regions': [], 'continents': [], 'countries': []}
    
    regions = set()
    countries = set()
    
    for entity in entities:
        if entity.get('coordinates'):
            lat, lng = entity['coordinates']
            # Simple continent classification
            if -90 <= lat <= 90:
                if -180 <= lng <= -30:
                    regions.add('Americas')
                elif -30 <= lng <= 60:
                    regions.add('Europe/Africa')
                elif 60 <= lng <= 180:
                    regions.add('Asia/Pacific')
        
        # Extract country from entity name
        entity_name = entity['entity'].lower()
        country_keywords = ['united states', 'china', 'russia', 'india', 'brazil', 'germany', 'france', 'japan']
        for country in country_keywords:
            if country in entity_name:
                countries.add(country.title())
    
    return {
        'regions': list(regions),
        'countries': list(countries),
        'total_regions': len(regions),
        'total_countries': len(countries)
    }


def _calculate_bounds(entities: List[Dict]) -> Optional[Dict[str, float]]:
    """Calculate bounding box for entities with coordinates."""
    coords = [e['coordinates'] for e in entities if e.get('coordinates')]
    if not coords:
        return None
    
    lats = [c[0] for c in coords]
    lngs = [c[1] for c in coords]
    
    return {
        'north': max(lats),
        'south': min(lats), 
        'east': max(lngs),
        'west': min(lngs)
    }


def _is_within_bounds(lat: float, lng: float, bounds: Dict[str, float]) -> bool:
    """Check if coordinates are within geographic bounds."""
    return (bounds['south'] <= lat <= bounds['north'] and 
            bounds['west'] <= lng <= bounds['east'])


def _get_temporal_cluster(timestamp: datetime, resolution: str) -> str:
    """Get temporal cluster key for a timestamp."""
    if resolution == "hour":
        return timestamp.strftime("%Y-%m-%d-%H")
    elif resolution == "day":
        return timestamp.strftime("%Y-%m-%d")
    elif resolution == "week":
        week_start = timestamp - timedelta(days=timestamp.weekday())
        return week_start.strftime("%Y-W%U")
    elif resolution == "month":
        return timestamp.strftime("%Y-%m")
    else:
        return timestamp.strftime("%Y-%m-%d")


async def _get_spatial_cluster(lat: float, lng: float, existing_events: List[Dict], distance_km: float) -> str:
    """Get spatial cluster ID for coordinates."""
    for event in existing_events:
        if event.get('latitude') and event.get('longitude'):
            dist = _calculate_distance(lat, lng, event['latitude'], event['longitude'])
            if dist <= distance_km:
                return event.get('spatial_cluster', f"cluster_{len(existing_events)}")
    
    return f"cluster_{len(existing_events)}"


async def _generate_spatial_clusters(events: List[Dict], distance_km: float) -> Dict[str, List[str]]:
    """Generate spatial clusters for events."""
    clusters = {}
    for event in events:
        cluster_id = event.get('spatial_cluster', 'unknown')
        if cluster_id not in clusters:
            clusters[cluster_id] = []
        clusters[cluster_id].append(event['event_id'])
    return clusters


def _calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two coordinates in kilometers."""
    R = 6371  # Earth's radius in km
    
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    
    a = (math.sin(delta_lat / 2) ** 2 + 
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c


def _calculate_event_statistics(events: List[Dict]) -> Dict[str, Any]:
    """Calculate statistics for spatiotemporal events."""
    if not events:
        return {}
    
    event_types = {}
    locations = {}
    time_distribution = {}
    
    for event in events:
        # Event type distribution
        event_type = event.get('event_type', 'unknown')
        event_types[event_type] = event_types.get(event_type, 0) + 1
        
        # Location distribution
        entity = event.get('entity', 'unknown')
        locations[entity] = locations.get(entity, 0) + 1
        
        # Time distribution
        timestamp = event.get('timestamp', '')
        if timestamp:
            date_key = timestamp[:10]  # YYYY-MM-DD
            time_distribution[date_key] = time_distribution.get(date_key, 0) + 1
    
    return {
        'event_types': event_types,
        'top_locations': dict(sorted(locations.items(), key=lambda x: x[1], reverse=True)[:10]),
        'time_distribution': time_distribution,
        'total_events': len(events),
        'unique_locations': len(locations),
        'unique_event_types': len(event_types)
    }


async def _find_related_entities(entity: Dict, all_entities: List[Dict], corpus: Dict) -> List[Dict]:
    """Find entities related to the given entity."""
    related = []
    entity_docs = set(entity.get('documents', []))
    
    for other_entity in all_entities:
        if other_entity['entity'] == entity['entity']:
            continue
            
        other_docs = set(other_entity.get('documents', []))
        overlap = len(entity_docs.intersection(other_docs))
        
        if overlap > 0:
            related.append({
                'entity': other_entity['entity'],
                'shared_documents': overlap,
                'coordinates': other_entity.get('coordinates'),
                'confidence': other_entity.get('confidence', 0.0)
            })
    
    return sorted(related, key=lambda x: x['shared_documents'], reverse=True)[:5]


async def _get_temporal_context(entity: Dict, corpus: Dict) -> Dict[str, Any]:
    """Get temporal context for an entity."""
    documents = corpus.get('documents', [])
    entity_docs = entity.get('documents', [])
    
    timestamps = []
    for doc in documents:
        if isinstance(doc, dict) and doc.get('id') in entity_docs:
            timestamp = doc.get('timestamp')
            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    timestamps.append(dt)
                except (ValueError, AttributeError, TypeError):
                    # Skip malformed timestamps
                    continue
    
    if not timestamps:
        return {'temporal_span': None, 'first_mention': None, 'last_mention': None}
    
    timestamps.sort()
    return {
        'temporal_span': (timestamps[-1] - timestamps[0]).days if len(timestamps) > 1 else 0,
        'first_mention': timestamps[0].isoformat(),
        'last_mention': timestamps[-1].isoformat(),
        'mention_frequency': len(timestamps)
    }


def _generate_geographic_summary(results: List[Dict]) -> Dict[str, Any]:
    """Generate a summary of geographic query results."""
    if not results:
        return {'summary': 'No geographic results found'}
    
    locations = [r['entity'] for r in results]
    avg_relevance = sum(r['relevance_score'] for r in results) / len(results)
    
    # Find most frequent location types
    location_types = {}
    for result in results:
        for match in result.get('query_matches', []):
            location_types[match] = location_types.get(match, 0) + 1
    
    return {
        'total_locations': len(locations),
        'average_relevance': round(avg_relevance, 2),
        'top_locations': locations[:5],
        'common_terms': dict(sorted(location_types.items(), key=lambda x: x[1], reverse=True)[:3]),
        'geographic_spread': _calculate_bounds([r for r in results if r.get('coordinates')])
    }