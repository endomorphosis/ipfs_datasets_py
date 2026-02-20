"""
Geographic and geospatial analysis tools for the MCP server.
Implements the three MCP tools required for the Maps tab functionality.

.. deprecated::
    This legacy module is superseded by
    ``ipfs_datasets_py.mcp_server.tools.geospatial_tools``.
    See ``legacy_mcp_tools/MIGRATION_GUIDE.md`` for migration instructions.
"""
import warnings
warnings.warn(
    "legacy_mcp_tools.geospatial_tools is deprecated. "
    "Use ipfs_datasets_py.mcp_server.tools.geospatial_tools instead.",
    DeprecationWarning,
    stacklevel=2,
)

import json
import logging
from typing import Any, Dict, List, Optional, Tuple
import re
from datetime import datetime
import anyio


class GeospatialAnalysisTools:
    """Tools for geographic entity extraction and spatial-temporal analysis."""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        # Mock geocoding database for demonstration
        self.location_coordinates = {
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
            "singapore": [1.3521, 103.8198]
        }
    
    def extract_geographic_entities(self, corpus_data: str, confidence_threshold: float = 0.7, 
                                  include_coordinates: bool = True) -> Dict[str, Any]:
        """
        Extract geographic entities from corpus data and geocode them.
        
        Args:
            corpus_data: JSON string of documents to analyze
            confidence_threshold: Minimum confidence for entity extraction
            include_coordinates: Whether to include coordinates in results
            
        Returns:
            Dictionary with extracted geographic entities and metadata
        """
        try:
            # Parse corpus data
            if isinstance(corpus_data, str):
                corpus = json.loads(corpus_data)
            else:
                corpus = corpus_data
            
            extracted_entities = []
            entity_frequencies = {}
            total_documents = len(corpus) if isinstance(corpus, list) else 1
            
            # Process documents
            documents = corpus if isinstance(corpus, list) else [corpus]
            
            for doc_idx, document in enumerate(documents):
                content = document.get('content', '') + ' ' + document.get('title', '')
                
                # Extract location entities using pattern matching
                locations = self._extract_locations_from_text(content)
                
                for location in locations:
                    location_key = location.lower()
                    
                    # Get coordinates if available
                    coordinates = None
                    if include_coordinates and location_key in self.location_coordinates:
                        coordinates = self.location_coordinates[location_key]
                    
                    # Calculate confidence based on context
                    confidence = self._calculate_location_confidence(location, content)
                    
                    if confidence >= confidence_threshold:
                        # Track frequency
                        if location_key not in entity_frequencies:
                            entity_frequencies[location_key] = {
                                'entity': location,
                                'frequency': 0,
                                'documents': [],
                                'confidence': confidence,
                                'coordinates': coordinates,
                                'context_snippet': self._extract_context(location, content)
                            }
                        
                        entity_frequencies[location_key]['frequency'] += 1
                        entity_frequencies[location_key]['documents'].append({
                            'id': document.get('id', doc_idx),
                            'title': document.get('title', f'Document {doc_idx}')
                        })
            
            # Convert to list and sort by frequency
            entities_list = list(entity_frequencies.values())
            entities_list.sort(key=lambda x: x['frequency'], reverse=True)
            
            # Calculate geographic coverage
            regions = set()
            for entity in entities_list:
                if entity['coordinates']:
                    lat, lng = entity['coordinates']
                    if lat > 49:  # Approximate Europe/Asia boundary
                        regions.add('Europe' if lng < 30 else 'Asia')
                    elif lat > 25:  # North America
                        regions.add('North America')
                    else:
                        regions.add('Other')
            
            mappable_entities = sum(1 for e in entities_list if e['coordinates'])
            
            result = {
                'total_entities': len(entities_list),
                'mappable_entities': mappable_entities,
                'geographic_coverage': {
                    'regions': list(regions),
                    'coverage_percentage': (mappable_entities / len(entities_list) * 100) if entities_list else 0
                },
                'entities': entities_list,
                'extraction_metadata': {
                    'confidence_threshold': confidence_threshold,
                    'documents_processed': total_documents,
                    'extraction_method': 'pattern_matching',
                    'timestamp': datetime.now().isoformat()
                }
            }
            
            self.logger.info(f"Extracted {len(entities_list)} geographic entities from {total_documents} documents")
            return result
            
        except Exception as e:
            self.logger.error(f"Error extracting geographic entities: {e}")
            return {
                'total_entities': 0,
                'mappable_entities': 0,
                'entities': [],
                'error': str(e)
            }
    
    def map_spatiotemporal_events(self, corpus_data: str, time_range: Optional[Dict] = None,
                                clustering_distance: float = 50.0, temporal_resolution: str = 'day') -> Dict[str, Any]:
        """
        Map events with spatial-temporal clustering analysis.
        
        Args:
            corpus_data: JSON string of documents to analyze
            time_range: Optional time range filter with 'start' and 'end' keys
            clustering_distance: Distance in km for spatial clustering
            temporal_resolution: Resolution for temporal clustering ('hour', 'day', 'week', 'month')
            
        Returns:
            Dictionary with spatiotemporal events and clustering analysis
        """
        try:
            # Parse corpus data
            if isinstance(corpus_data, str):
                corpus = json.loads(corpus_data)
            else:
                corpus = corpus_data
            
            events = []
            spatial_clusters = {}
            temporal_clusters = {}
            
            # Process documents to extract events
            documents = corpus if isinstance(corpus, list) else [corpus]
            
            for doc_idx, document in enumerate(documents):
                content = document.get('content', '') + ' ' + document.get('title', '')
                doc_date = document.get('date', datetime.now().isoformat())
                
                # Extract events and locations
                locations = self._extract_locations_from_text(content)
                event_types = self._extract_event_types(content)
                
                for location in locations:
                    location_key = location.lower()
                    coordinates = self.location_coordinates.get(location_key)
                    
                    if coordinates:
                        for event_type in event_types:
                            # Create event
                            event = {
                                'entity': location,
                                'event_type': event_type,
                                'latitude': coordinates[0],
                                'longitude': coordinates[1],
                                'timestamp': doc_date,
                                'confidence': self._calculate_event_confidence(event_type, content),
                                'context': self._extract_context(f"{event_type} {location}", content),
                                'document_id': document.get('id', doc_idx),
                                'source': document.get('source', 'unknown')
                            }
                            
                            # Apply time range filter if specified
                            if time_range:
                                event_time = datetime.fromisoformat(doc_date.replace('Z', '+00:00'))
                                start_time = datetime.fromisoformat(time_range['start'].replace('Z', '+00:00'))
                                end_time = datetime.fromisoformat(time_range['end'].replace('Z', '+00:00'))
                                
                                if not (start_time <= event_time <= end_time):
                                    continue
                            
                            events.append(event)
                            
                            # Spatial clustering
                            spatial_cluster = self._assign_spatial_cluster(
                                coordinates, spatial_clusters, clustering_distance
                            )
                            event['spatial_cluster'] = spatial_cluster
                            
                            # Temporal clustering
                            temporal_cluster = self._assign_temporal_cluster(
                                doc_date, temporal_clusters, temporal_resolution
                            )
                            event['temporal_cluster'] = temporal_cluster
            
            # Calculate cluster statistics
            cluster_stats = {}
            for cluster_name, events_in_cluster in spatial_clusters.items():
                cluster_stats[cluster_name] = len(events_in_cluster)
            
            result = {
                'total_events': len(events),
                'spatial_clusters': cluster_stats,
                'temporal_clusters': {k: len(v) for k, v in temporal_clusters.items()},
                'events': events,
                'clustering_metadata': {
                    'clustering_distance': clustering_distance,
                    'temporal_resolution': temporal_resolution,
                    'time_range': time_range,
                    'timestamp': datetime.now().isoformat()
                }
            }
            
            self.logger.info(f"Mapped {len(events)} spatiotemporal events with {len(cluster_stats)} spatial clusters")
            return result
            
        except Exception as e:
            self.logger.error(f"Error mapping spatiotemporal events: {e}")
            return {
                'total_events': 0,
                'spatial_clusters': {},
                'events': [],
                'error': str(e)
            }
    
    def query_geographic_context(self, query: str, corpus_data: str, radius_km: float = 100.0,
                               center_location: Optional[str] = None, include_related_entities: bool = True,
                               temporal_context: bool = True) -> Dict[str, Any]:
        """
        Perform natural language geographic queries with relationship discovery.
        
        Args:
            query: Natural language query (e.g., "financial events in New York")
            corpus_data: JSON string of documents to search
            radius_km: Search radius in kilometers
            center_location: Center location for geographic search
            include_related_entities: Whether to include related entities
            temporal_context: Whether to include temporal analysis
            
        Returns:
            Dictionary with query results and geographic context
        """
        try:
            # Parse corpus data
            if isinstance(corpus_data, str):
                corpus = json.loads(corpus_data)
            else:
                corpus = corpus_data
            
            # Parse query
            query_terms = self._parse_geographic_query(query)
            query_locations = query_terms.get('locations', [])
            query_events = query_terms.get('events', [])
            query_entities = query_terms.get('entities', [])
            
            # Set center coordinates
            center_coords = None
            if center_location:
                center_coords = self.location_coordinates.get(center_location.lower())
            elif query_locations:
                center_coords = self.location_coordinates.get(query_locations[0].lower())
            
            results = []
            
            # Process documents
            documents = corpus if isinstance(corpus, list) else [corpus]
            
            for doc_idx, document in enumerate(documents):
                content = document.get('content', '') + ' ' + document.get('title', '')
                
                # Check if document matches query
                relevance_score = self._calculate_query_relevance(query_terms, content)
                
                if relevance_score > 0.1:  # Minimum relevance threshold
                    # Extract entities from this document
                    locations = self._extract_locations_from_text(content)
                    
                    for location in locations:
                        location_key = location.lower()
                        coordinates = self.location_coordinates.get(location_key)
                        
                        if coordinates:
                            # Check if within radius
                            if center_coords:
                                distance = self._calculate_distance(center_coords, coordinates)
                                if distance > radius_km:
                                    continue
                            
                            # Create result entry
                            result_entry = {
                                'entity': location,
                                'entity_type': 'location',
                                'coordinates': coordinates,
                                'confidence': self._calculate_location_confidence(location, content),
                                'context_snippet': self._extract_context(location, content),
                                'relevance_score': relevance_score,
                                'document_id': document.get('id', doc_idx),
                                'document_title': document.get('title', f'Document {doc_idx}')
                            }
                            
                            # Add related entities if requested
                            if include_related_entities:
                                related = self._find_related_entities(location, content)
                                result_entry['related_entities'] = related
                            
                            # Add temporal context if requested
                            if temporal_context:
                                result_entry['temporal_context'] = {
                                    'document_date': document.get('date', datetime.now().isoformat()),
                                    'temporal_references': self._extract_temporal_references(content)
                                }
                            
                            results.append(result_entry)
            
            # Sort by relevance score
            results.sort(key=lambda x: x['relevance_score'], reverse=True)
            
            # Calculate geographic scope
            if results:
                lats = [r['coordinates'][0] for r in results]
                lngs = [r['coordinates'][1] for r in results]
                geographic_scope = {
                    'center': [sum(lats)/len(lats), sum(lngs)/len(lngs)],
                    'bounds': {
                        'north': max(lats),
                        'south': min(lats),
                        'east': max(lngs),
                        'west': min(lngs)
                    }
                }
            else:
                geographic_scope = None
            
            query_result = {
                'query': query,
                'total_results': len(results),
                'results': results,
                'query_metadata': {
                    'parsed_terms': query_terms,
                    'center_location': center_location,
                    'radius_km': radius_km,
                    'geographic_scope': geographic_scope,
                    'timestamp': datetime.now().isoformat()
                }
            }
            
            self.logger.info(f"Geographic query '{query}' returned {len(results)} results")
            return query_result
            
        except Exception as e:
            self.logger.error(f"Error processing geographic query: {e}")
            return {
                'query': query,
                'total_results': 0,
                'results': [],
                'error': str(e)
            }
    
    # Helper methods
    
    def _extract_locations_from_text(self, text: str) -> List[str]:
        """Extract location names from text using pattern matching."""
        locations = []
        
        # Known location patterns
        location_patterns = [
            r'\b(?:New York|NYC|Manhattan|Wall Street)\b',
            r'\b(?:Washington|Washington DC|Capitol Hill)\b',
            r'\b(?:London|The City|City of London)\b',
            r'\b(?:Silicon Valley|San Francisco|SF)\b',
            r'\b(?:Chicago|Los Angeles|Boston|Tokyo|Hong Kong|Singapore)\b',
            r'\b(?:Federal Reserve|NYSE|NASDAQ|Goldman Sachs|JPMorgan)\b'
        ]
        
        for pattern in location_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            locations.extend(matches)
        
        return list(set(locations))  # Remove duplicates
    
    def _extract_event_types(self, text: str) -> List[str]:
        """Extract event types from text."""
        event_patterns = {
            'trading': r'\b(?:trading|trade|market|exchange)\b',
            'announcement': r'\b(?:announce|announcement|declare|statement)\b',
            'meeting': r'\b(?:meeting|conference|summit|gathering)\b',
            'decision': r'\b(?:decision|ruling|verdict|judgment)\b',
            'investment': r'\b(?:investment|funding|capital|finance)\b',
            'regulation': r'\b(?:regulation|policy|law|compliance)\b'
        }
        
        events = []
        for event_type, pattern in event_patterns.items():
            if re.search(pattern, text, re.IGNORECASE):
                events.append(event_type)
        
        return events if events else ['general']
    
    def _calculate_location_confidence(self, location: str, context: str) -> float:
        """Calculate confidence score for location extraction."""
        base_confidence = 0.7
        
        # Boost confidence for known financial locations
        financial_terms = ['financial', 'bank', 'trading', 'market', 'exchange']
        for term in financial_terms:
            if term.lower() in context.lower():
                base_confidence += 0.05
        
        # Boost for proper capitalization
        if location[0].isupper():
            base_confidence += 0.1
        
        return min(base_confidence, 1.0)
    
    def _calculate_event_confidence(self, event_type: str, context: str) -> float:
        """Calculate confidence score for event extraction."""
        base_confidence = 0.6
        
        # Context-specific boosts
        if event_type in context.lower():
            base_confidence += 0.2
        
        return min(base_confidence, 1.0)
    
    def _extract_context(self, entity: str, text: str, window: int = 50) -> str:
        """Extract context snippet around entity mention."""
        entity_lower = entity.lower()
        text_lower = text.lower()
        
        start_pos = text_lower.find(entity_lower)
        if start_pos == -1:
            return text[:100] + "..." if len(text) > 100 else text
        
        start = max(0, start_pos - window)
        end = min(len(text), start_pos + len(entity) + window)
        
        snippet = text[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."
        
        return snippet
    
    def _assign_spatial_cluster(self, coordinates: List[float], clusters: Dict, max_distance: float) -> str:
        """Assign coordinates to a spatial cluster."""
        for cluster_name, cluster_points in clusters.items():
            for point in cluster_points:
                if self._calculate_distance(coordinates, point) <= max_distance:
                    cluster_points.append(coordinates)
                    return cluster_name
        
        # Create new cluster
        cluster_name = f"cluster_{len(clusters) + 1}"
        clusters[cluster_name] = [coordinates]
        return cluster_name
    
    def _assign_temporal_cluster(self, timestamp: str, clusters: Dict, resolution: str) -> str:
        """Assign timestamp to a temporal cluster."""
        try:
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            
            if resolution == 'hour':
                cluster_key = dt.strftime('%Y-%m-%d-%H')
            elif resolution == 'day':
                cluster_key = dt.strftime('%Y-%m-%d')
            elif resolution == 'week':
                cluster_key = f"{dt.year}-W{dt.isocalendar()[1]}"
            elif resolution == 'month':
                cluster_key = dt.strftime('%Y-%m')
            else:
                cluster_key = dt.strftime('%Y-%m-%d')
            
            if cluster_key not in clusters:
                clusters[cluster_key] = []
            clusters[cluster_key].append(timestamp)
            
            return cluster_key
            
        except (KeyError, ValueError, AttributeError, TypeError) as e:
            # Return unknown for any clustering errors
            logger.debug(f"Clustering error: {e}")
            return 'unknown'
    
    def _calculate_distance(self, coord1: List[float], coord2: List[float]) -> float:
        """Calculate approximate distance between two coordinates in km."""
        import math
        
        lat1, lon1 = math.radians(coord1[0]), math.radians(coord1[1])
        lat2, lon2 = math.radians(coord2[0]), math.radians(coord2[1])
        
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        
        # Earth's radius in km
        r = 6371
        
        return r * c
    
    def _parse_geographic_query(self, query: str) -> Dict[str, List[str]]:
        """Parse natural language query to extract locations, events, and entities."""
        query_lower = query.lower()
        
        # Extract locations
        locations = []
        for location in self.location_coordinates.keys():
            if location in query_lower:
                locations.append(location)
        
        # Extract event types
        events = []
        event_keywords = {
            'financial': ['financial', 'finance', 'money', 'investment', 'trading'],
            'political': ['political', 'government', 'policy', 'regulation'],
            'business': ['business', 'corporate', 'company', 'merger'],
            'legal': ['legal', 'lawsuit', 'court', 'litigation']
        }
        
        for event_type, keywords in event_keywords.items():
            if any(keyword in query_lower for keyword in keywords):
                events.append(event_type)
        
        # Extract entities (simplified)
        entities = []
        entity_patterns = [
            r'\b[A-Z][a-z]+ [A-Z][a-z]+\b',  # Proper names
            r'\b[A-Z]{2,}\b'  # Acronyms
        ]
        
        for pattern in entity_patterns:
            matches = re.findall(pattern, query)
            entities.extend(matches)
        
        return {
            'locations': locations,
            'events': events,
            'entities': entities,
            'raw_query': query
        }
    
    def _calculate_query_relevance(self, query_terms: Dict, content: str) -> float:
        """Calculate relevance score for document against query."""
        content_lower = content.lower()
        score = 0.0
        
        # Location relevance
        for location in query_terms.get('locations', []):
            if location in content_lower:
                score += 0.3
        
        # Event relevance
        for event in query_terms.get('events', []):
            if event in content_lower:
                score += 0.2
        
        # Entity relevance
        for entity in query_terms.get('entities', []):
            if entity.lower() in content_lower:
                score += 0.1
        
        return min(score, 1.0)
    
    def _find_related_entities(self, location: str, content: str) -> List[Dict[str, str]]:
        """Find entities related to a location in the content."""
        related = []
        
        # Simple pattern matching for organizations
        org_patterns = [
            r'\b[A-Z][a-z]+ [A-Z][a-z]+ (?:Bank|Corp|Inc|LLC|Ltd)\b',
            r'\b(?:Goldman Sachs|JPMorgan|Morgan Stanley|Federal Reserve)\b'
        ]
        
        for pattern in org_patterns:
            matches = re.findall(pattern, content)
            for match in matches:
                related.append({'entity': match, 'type': 'organization'})
        
        return related[:5]  # Limit to 5 related entities
    
    def _extract_temporal_references(self, content: str) -> List[str]:
        """Extract temporal references from content."""
        temporal_patterns = [
            r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b',
            r'\b\d{4}-\d{2}-\d{2}\b',
            r'\b(?:today|yesterday|tomorrow|this week|last week|next week)\b'
        ]
        
        references = []
        for pattern in temporal_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            references.extend(matches)
        
        return references[:3]  # Limit to 3 references


# Initialize the tools instance
geospatial_tools = GeospatialAnalysisTools()

# Export the tool functions for MCP integration
def extract_geographic_entities(corpus_data: str, confidence_threshold: float = 0.7, 
                              include_coordinates: bool = True) -> str:
    """MCP tool: Extract geographic entities from corpus data."""
    result = geospatial_tools.extract_geographic_entities(
        corpus_data, confidence_threshold, include_coordinates
    )
    return json.dumps(result)

def map_spatiotemporal_events(corpus_data: str, time_range: Optional[Dict] = None,
                            clustering_distance: float = 50.0, 
                            temporal_resolution: str = 'day') -> str:
    """MCP tool: Map events with spatial-temporal clustering analysis."""
    result = geospatial_tools.map_spatiotemporal_events(
        corpus_data, time_range, clustering_distance, temporal_resolution
    )
    return json.dumps(result)

def query_geographic_context(query: str, corpus_data: str, radius_km: float = 100.0,
                           center_location: Optional[str] = None, 
                           include_related_entities: bool = True,
                           temporal_context: bool = True) -> str:
    """MCP tool: Perform natural language geographic queries."""
    result = geospatial_tools.query_geographic_context(
        query, corpus_data, radius_km, center_location, 
        include_related_entities, temporal_context
    )
    return json.dumps(result)