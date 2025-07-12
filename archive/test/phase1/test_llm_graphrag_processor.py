"""
Tests for the GraphRAG LLM processor functionality.

This module tests the GraphRAG LLM processor that applies domain-specific
processing and schema generation for various reasoning tasks.
"""

import unittest
import os
import sys
import json
import numpy as np
from typing import Dict, List, Any, Optional
from unittest.mock import MagicMock, patch

# Add parent directory to path to import the module
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.append(parent_dir)

# Import the modules to test
from ipfs_datasets_py.llm.llm_interface import (
    LLMInterface, MockLLMInterface, LLMConfig, PromptTemplate,
    PromptLibrary, AdaptivePrompting
)
from ipfs_datasets_py.llm.llm_graphrag import (
    GraphRAGLLMProcessor, DomainSpecificProcessor, GraphRAGPerformanceMonitor
)


class TestGraphRAGLLMProcessor(unittest.TestCase):
    """Tests for the GraphRAG LLM processor."""

    def setUp(self):
        """Set up test fixtures."""
        # Create mock LLM interface
        self.mock_llm = MockLLMInterface()

        # Create prompt library
        self.library = PromptLibrary()

        # Create performance monitor
        self.monitor = GraphRAGPerformanceMonitor()

        # Create processor
        self.processor = GraphRAGLLMProcessor(
            llm_interface=self.mock_llm,
            prompt_library=self.library,
            performance_monitor=self.monitor
        )

        # Spy on the LLM calls
        self.original_generate_with_structured_output = self.mock_llm.generate_with_structured_output
        self.mock_llm.generate_with_structured_output = MagicMock(
            side_effect=self.original_generate_with_structured_output
        )

    def test_analyze_evidence_chain(self):
        """Test analyzing evidence chains between documents."""
        # Test documents and entity
        doc1 = {"id": "doc1", "title": "First Document"}
        doc2 = {"id": "doc2", "title": "Second Document"}
        entity = {"id": "entity1", "name": "Test Entity", "type": "Concept"}

        # Test contexts
        doc1_context = "This is context from document 1 about Test Entity."
        doc2_context = "This is context from document 2 about Test Entity."

        # Call the method
        result = self.processor.analyze_evidence_chain(
            doc1, doc2, entity, doc1_context, doc2_context
        )

        # Check that the LLM was called
        self.mock_llm.generate_with_structured_output.assert_called_once()

        # Check result format
        self.assertIn("relationship_type", result)
        self.assertIn("explanation", result)
        self.assertIn("inference", result)
        self.assertIn("confidence", result)

        # Relationship type should be one of the expected values
        self.assertIn(result["relationship_type"],
                      ["complementary", "contradictory", "identical", "unrelated"])

        # Confidence should be a float between 0 and 1
        self.assertIsInstance(result["confidence"], float)
        self.assertGreaterEqual(result["confidence"], 0.0)
        self.assertLessEqual(result["confidence"], 1.0)

        # Check performance tracking
        task_metrics = self.monitor.get_task_metrics("evidence_chain_analysis")
        self.assertEqual(task_metrics["count"], 1)
        self.assertEqual(task_metrics["success_count"], 1)

    def test_analyze_evidence_chain_error_handling(self):
        """Test error handling in analyze_evidence_chain."""
        # Mock LLM to raise an exception
        self.mock_llm.generate_with_structured_output = MagicMock(
            side_effect=Exception("Test error")
        )

        # Test documents and entity
        doc1 = {"id": "doc1", "title": "First Document"}
        doc2 = {"id": "doc2", "title": "Second Document"}
        entity = {"id": "entity1", "name": "Test Entity", "type": "Concept"}

        # Test contexts
        doc1_context = "This is context from document 1 about Test Entity."
        doc2_context = "This is context from document 2 about Test Entity."

        # Call the method - should not raise exception
        result = self.processor.analyze_evidence_chain(
            doc1, doc2, entity, doc1_context, doc2_context
        )

        # Check that error was handled gracefully
        self.assertIn("relationship_type", result)
        self.assertIn("explanation", result)
        self.assertIn("inference", result)
        self.assertIn("confidence", result)

        # Relationship type should be unknown
        self.assertEqual(result["relationship_type"], "unknown")

        # Explanation should mention error
        self.assertIn("Error", result["explanation"])

        # Check performance tracking
        task_metrics = self.monitor.get_task_metrics("evidence_chain_analysis")
        self.assertEqual(task_metrics["count"], 1)
        self.assertEqual(task_metrics["success_count"], 0)
        self.assertEqual(task_metrics["error_count"], 1)

    def test_identify_knowledge_gaps(self):
        """Test identifying knowledge gaps between documents."""
        # Test entity and document information
        entity = {"id": "entity1", "name": "Test Entity", "type": "Concept"}
        doc1_info = "Document 1 states that Test Entity was created in 2010."
        doc2_info = "Document 2 states that Test Entity has 5 components."

        # Call the method
        result = self.processor.identify_knowledge_gaps(entity, doc1_info, doc2_info)

        # Check result format
        self.assertIn("gaps_doc1_to_doc2", result)
        self.assertIn("gaps_doc2_to_doc1", result)
        self.assertIn("summary", result)

        # Gaps should be lists
        self.assertIsInstance(result["gaps_doc1_to_doc2"], list)
        self.assertIsInstance(result["gaps_doc2_to_doc1"], list)

        # Summary should be a string
        self.assertIsInstance(result["summary"], str)

    def test_generate_deep_inference(self):
        """Test generating deep inferences from document relationships."""
        # Test entity and documents
        entity = {"id": "entity1", "name": "Test Entity", "type": "Concept"}
        doc1 = {"id": "doc1", "title": "First Document"}
        doc2 = {"id": "doc2", "title": "Second Document"}

        # Test document information
        doc1_info = "Document 1 states that Test Entity was created in 2010."
        doc2_info = "Document 2 states that Test Entity has 5 components."

        # Test relationship type and knowledge gaps
        relation_type = "complementary"
        knowledge_gaps = {
            "summary": "Document 1 mentions creation date while Document 2 mentions components.",
            "gaps_doc1_to_doc2": ["Document 1 does not mention components."],
            "gaps_doc2_to_doc1": ["Document 2 does not mention creation date."]
        }

        # Call the method
        result = self.processor.generate_deep_inference(
            entity, doc1, doc2, doc1_info, doc2_info, relation_type, knowledge_gaps
        )

        # Check result format
        self.assertIn("inferences", result)
        self.assertIn("confidence", result)
        self.assertIn("explanation", result)

        # Inferences should be a list
        self.assertIsInstance(result["inferences"], list)
        self.assertTrue(len(result["inferences"]) > 0)

        # Confidence should be a float between 0 and 1
        self.assertIsInstance(result["confidence"], float)
        self.assertGreaterEqual(result["confidence"], 0.0)
        self.assertLessEqual(result["confidence"], 1.0)

    def test_analyze_transitive_relationships(self):
        """Test analyzing transitive relationships in entity chains."""
        # Test relationship chain
        relationship_chain = """
        Entity A is authored_by Person B
        Person B works_at Organization C
        Organization C funded_by Entity D
        """

        # Call the method
        result = self.processor.analyze_transitive_relationships(relationship_chain)

        # Check result format
        self.assertIn("transitive_relationships", result)
        self.assertIn("confidence", result)
        self.assertIn("explanation", result)

        # Transitive relationships should be a list
        self.assertIsInstance(result["transitive_relationships"], list)
        self.assertTrue(len(result["transitive_relationships"]) > 0)

    def test_synthesize_cross_document_reasoning(self):
        """Test synthesizing cross-document reasoning results."""
        # Test query and documents
        query = "What is the relationship between Document 1 and Document 2?"
        documents = [
            {"id": "doc1", "title": "Document 1", "content": "Content 1", "score": 0.9},
            {"id": "doc2", "title": "Document 2", "content": "Content 2", "score": 0.8}
        ]

        # Test connections
        connections = "Connection between Document 1 and Document 2 through Entity."

        # Test reasoning depths
        for depth in ["basic", "moderate", "deep"]:
            # Call the method
            result = self.processor.synthesize_cross_document_reasoning(
                query, documents, connections, depth
            )

            # Check result format
            self.assertIn("answer", result)
            self.assertIn("reasoning", result)
            self.assertIn("confidence", result)

            # Answer and reasoning should be strings
            self.assertIsInstance(result["answer"], str)
            self.assertIsInstance(result["reasoning"], str)

            # Confidence should be a float between 0 and 1
            self.assertIsInstance(result["confidence"], float)
            self.assertGreaterEqual(result["confidence"], 0.0)
            self.assertLessEqual(result["confidence"], 1.0)

            # Check domain-specific fields based on depth
            if depth in ["moderate", "deep"]:
                # Should have domain-specific fields
                enhanced_result = self.processor._enhance_result_for_domain(
                    result, "academic", depth
                )

                # Enhanced result should have additional fields
                self.assertIn("domain", enhanced_result)
                self.assertIn("reasoning_depth", enhanced_result)

            # Check performance tracking
            task_metrics = self.monitor.get_task_metrics("cross_document_reasoning")
            self.assertGreaterEqual(task_metrics["count"], 1)
            self.assertGreaterEqual(task_metrics["success_count"], 1)

    def test_domain_specific_schema_generation(self):
        """Test domain-specific schema generation."""
        # Test different domains
        domains = ["academic", "medical", "legal", "financial", "technical"]

        for domain in domains:
            # Get evidence chain schema
            evidence_schema = self.processor._get_evidence_chain_schema(domain)

            # Check common fields
            self.assertIn("properties", evidence_schema)
            self.assertIn("relationship_type", evidence_schema["properties"])
            self.assertIn("explanation", evidence_schema["properties"])
            self.assertIn("inference", evidence_schema["properties"])
            self.assertIn("confidence", evidence_schema["properties"])

            # Check domain-specific fields
            if domain == "academic":
                self.assertIn("scholarly_impact", evidence_schema["properties"])
                self.assertIn("research_implications", evidence_schema["properties"])
            elif domain == "medical":
                self.assertIn("clinical_relevance", evidence_schema["properties"])
                self.assertIn("certainty_level", evidence_schema["properties"])
            elif domain == "legal":
                self.assertIn("precedent_relationship", evidence_schema["properties"])
                self.assertIn("legal_significance", evidence_schema["properties"])
            elif domain == "financial":
                self.assertIn("market_implications", evidence_schema["properties"])
                self.assertIn("investment_relevance", evidence_schema["properties"])
            elif domain == "technical":
                self.assertIn("compatibility_impacts", evidence_schema["properties"])
                self.assertIn("implementation_considerations", evidence_schema["properties"])

            # Get cross-document reasoning schema
            for depth in ["basic", "moderate", "deep"]:
                reasoning_schema = self.processor._get_cross_document_reasoning_schema(
                    domain, depth
                )

                # Check common fields
                self.assertIn("properties", reasoning_schema)
                self.assertIn("answer", reasoning_schema["properties"])
                self.assertIn("reasoning", reasoning_schema["properties"])
                self.assertIn("confidence", reasoning_schema["properties"])

                # Check depth-specific fields
                if depth in ["moderate", "deep"]:
                    self.assertIn("evidence_strength", reasoning_schema["properties"])

                    if depth == "deep":
                        self.assertIn("alternative_interpretations", reasoning_schema["properties"])
                        self.assertIn("implications", reasoning_schema["properties"])

                # Check domain-specific fields
                if domain == "academic":
                    self.assertIn("research_implications", reasoning_schema["properties"])
                    self.assertIn("future_research_directions", reasoning_schema["properties"])
                elif domain == "medical":
                    self.assertIn("clinical_significance", reasoning_schema["properties"])
                    self.assertIn("certainty_level", reasoning_schema["properties"])
                elif domain == "legal":
                    self.assertIn("legal_principle", reasoning_schema["properties"])
                    self.assertIn("precedent_value", reasoning_schema["properties"])
                elif domain == "financial":
                    self.assertIn("market_impact", reasoning_schema["properties"])
                    self.assertIn("risk_assessment", reasoning_schema["properties"])
                elif domain == "technical":
                    self.assertIn("technical_implications", reasoning_schema["properties"])
                    self.assertIn("implementation_considerations", reasoning_schema["properties"])

    def test_domain_specific_formatting(self):
        """Test domain-specific document formatting."""
        # Test documents
        documents = [
            {
                "id": "doc1",
                "title": "Test Document",
                "content": "Content",
                "authors": "Author",
                "year": 2020
            }
        ]

        # Test different domains
        domains = ["academic", "medical", "legal", "financial", "technical"]

        for domain in domains:
            # Format documents
            formatted = self.processor._format_documents_for_domain(documents, domain)

            # Should be a string
            self.assertIsInstance(formatted, str)

            # Should include document title
            self.assertIn("Test Document", formatted)

            # Should include domain-specific formatting
            if domain == "academic":
                self.assertIn("PAPER", formatted)
                self.assertIn("AUTHORS", formatted)
            elif domain == "medical":
                self.assertIn("CLINICAL DOCUMENT", formatted)
                self.assertIn("DATE", formatted)
            elif domain == "legal":
                self.assertIn("LEGAL DOCUMENT", formatted)
                self.assertIn("JURISDICTION", formatted)
            elif domain == "financial":
                self.assertIn("FINANCIAL DOCUMENT", formatted)
                self.assertIn("COMPANY", formatted)
            elif domain == "technical":
                self.assertIn("TECHNICAL DOCUMENT", formatted)
                self.assertIn("COMPONENT", formatted)

    def test_result_enhancement(self):
        """Test result enhancement based on domain and reasoning depth."""
        # Base result
        base_result = {
            "answer": "Test answer",
            "reasoning": "Test reasoning",
            "confidence": 0.9
        }

        # Test domains
        domains = ["academic", "medical", "legal", "financial", "technical"]

        for domain in domains:
            # Enhance for each domain
            enhanced = self.processor._enhance_result_for_domain(
                base_result, domain, "deep"
            )

            # Check common fields
            self.assertIn("domain", enhanced)
            self.assertIn("reasoning_depth", enhanced)

            # Domain and reasoning depth should be correct
            self.assertEqual(enhanced["domain"], domain)
            self.assertEqual(enhanced["reasoning_depth"], "deep")

            # Should have references and knowledge gaps
            self.assertIn("references", enhanced)
            self.assertIn("knowledge_gaps", enhanced)

            # Check domain-specific enhancement logic
            if domain == "academic" and "research_implications" in enhanced:
                # Academic domain with research implications
                if "implications" not in enhanced:
                    # Test the logic to add implications from research_implications
                    enhanced["research_implications"] = "Implication 1. Implication 2."
                    enhanced = self.processor._enhance_result_for_domain(
                        enhanced, domain, "deep"
                    )
                    self.assertIn("implications", enhanced)


class TestReasoningEnhancer(unittest.TestCase):
    """Tests for the reasoning enhancer that integrates with datasets."""

    def setUp(self):
        """Set up test fixtures."""
        # Create mock LLM processor
        self.mock_processor = MagicMock()

        # Mock analyze_evidence_chain method
        self.mock_processor.analyze_evidence_chain.return_value = {
            "relationship_type": "complementary",
            "explanation": "Test explanation",
            "inference": "Test inference",
            "confidence": 0.9
        }

        # Mock identify_knowledge_gaps method
        self.mock_processor.identify_knowledge_gaps.return_value = {
            "gaps_doc1_to_doc2": ["Gap 1"],
            "gaps_doc2_to_doc1": ["Gap 2"],
            "summary": "Test summary"
        }

        # Mock generate_deep_inference method
        self.mock_processor.generate_deep_inference.return_value = {
            "inferences": ["Inference 1", "Inference 2"],
            "implications": ["Implication 1", "Implication 2"],
            "confidence": 0.9,
            "explanation": "Test explanation"
        }

        # Mock synthesize_cross_document_reasoning method
        self.mock_processor.synthesize_cross_document_reasoning.return_value = {
            "answer": "Test answer",
            "reasoning": "Test reasoning",
            "confidence": 0.9,
            "domain": "academic",
            "research_implications": "Test implications"
        }

        # Mock performance recorder
        self.mock_recorder = MagicMock()

        # Create enhancer
        self.enhancer = self.enhancer = GraphRAGIntegration

    def test_enhance_document_connections(self):
        """Test enhancing document connections with various reasoning depths."""
        # Create enhancer with mock processor
        enhancer = GraphRAGIntegration.ReasoningEnhancer(
            llm_processor=self.mock_processor,
            performance_recorder=self.mock_recorder
        )

        # Test documents and entity
        doc1 = {"id": "doc1", "title": "First Document"}
        doc2 = {"id": "doc2", "title": "Second Document"}
        entity = {"id": "entity1", "name": "Test Entity", "type": "Concept"}

        # Test contexts
        doc1_context = "Context from first document"
        doc2_context = "Context from second document"

        # Test with basic reasoning
        basic_result = enhancer.enhance_document_connections(
            doc1, doc2, entity, doc1_context, doc2_context, "basic"
        )

        # Check that processor was called correctly
        self.mock_processor.analyze_evidence_chain.assert_called_with(
            doc1, doc2, entity, doc1_context, doc2_context, None
        )

        # Check basic result format
        self.assertIn("connection_type", basic_result)
        self.assertIn("explanation", basic_result)
        self.assertIn("inference", basic_result)
        self.assertIn("confidence", basic_result)
        self.assertIn("reasoning_depth", basic_result)
        self.assertEqual(basic_result["reasoning_depth"], "basic")

        # Test with moderate reasoning
        moderate_result = enhancer.enhance_document_connections(
            doc1, doc2, entity, doc1_context, doc2_context, "moderate"
        )

        # Check that knowledge gaps were requested
        self.mock_processor.identify_knowledge_gaps.assert_called_with(
            entity, doc1_context, doc2_context
        )

        # Check moderate result format
        self.assertIn("knowledge_gaps", moderate_result)
        self.assertIn("specific_gaps", moderate_result)
        self.assertEqual(moderate_result["reasoning_depth"], "moderate")

        # Test with deep reasoning
        deep_result = enhancer.enhance_document_connections(
            doc1, doc2, entity, doc1_context, doc2_context, "deep"
        )

        # Check that deep inference was requested
        self.mock_processor.generate_deep_inference.assert_called()

        # Check deep result format
        self.assertIn("deep_inferences", deep_result)
        self.assertIn("implications", deep_result)
        self.assertIn("deep_explanation", deep_result)
        self.assertIn("deep_confidence", deep_result)
        self.assertEqual(deep_result["reasoning_depth"], "deep")

        # Check that performance recorder was called
        self.assertEqual(self.mock_recorder.call_count, 3)

    def test_enhance_cross_document_reasoning(self):
        """Test enhancing cross-document reasoning with various depths."""
        # Create enhancer with mock processor
        enhancer = GraphRAGIntegration.ReasoningEnhancer(
            llm_processor=self.mock_processor,
            performance_recorder=self.mock_recorder
        )

        # Test query and documents
        query = "Test query"
        documents = [
            {"id": "doc1", "title": "Document 1", "content": "Content 1", "score": 0.9},
            {"id": "doc2", "title": "Document 2", "content": "Content 2", "score": 0.8}
        ]

        # Test connections
        connections = [
            {
                "doc1": {"id": "doc1", "title": "Document 1"},
                "doc2": {"id": "doc2", "title": "Document 2"},
                "entity": {"id": "entity1", "name": "Entity 1", "type": "Concept"},
                "connection_type": "complementary",
                "explanation": "The documents complement each other."
            }
        ]

        # Test with various reasoning depths
        for depth in ["basic", "moderate", "deep"]:
            # Call the method
            result = enhancer.enhance_cross_document_reasoning(
                query, documents, connections, depth
            )

            # Check that processor was called correctly
            self.mock_processor.synthesize_cross_document_reasoning.assert_called()

            # Check result format
            self.assertIn("answer", result)
            self.assertIn("reasoning", result)
            self.assertIn("confidence", result)
            self.assertIn("references", result)
            self.assertIn("knowledge_gaps", result)
            self.assertIn("raw_connections", result)
            self.assertIn("reasoning_depth", result)
            self.assertIn("domain", result)

            # Domain-specific fields should be present
            self.assertIn("research_implications", result)

            # Reasoning depth should be correct
            self.assertEqual(result["reasoning_depth"], depth)

            # Check that performance recorder was called
            self.mock_recorder.assert_called()

    def test_format_connections_for_llm(self):
        """Test formatting connections for LLM."""
        # Create enhancer with mock processor
        enhancer = GraphRAGIntegration.ReasoningEnhancer(
            llm_processor=self.mock_processor
        )

        # Test connections
        connections = [
            {
                "doc1": {"id": "doc1", "title": "Document 1"},
                "doc2": {"id": "doc2", "title": "Document 2"},
                "entity": {"id": "entity1", "name": "Entity 1", "type": "Concept"},
                "connection_type": "complementary",
                "explanation": "The documents complement each other.",
                "inference": "Both documents provide information about Entity 1.",
                "knowledge_gaps": "Document 1 does not mention the creation date."
            }
        ]

        # Format for different reasoning depths
        for depth in ["basic", "moderate", "deep"]:
            # Format connections
            formatted = enhancer._format_connections_for_llm(connections, depth)

            # Should be a string
            self.assertIsInstance(formatted, str)

            # Should include document titles
            self.assertIn("Document 1", formatted)
            self.assertIn("Document 2", formatted)

            # Should include entity name and type
            self.assertIn("Entity 1", formatted)
            self.assertIn("Concept", formatted)

            # Should include relationship type
            self.assertIn("complementary", formatted)

            # Check depth-specific formatting
            if depth in ["moderate", "deep"]:
                # Moderate and deep should include explanation and inference
                self.assertIn("Explanation", formatted)
                self.assertIn("Inference", formatted)

                # Should include knowledge gaps
                self.assertIn("Knowledge Gaps", formatted)

                if depth == "deep":
                    # Deep should be detailed
                    pass  # No deep-specific fields in this test connection

        # Test with empty connections
        empty_formatted = enhancer._format_connections_for_llm([], "basic")
        self.assertIn("No connections", empty_formatted)


if __name__ == "__main__":
    unittest.main()
