#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test script for geospatial MCP tools and dashboard integration.

This script tests the new geospatial analysis tools and the Maps tab functionality.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

# Add the project root to the path
import sys
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from ipfs_datasets_py.mcp_server.tools.investigation_tools.geospatial_analysis_tools import (
    extract_geographic_entities,
    map_spatiotemporal_events,
    query_geographic_context
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def create_test_corpus():
    """Create a test corpus with geographic and temporal data."""
    test_documents = [
        {
            'id': 'doc_1',
            'content': 'Breaking news from New York: The financial markets crashed today. Wall Street traders were in panic as stocks fell dramatically. This event has global implications for London and Tokyo markets.',
            'timestamp': '2024-01-15T10:30:00Z',
            'source': 'financial_news'
        },
        {
            'id': 'doc_2', 
            'content': 'In Washington DC, the President announced new trade policies affecting China and Russia. The announcement was made at the White House during a press conference.',
            'timestamp': '2024-01-20T14:15:00Z',
            'source': 'political_news'
        },
        {
            'id': 'doc_3',
            'content': 'A major earthquake struck Japan near Tokyo, causing significant damage. Emergency services in Tokyo responded quickly. The tremor was felt across the region including in nearby cities.',
            'timestamp': '2024-01-25T08:45:00Z',
            'source': 'disaster_news'
        },
        {
            'id': 'doc_4',
            'content': 'Technology conference held in San Francisco attracted major companies from Silicon Valley. Google, Apple, and Meta announced their latest innovations. The event was attended by thousands.',
            'timestamp': '2024-02-01T16:00:00Z',
            'source': 'tech_news'
        },
        {
            'id': 'doc_5',
            'content': 'Climate summit in Paris brought together world leaders to discuss environmental policies. France hosted delegates from around the world including representatives from Brazil, India, and Germany.',
            'timestamp': '2024-02-10T12:00:00Z',
            'source': 'environmental_news'
        }
    ]
    
    return {
        'documents': test_documents,
        'metadata': {
            'total_documents': len(test_documents),
            'date_range': '2024-01-15 to 2024-02-10',
            'sources': ['financial_news', 'political_news', 'disaster_news', 'tech_news', 'environmental_news']
        }
    }


async def test_extract_geographic_entities():
    """Test geographic entity extraction."""
    logger.info("Testing geographic entity extraction...")
    
    corpus = await create_test_corpus()
    corpus_json = json.dumps(corpus)
    
    result = await extract_geographic_entities(
        corpus_data=corpus_json,
        confidence_threshold=0.6,
        include_coordinates=True
    )
    
    logger.info(f"Extracted {result['total_entities']} geographic entities")
    logger.info(f"Mappable entities: {result['mappable_entities']}")
    
    if result['entities']:
        logger.info("Top entities:")
        for entity in result['entities'][:5]:
            coords = entity.get('coordinates', 'N/A')
            logger.info(f"  - {entity['entity']}: {coords} (confidence: {entity['confidence']:.2f})")
    
    return result


async def test_spatiotemporal_mapping():
    """Test spatiotemporal event mapping."""
    logger.info("Testing spatiotemporal event mapping...")
    
    corpus = await create_test_corpus()
    corpus_json = json.dumps(corpus)
    
    # Test with time range
    time_range = {
        'start': '2024-01-01T00:00:00Z',
        'end': '2024-02-28T23:59:59Z'
    }
    
    result = await map_spatiotemporal_events(
        corpus_data=corpus_json,
        time_range=time_range,
        clustering_distance=100.0,
        temporal_resolution='day'
    )
    
    logger.info(f"Mapped {result['total_events']} spatiotemporal events")
    logger.info(f"Temporal clusters: {len(result.get('temporal_clusters', {}))}")
    logger.info(f"Spatial clusters: {len(result.get('spatial_clusters', {}))}")
    
    if result['events']:
        logger.info("Sample events:")
        for event in result['events'][:3]:
            logger.info(f"  - {event['entity']}: {event['event_type']} at {event['latitude']:.4f}, {event['longitude']:.4f}")
    
    return result


async def test_geographic_context_query():
    """Test geographic context querying."""
    logger.info("Testing geographic context query...")
    
    corpus = await create_test_corpus()
    corpus_json = json.dumps(corpus)
    
    # Test different types of queries
    queries = [
        "financial markets in New York",
        "political events in Washington",
        "technology companies in San Francisco", 
        "events near Tokyo"
    ]
    
    results = {}
    for query in queries:
        result = await query_geographic_context(
            query=query,
            corpus_data=corpus_json,
            radius_km=200.0,
            center_location="New York",
            include_related_entities=True
        )
        
        results[query] = result
        logger.info(f"Query '{query}': {result['total_results']} results")
        
        if result['results']:
            for entity in result['results'][:2]:
                logger.info(f"  - {entity['entity']}: relevance {entity['relevance_score']:.2f}")
    
    return results


async def test_dashboard_integration():
    """Test dashboard integration scenarios."""
    logger.info("Testing dashboard integration scenarios...")
    
    corpus = await create_test_corpus()
    
    # Scenario 1: User searches for "New York financial events"
    logger.info("Scenario 1: User searches for 'New York financial events'")
    query_result = await query_geographic_context(
        query="New York financial events",
        corpus_data=json.dumps(corpus),
        center_location="New York",
        radius_km=100.0
    )
    
    # Scenario 2: Extract all locations for map overview
    logger.info("Scenario 2: Extract all locations for map overview")
    entities_result = await extract_geographic_entities(
        corpus_data=json.dumps(corpus),
        confidence_threshold=0.7
    )
    
    # Scenario 3: Analyze events in January 2024
    logger.info("Scenario 3: Analyze events in January 2024")
    events_result = await map_spatiotemporal_events(
        corpus_data=json.dumps(corpus),
        time_range={
            'start': '2024-01-01T00:00:00Z',
            'end': '2024-01-31T23:59:59Z'
        },
        clustering_distance=50.0
    )
    
    # Generate summary for dashboard
    summary = {
        'total_locations': entities_result['total_entities'],
        'mappable_locations': entities_result['mappable_entities'],
        'total_events': events_result['total_events'],
        'query_results': query_result['total_results'],
        'geographic_coverage': entities_result.get('geographic_coverage', {}),
        'temporal_span': len(events_result.get('temporal_clusters', {})),
        'spatial_clusters': len(events_result.get('spatial_clusters', {}))
    }
    
    logger.info("Dashboard Integration Summary:")
    for key, value in summary.items():
        logger.info(f"  - {key}: {value}")
    
    return summary


async def main():
    """Run all geospatial tests."""
    logger.info("Starting geospatial MCP tools tests...")
    
    try:
        # Test individual tools
        entities_result = await test_extract_geographic_entities()
        events_result = await test_spatiotemporal_mapping() 
        query_results = await test_geographic_context_query()
        
        # Test dashboard integration
        dashboard_summary = await test_dashboard_integration()
        
        # Save test results
        test_results = {
            'timestamp': datetime.now().isoformat(),
            'entities_extraction': {
                'total_entities': entities_result['total_entities'],
                'mappable_entities': entities_result['mappable_entities'],
                'success': True
            },
            'spatiotemporal_mapping': {
                'total_events': events_result['total_events'],
                'temporal_clusters': len(events_result.get('temporal_clusters', {})),
                'spatial_clusters': len(events_result.get('spatial_clusters', {})),
                'success': True
            },
            'geographic_queries': {
                'queries_tested': len(query_results),
                'total_results': sum(r['total_results'] for r in query_results.values()),
                'success': True
            },
            'dashboard_integration': dashboard_summary,
            'overall_success': True
        }
        
        # Write results to file
        results_file = project_root / 'geospatial_test_results.json'
        with open(results_file, 'w') as f:
            json.dump(test_results, f, indent=2)
        
        logger.info(f"Test results saved to: {results_file}")
        logger.info("All geospatial tests completed successfully!")
        
        return test_results
        
    except Exception as e:
        logger.error(f"Test failed: {str(e)}")
        raise


if __name__ == "__main__":
    asyncio.run(main())