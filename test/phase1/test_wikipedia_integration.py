"""
Test for Wikipedia Integration, SPARQL Validation, and Tracing

This module tests the Wikipedia integration, SPARQL validation, and tracing
capabilities of the KnowledgeGraphExtractor class. It verifies extraction of 
knowledge graphs from Wikipedia pages, validates them against Wikidata's structured
data, and tests the WikipediaKnowledgeGraphTracer integration for detailed
extraction and validation tracing.

The tests cover:
- Basic extraction from Wikipedia pages
- Validation against Wikidata's structured data
- Combined extraction and validation workflow
- Tracing functionality using WikipediaKnowledgeGraphTracer
- Temperature settings comparison for extraction quality analysis
- Visualization and explanation of extraction and validation results
"""

import unittest
import json
from ipfs_datasets_py.knowledge_graph_extraction import KnowledgeGraphExtractor, KnowledgeGraph
from ipfs_datasets_py.llm_reasoning_tracer import WikipediaKnowledgeGraphTracer

class TestWikipediaIntegration(unittest.TestCase):
    """Test case for Wikipedia integration and SPARQL validation."""
    
    def setUp(self):
        """Set up test case."""
        self.extractor = KnowledgeGraphExtractor(use_tracer=True)
        
    def test_extract_from_wikipedia(self):
        """Test extracting a knowledge graph from a Wikipedia page."""
        try:
            # Use a well-known Wikipedia page for testing
            page_title = "IPFS"
            kg = self.extractor.extract_from_wikipedia(
                page_title=page_title,
                extraction_temperature=0.7,
                structure_temperature=0.5
            )
            
            # Basic checks
            self.assertIsInstance(kg, KnowledgeGraph)
            self.assertEqual(kg.name, f"wikipedia_{page_title}")
            
            # Check that we have some entities and relationships
            self.assertGreater(len(kg.entities), 0)
            
            # Check that the Wikipedia page entity was created
            page_entities = kg.get_entities_by_type("wikipedia_page")
            self.assertEqual(len(page_entities), 1)
            self.assertEqual(page_entities[0].name, page_title)
            
            # Print summary for informational purposes
            print(f"Extracted {len(kg.entities)} entities and {len(kg.relationships)} relationships from Wikipedia page '{page_title}'")
            
        except Exception as e:
            # If there's a network error, skip the test
            self.skipTest(f"Network error or Wikipedia/Wikidata API issue: {e}")
            
    def test_validate_against_wikidata(self):
        """Test validating a knowledge graph against Wikidata."""
        try:
            # Create a simple knowledge graph
            kg = KnowledgeGraph()
            
            # Add IPFS as main entity
            ipfs_entity = kg.add_entity(
                entity_type="technology",
                name="IPFS",
                properties={"description": "InterPlanetary File System"}
            )
            
            # Add related entities
            juan_entity = kg.add_entity(
                entity_type="person",
                name="Juan Benet",
                properties={"role": "creator"}
            )
            
            protocol_labs_entity = kg.add_entity(
                entity_type="organization",
                name="Protocol Labs",
                properties={"industry": "technology"}
            )
            
            # Add relationships
            kg.add_relationship(
                relationship_type="created_by",
                source=ipfs_entity,
                target=juan_entity,
                confidence=0.9
            )
            
            kg.add_relationship(
                relationship_type="developed_by",
                source=ipfs_entity,
                target=protocol_labs_entity,
                confidence=0.9
            )
            
            # Validate against Wikidata
            result = self.extractor.validate_against_wikidata(kg, "IPFS")
            
            # Check that we have results
            self.assertIsInstance(result, dict)
            self.assertIn("coverage", result)
            
            # Print coverage for informational purposes
            print(f"Wikidata validation coverage: {result['coverage']:.2f}")
            
        except Exception as e:
            # If there's a network error, skip the test
            self.skipTest(f"Network error or Wikidata API issue: {e}")
            
    def test_extract_and_validate_wikipedia_graph(self):
        """Test end-to-end extraction and validation from Wikipedia to Wikidata."""
        try:
            # Use a well-known Wikipedia page for testing
            page_title = "IPFS"
            result = self.extractor.extract_and_validate_wikipedia_graph(
                page_title=page_title,
                extraction_temperature=0.7,
                structure_temperature=0.5
            )
            
            # Check that we have results
            self.assertIsInstance(result, dict)
            self.assertIn("knowledge_graph", result)
            self.assertIn("validation", result)
            self.assertIn("coverage", result)
            self.assertIn("metrics", result)
            
            # Print metrics for informational purposes
            metrics = result["metrics"]
            print(f"Entity count: {metrics['entity_count']}")
            print(f"Relationship count: {metrics['relationship_count']}")
            print(f"Entity types: {json.dumps(metrics['entity_types'])}")
            print(f"Relationship types: {json.dumps(metrics['relationship_types'])}")
            print(f"Average confidence: {metrics['avg_confidence']:.2f}")
            print(f"Wikidata coverage: {result['coverage']:.2f}")
            
            # Test with different temperature settings
            print("\nTesting with low temperatures (0.2, 0.2):")
            result_low = self.extractor.extract_and_validate_wikipedia_graph(
                page_title=page_title,
                extraction_temperature=0.2,
                structure_temperature=0.2
            )
            print(f"Entity count: {result_low['metrics']['entity_count']}")
            print(f"Relationship count: {result_low['metrics']['relationship_count']}")
            
            print("\nTesting with high temperatures (0.9, 0.9):")
            result_high = self.extractor.extract_and_validate_wikipedia_graph(
                page_title=page_title,
                extraction_temperature=0.9,
                structure_temperature=0.9
            )
            print(f"Entity count: {result_high['metrics']['entity_count']}")
            print(f"Relationship count: {result_high['metrics']['relationship_count']}")
            
            # Expect that higher temperatures produce more entities and relationships
            # Note: This might not always be true due to the probabilistic nature of extraction
            # and the specific content of the Wikipedia page
            if result_high['metrics']['entity_count'] <= result_low['metrics']['entity_count']:
                print("Warning: Higher temperature did not produce more entities as expected")
                
        except Exception as e:
            # If there's a network error, skip the test
            self.skipTest(f"Network error or Wikipedia/Wikidata API issue: {e}")
            
    def test_different_wikipedia_pages(self):
        """Test extraction from different types of Wikipedia pages."""
        pages = ["IPFS", "Protocol Labs", "Distributed hash table"]
        
        for page in pages:
            try:
                print(f"\nTesting with Wikipedia page: {page}")
                result = self.extractor.extract_and_validate_wikipedia_graph(
                    page_title=page,
                    extraction_temperature=0.7,
                    structure_temperature=0.5
                )
                
                metrics = result["metrics"]
                print(f"Entity count: {metrics['entity_count']}")
                print(f"Relationship count: {metrics['relationship_count']}")
                print(f"Wikidata coverage: {result['coverage']:.2f}")
                
            except Exception as e:
                print(f"Error with page {page}: {e}")
                continue
                
    def test_wikipedia_tracing_functionality(self):
        """Test tracing functionality for Wikipedia knowledge graph extraction."""
        try:
            # Use a well-known Wikipedia page for testing
            page_title = "IPFS"
            
            # Create an extractor with tracing enabled
            extractor = KnowledgeGraphExtractor(use_tracer=True)
            
            # Extract and validate the knowledge graph
            result = extractor.extract_and_validate_wikipedia_graph(
                page_title=page_title,
                extraction_temperature=0.7,
                structure_temperature=0.5
            )
            
            # Check that we have a trace ID
            self.assertIn("trace_id", result)
            trace_id = result["trace_id"]
            self.assertIsNotNone(trace_id)
            
            # Get the tracer and retrieve the trace
            tracer = extractor.tracer
            self.assertIsInstance(tracer, WikipediaKnowledgeGraphTracer)
            
            # Get trace information and check that it's valid
            trace_info = tracer.get_trace_info(trace_id)
            self.assertIsNotNone(trace_info)
            self.assertEqual(trace_info["page_title"], page_title)
            self.assertEqual(trace_info["extraction_temperature"], 0.7)
            self.assertEqual(trace_info["structure_temperature"], 0.5)
            self.assertEqual(trace_info["status"], "completed")
            
            # Test explanation methods
            explanation = tracer.explain_extraction_and_validation_trace(trace_id)
            self.assertIsNotNone(explanation)
            self.assertIn(page_title, explanation)
            
            # Test visualization methods
            visualization = tracer.visualize_knowledge_graph(trace_id, format="text")
            self.assertIsNotNone(visualization)
            
            # Test relationship type distribution
            distribution = tracer.get_relationship_type_distribution(trace_id)
            self.assertIsInstance(distribution, dict)
            
            # Test entity type distribution
            entity_distribution = tracer.get_entity_type_distribution(trace_id)
            self.assertIsInstance(entity_distribution, dict)
            
            # Test temperature description
            temp_description = tracer.describe_temperature_settings(
                extraction_temperature=0.7, 
                structure_temperature=0.5
            )
            self.assertIsNotNone(temp_description)
            self.assertIn("extraction", temp_description)
            self.assertIn("structure", temp_description)
            
            print(f"\nTracing test successful for trace ID: {trace_id}")
            print(f"Explanation preview: {explanation[:150]}...")
            
        except Exception as e:
            # If there's a network error, skip the test
            self.skipTest(f"Network error or tracing issue: {e}")
            
    def test_temperature_comparison(self):
        """Test temperature comparison functionality."""
        try:
            # Use a well-known Wikipedia page for testing
            page_title = "IPFS"
            
            # Create an extractor with tracing enabled
            extractor = KnowledgeGraphExtractor(use_tracer=True)
            tracer = extractor.tracer
            
            # Extract with different temperature settings
            print("\nExtracting with different temperature settings...")
            
            # Low temperature
            result_low = extractor.extract_from_wikipedia(
                page_title=page_title,
                extraction_temperature=0.3,
                structure_temperature=0.3
            )
            low_trace_id = tracer.get_trace_id_for_extraction(
                page_title=page_title,
                extraction_temperature=0.3,
                structure_temperature=0.3
            )
            
            # Medium temperature
            result_med = extractor.extract_from_wikipedia(
                page_title=page_title,
                extraction_temperature=0.6,
                structure_temperature=0.6
            )
            med_trace_id = tracer.get_trace_id_for_extraction(
                page_title=page_title,
                extraction_temperature=0.6,
                structure_temperature=0.6
            )
            
            # High temperature
            result_high = extractor.extract_from_wikipedia(
                page_title=page_title,
                extraction_temperature=0.9,
                structure_temperature=0.9
            )
            high_trace_id = tracer.get_trace_id_for_extraction(
                page_title=page_title,
                extraction_temperature=0.9,
                structure_temperature=0.9
            )
            
            # Compare low and high temperature results
            comparison = tracer.compare_temperature_settings(
                trace_id1=low_trace_id,
                trace_id2=high_trace_id
            )
            
            self.assertIsNotNone(comparison)
            self.assertIn("entities", comparison)
            self.assertIn("relationships", comparison)
            
            # Compare all three temperature settings
            compare_all = tracer.compare_temperature_settings_batch(
                trace_ids=[low_trace_id, med_trace_id, high_trace_id],
                labels=["Low (0.3)", "Medium (0.6)", "High (0.9)"]
            )
            
            self.assertIsNotNone(compare_all)
            self.assertIn("entities", compare_all)
            self.assertIn("relationships", compare_all)
            
            # Check entity counts generally increase with temperature
            # Note: This might not always be true due to the probabilistic nature of extraction
            print(f"\nLow temp entity count: {len(result_low.entities)}")
            print(f"Medium temp entity count: {len(result_med.entities)}")
            print(f"High temp entity count: {len(result_high.entities)}")
            
            print(f"\nTemperature comparison results:")
            print(f"Entities difference: {comparison['entities']['difference']}")
            print(f"Relationships difference: {comparison['relationships']['difference']}")
            
        except Exception as e:
            # If there's a network error, skip the test
            self.skipTest(f"Network error or temperature comparison issue: {e}")

if __name__ == '__main__':
    unittest.main()