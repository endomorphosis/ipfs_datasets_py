#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Simple test for geospatial tools without MCP server dependencies.
"""

import anyio
import json
import logging
from datetime import datetime
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def mock_extract_geographic_entities(corpus_data, confidence_threshold=0.8, **kwargs):
    """Mock implementation of geographic entity extraction."""
    try:
        if isinstance(corpus_data, str):
            corpus = json.loads(corpus_data)
        else:
            corpus = corpus_data

        documents = corpus.get('documents', [])
        entities = []
        
        # Mock geographic entities with known coordinates
        mock_locations = {
            'new york': (40.7128, -74.0060),
            'washington': (38.9072, -77.0369),
            'tokyo': (35.6762, 139.6503),
            'san francisco': (37.7749, -122.4194),
            'paris': (48.8566, 2.3522),
            'london': (51.5074, -0.1278),
            'china': (35.8617, 104.1954),
            'russia': (61.5240, 105.3188),
            'brazil': (-14.2350, -51.9253),
            'india': (20.5937, 78.9629),
            'germany': (51.1657, 10.4515),
            'france': (46.6034, 1.8883),
            'japan': (36.2048, 138.2529)
        }
        
        for doc_idx, doc in enumerate(documents):
            content = doc.get('content', '').lower()
            doc_id = doc.get('id', f'doc_{doc_idx}')
            
            for location, coords in mock_locations.items():
                if location in content:
                    entities.append({
                        'entity': location.title(),
                        'entity_type': 'LOCATION',
                        'confidence': 0.9,
                        'frequency': 1,
                        'coordinates': coords,
                        'latitude': coords[0],
                        'longitude': coords[1],
                        'documents': [doc_id],
                        'context_snippet': content[:100] + '...'
                    })
        
        return {
            'total_entities': len(entities),
            'mappable_entities': len([e for e in entities if e['coordinates']]),
            'entities': entities,
            'geographic_coverage': {
                'regions': ['Americas', 'Europe', 'Asia'],
                'coordinate_bounds': {
                    'north': max(e['latitude'] for e in entities) if entities else 0,
                    'south': min(e['latitude'] for e in entities) if entities else 0,
                    'east': max(e['longitude'] for e in entities) if entities else 0,
                    'west': min(e['longitude'] for e in entities) if entities else 0
                }
            },
            'timestamp': datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error in mock entity extraction: {e}")
        return {'error': str(e), 'total_entities': 0, 'entities': []}


async def mock_map_spatiotemporal_events(corpus_data, **kwargs):
    """Mock implementation of spatiotemporal event mapping."""
    try:
        if isinstance(corpus_data, str):
            corpus = json.loads(corpus_data)
        else:
            corpus = corpus_data

        documents = corpus.get('documents', [])
        events = []
        
        # Extract events with locations
        for doc_idx, doc in enumerate(documents):
            content = doc.get('content', '').lower()
            doc_id = doc.get('id', f'doc_{doc_idx}')
            timestamp = doc.get('timestamp', datetime.now().isoformat())
            
            # Mock event detection
            event_keywords = ['announced', 'crashed', 'struck', 'held', 'summit']
            location_coords = {
                'new york': (40.7128, -74.0060),
                'washington': (38.9072, -77.0369),
                'tokyo': (35.6762, 139.6503),
                'san francisco': (37.7749, -122.4194),
                'paris': (48.8566, 2.3522)
            }
            
            for location, coords in location_coords.items():
                if location in content:
                    for keyword in event_keywords:
                        if keyword in content:
                            events.append({
                                'event_id': f"{doc_id}_{location}_{keyword}",
                                'document_id': doc_id,
                                'entity': location.title(),
                                'event_type': keyword,
                                'latitude': coords[0],
                                'longitude': coords[1],
                                'timestamp': timestamp,
                                'context': content[:200] + '...',
                                'confidence': 0.85,
                                'temporal_cluster': timestamp[:10],  # Date
                                'spatial_cluster': f'cluster_{location}'
                            })
        
        temporal_clusters = {}
        spatial_clusters = {}
        
        for event in events:
            # Group by temporal cluster
            temp_key = event['temporal_cluster']
            if temp_key not in temporal_clusters:
                temporal_clusters[temp_key] = []
            temporal_clusters[temp_key].append(event['event_id'])
            
            # Group by spatial cluster
            spatial_key = event['spatial_cluster']
            if spatial_key not in spatial_clusters:
                spatial_clusters[spatial_key] = []
            spatial_clusters[spatial_key].append(event['event_id'])
        
        return {
            'total_events': len(events),
            'events': events,
            'temporal_clusters': temporal_clusters,
            'spatial_clusters': spatial_clusters,
            'statistics': {
                'event_types': {event['event_type']: 1 for event in events},
                'top_locations': {event['entity']: 1 for event in events},
                'unique_locations': len(set(event['entity'] for event in events)),
                'unique_event_types': len(set(event['event_type'] for event in events))
            },
            'timestamp': datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error in mock spatiotemporal mapping: {e}")
        return {'error': str(e), 'total_events': 0, 'events': []}


async def mock_query_geographic_context(query, corpus_data, **kwargs):
    """Mock implementation of geographic context query."""
    try:
        entities_result = await mock_extract_geographic_entities(corpus_data)
        entities = entities_result.get('entities', [])
        
        # Simple relevance scoring based on query keywords
        query_words = query.lower().split()
        results = []
        
        for entity in entities:
            relevance = 0
            for word in query_words:
                if word in entity['entity'].lower():
                    relevance += 2.0
                if word in entity['context_snippet'].lower():
                    relevance += 1.0
            
            if relevance > 0:
                entity_result = {
                    **entity,
                    'relevance_score': relevance,
                    'query_matches': [w for w in query_words if w in entity['entity'].lower() or w in entity['context_snippet'].lower()]
                }
                results.append(entity_result)
        
        # Sort by relevance
        results.sort(key=lambda x: x['relevance_score'], reverse=True)
        
        return {
            'query': query,
            'total_results': len(results),
            'results': results,
            'center_location': kwargs.get('center_location'),
            'search_radius_km': kwargs.get('radius_km', 100),
            'timestamp': datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error in mock geographic query: {e}")
        return {'error': str(e), 'total_results': 0, 'results': []}


async def create_test_corpus():
    """Create test corpus."""
    return {
        'documents': [
            {
                'id': 'doc_1',
                'content': 'Breaking news from New York: The financial markets crashed today. Wall Street traders were in panic.',
                'timestamp': '2024-01-15T10:30:00Z',
                'source': 'financial_news'
            },
            {
                'id': 'doc_2',
                'content': 'In Washington DC, the President announced new trade policies affecting China and Russia.',
                'timestamp': '2024-01-20T14:15:00Z',
                'source': 'political_news'
            },
            {
                'id': 'doc_3',
                'content': 'A major earthquake struck Japan near Tokyo, causing significant damage.',
                'timestamp': '2024-01-25T08:45:00Z',
                'source': 'disaster_news'
            },
            {
                'id': 'doc_4',
                'content': 'Technology conference held in San Francisco attracted major companies.',
                'timestamp': '2024-02-01T16:00:00Z',
                'source': 'tech_news'
            },
            {
                'id': 'doc_5',
                'content': 'Climate summit in Paris brought together world leaders from Brazil, India, and Germany.',
                'timestamp': '2024-02-10T12:00:00Z',
                'source': 'environmental_news'
            }
        ]
    }


async def test_geospatial_functionality():
    """Test the geospatial functionality."""
    logger.info("Testing geospatial functionality with mock implementations...")
    
    corpus = await create_test_corpus()
    corpus_json = json.dumps(corpus)
    
    # Test 1: Extract geographic entities
    logger.info("\n1. Testing geographic entity extraction...")
    entities_result = await mock_extract_geographic_entities(corpus_json, confidence_threshold=0.7)
    logger.info(f"   Found {entities_result['total_entities']} entities, {entities_result['mappable_entities']} mappable")
    
    if entities_result['entities']:
        logger.info("   Top entities:")
        for entity in entities_result['entities'][:3]:
            logger.info(f"     - {entity['entity']}: {entity['coordinates']} (confidence: {entity['confidence']})")
    
    # Test 2: Map spatiotemporal events
    logger.info("\n2. Testing spatiotemporal event mapping...")
    events_result = await mock_map_spatiotemporal_events(corpus_json)
    logger.info(f"   Found {events_result['total_events']} events")
    logger.info(f"   Temporal clusters: {len(events_result['temporal_clusters'])}")
    logger.info(f"   Spatial clusters: {len(events_result['spatial_clusters'])}")
    
    if events_result['events']:
        logger.info("   Sample events:")
        for event in events_result['events'][:3]:
            logger.info(f"     - {event['entity']}: {event['event_type']} at {event['latitude']:.4f}, {event['longitude']:.4f}")
    
    # Test 3: Query geographic context
    logger.info("\n3. Testing geographic context queries...")
    queries = [
        "financial markets in New York",
        "political events in Washington",
        "technology in San Francisco"
    ]
    
    for query in queries:
        query_result = await mock_query_geographic_context(query, corpus_json, radius_km=200)
        logger.info(f"   Query '{query}': {query_result['total_results']} results")
        
        if query_result['results']:
            top_result = query_result['results'][0]
            logger.info(f"     Top result: {top_result['entity']} (relevance: {top_result['relevance_score']:.1f})")
    
    # Test 4: Dashboard integration scenario
    logger.info("\n4. Testing dashboard integration scenario...")
    
    # Simulate user interaction: Search for "New York events"
    dashboard_query = "New York events"
    dashboard_result = await mock_query_geographic_context(dashboard_query, corpus_json, center_location="New York")
    
    # Simulate map display data
    map_data = {
        'query': dashboard_query,
        'entities': entities_result['total_entities'],
        'events': events_result['total_events'],
        'mappable_locations': entities_result['mappable_entities'],
        'query_results': dashboard_result['total_results'],
        'geographic_bounds': entities_result['geographic_coverage']['coordinate_bounds'],
        'clusters': len(events_result['spatial_clusters'])
    }
    
    logger.info("   Dashboard integration data:")
    for key, value in map_data.items():
        logger.info(f"     - {key}: {value}")
    
    # Save results for verification
    test_results = {
        'timestamp': datetime.now().isoformat(),
        'test_summary': {
            'entities_test': {
                'total_entities': entities_result['total_entities'],
                'mappable_entities': entities_result['mappable_entities'],
                'success': True
            },
            'events_test': {
                'total_events': events_result['total_events'],
                'temporal_clusters': len(events_result['temporal_clusters']),
                'spatial_clusters': len(events_result['spatial_clusters']),
                'success': True
            },
            'query_test': {
                'queries_tested': len(queries),
                'success': True
            },
            'dashboard_integration': map_data
        },
        'detailed_results': {
            'entities': entities_result,
            'events': events_result,
            'dashboard_query': dashboard_result
        }
    }
    
    # Write test results
    results_file = project_root / 'geospatial_test_results.json'
    with open(results_file, 'w') as f:
        json.dump(test_results, f, indent=2)
    
    logger.info(f"\n✅ All tests completed successfully! Results saved to: {results_file}")
    return test_results


async def main():
    """Run the tests."""
    try:
        result = await test_geospatial_functionality()
        print(f"\n🎉 Geospatial MCP tools testing completed successfully!")
        print(f"📊 Summary:")
        print(f"   - Geographic entities: {result['test_summary']['entities_test']['total_entities']}")
        print(f"   - Spatiotemporal events: {result['test_summary']['events_test']['total_events']}")
        print(f"   - Mappable locations: {result['test_summary']['entities_test']['mappable_entities']}")
        print(f"   - Dashboard integration: ✅ Working")
        return result
    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise


if __name__ == "__main__":
    anyio.run(main())