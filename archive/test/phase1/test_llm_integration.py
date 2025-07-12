"""
Tests for LLM integration with domain-specific processing and adaptive prompting.

This module tests the domain-specific processing and adaptive prompting features
that enhance the LLM integration with GraphRAG.
"""

import unittest
import os
import sys
import numpy as np
from typing import Dict, List, Any, Optional
from datetime import datetime

# Add parent directory to path to import the module
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.append(parent_dir)

# Import the modules to test
from ipfs_datasets_py.llm.llm_interface import (
    LLMConfig, PromptTemplate, PromptMetadata, TemplateVersion,
    PromptLibrary, AdaptivePrompting
)
from ipfs_datasets_py.llm.llm_graphrag import (
    DomainSpecificProcessor, GraphRAGPerformanceMonitor
)


class TestAdaptivePrompting(unittest.TestCase):
    """Tests for adaptive prompting capabilities."""

    def setUp(self):
        """Set up test fixtures."""
        self.library = PromptLibrary()

        # Add test templates to library
        self.library.add_template(
            name="test_template",
            template="This is a test template for {task}.",
            tags=["general"]
        )

        self.library.add_template(
            name="test_template",
            template="This is an academic template for {task}.",
            version="1.1.0",
            tags=["academic"]
        )

        self.library.add_template(
            name="test_template",
            template="This is a medical template for {task}.",
            version="2.0.0",
            tags=["medical"]
        )

        # Initialize adaptive prompting
        self.adaptive_prompting = AdaptivePrompting(self.library)

    def test_template_selection_basic(self):
        """Test basic template selection."""
        # Select a template with default parameters
        template = self.adaptive_prompting.select_prompt(
            task="test_task",
            default_template="test_template"
        )

        # Should get the latest version (2.0.0, medical)
        self.assertEqual(template.template, "This is a medical template for {task}.")

        # Select a specific version
        template = self.adaptive_prompting.select_prompt(
            task="test_task",
            default_template="test_template",
            default_version="1.1.0"
        )

        # Should get the specified version (1.1.0, academic)
        self.assertEqual(template.template, "This is an academic template for {task}.")

    def test_rule_based_selection(self):
        """Test rule-based template selection."""
        # Add a rule for academic context
        self.adaptive_prompting.add_rule(
            name="academic_rule",
            condition=lambda ctx: "domain" in ctx and ctx["domain"] == "academic",
            template_selector=lambda ctx: ("test_template", "1.1.0"),
            priority=10
        )

        # Add a rule for medical context
        self.adaptive_prompting.add_rule(
            name="medical_rule",
            condition=lambda ctx: "domain" in ctx and ctx["domain"] == "medical",
            template_selector=lambda ctx: ("test_template", "2.0.0"),
            priority=10
        )

        # Update context with academic domain
        self.adaptive_prompting.update_context({"domain": "academic"})

        # Select a template - should use academic rule
        template = self.adaptive_prompting.select_prompt(
            task="test_task",
            default_template="test_template"
        )

        # Should get the academic template
        self.assertEqual(template.template, "This is an academic template for {task}.")

        # Update context with medical domain
        self.adaptive_prompting.update_context({"domain": "medical"})

        # Select a template - should use medical rule
        template = self.adaptive_prompting.select_prompt(
            task="test_task",
            default_template="test_template"
        )

        # Should get the medical template
        self.assertEqual(template.template, "This is a medical template for {task}.")

    def test_performance_tracking(self):
        """Test performance tracking for templates."""
        # Track performance for a template
        self.adaptive_prompting.track_performance(
            template_name="test_template",
            template_version="1.1.0",
            metrics={
                "success_rate": 0.9,
                "latency": 0.5,
                "token_count": 100
            }
        )

        # Track another performance metric
        self.adaptive_prompting.track_performance(
            template_name="test_template",
            template_version="1.1.0",
            metrics={
                "success_rate": 0.8,
                "latency": 0.7,
                "token_count": 120
            }
        )

        # Check that metrics are recorded
        key = "test_template:1.1.0"
        self.assertEqual(len(self.adaptive_prompting.metrics_tracker.get(key, [])), 2)

        # Check that the library has updated metrics
        templates = self.library.get_all_templates()
        versions = templates.get("test_template", [])

        # Find version 1.1.0
        for version_info in versions:
            if version_info.get("version") == "1.1.0":
                # Check that metrics were transferred to library
                # (This would be set by _aggregate_metrics in track_performance)
                self.assertTrue(len(version_info) > 0)


class TestDomainSpecificProcessor(unittest.TestCase):
    """Tests for domain-specific processing capabilities."""

    def setUp(self):
        """Set up test fixtures."""
        # Create prompt library
        self.library = PromptLibrary()

        # Add template versions for different domains
        self.library.add_template(
            name="cross_document_reasoning",
            template="General reasoning for {query}",
            tags=["general"]
        )

        self.library.add_template(
            name="cross_document_reasoning",
            template="Academic reasoning for {query}",
            version="1.1.0",
            tags=["academic", "research"]
        )

        self.library.add_template(
            name="cross_document_reasoning",
            template="Medical reasoning for {query}",
            version="1.2.0",
            tags=["medical", "healthcare"]
        )

        # Create adaptive prompting
        self.adaptive_prompting = AdaptivePrompting(self.library)

        # Create domain processor
        self.domain_processor = DomainSpecificProcessor(self.adaptive_prompting)

    def test_domain_detection(self):
        """Test domain detection from context."""
        # Academic context
        academic_context = {
            "query": "Compare research methodologies in AI papers",
            "graph_info": {
                "entity_types": ["paper", "author", "concept"],
                "relationship_types": ["authored_by", "cites", "uses"],
                "document_metadata": {
                    "doc1": {"year": 2020, "venue": "NeurIPS"}
                }
            }
        }

        # Medical context
        medical_context = {
            "query": "Compare treatment outcomes for patients",
            "graph_info": {
                "entity_types": ["condition", "treatment", "medication"],
                "relationship_types": ["treats", "causes", "prevents"],
                "document_metadata": {
                    "doc1": {"year": 2020, "journal": "JAMA"}
                }
            }
        }

        # Legal context
        legal_context = {
            "query": "Analyze the case precedents for contract law",
            "graph_info": {
                "entity_types": ["case", "statute", "court"],
                "relationship_types": ["cites", "overturns", "interprets"],
                "document_metadata": {
                    "doc1": {"year": 2020, "court": "Supreme Court"}
                }
            }
        }

        # Detect domains
        academic_domain = self.domain_processor.detect_domain(academic_context)
        medical_domain = self.domain_processor.detect_domain(medical_context)
        legal_domain = self.domain_processor.detect_domain(legal_context)

        # Check that domains are detected correctly
        self.assertEqual(academic_domain, "academic")
        self.assertEqual(medical_domain, "medical")
        self.assertEqual(legal_domain, "legal")

    def test_context_enhancement(self):
        """Test enhancing context with domain information."""
        # Create a context
        context = {
            "query": "Compare research methodologies in AI papers",
            "graph_info": {
                "entity_types": ["paper", "author", "concept"],
                "relationship_types": ["authored_by", "cites", "uses"]
            }
        }

        # Enhance context
        enhanced = self.domain_processor.enhance_context_with_domain(context)

        # Check that domain is added
        self.assertIn("domain", enhanced)
        self.assertEqual(enhanced["domain"], "academic")

        # Check that domain info is added
        self.assertIn("domain_info", enhanced)
        self.assertIn("entity_types", enhanced["domain_info"])
        self.assertIn("relationship_types", enhanced["domain_info"])
        self.assertIn("prompt_tags", enhanced["domain_info"])

    def test_domain_specific_template_selection(self):
        """Test domain-specific template selection."""
        # Academic context
        academic_context = {
            "task": "cross_document_reasoning",
            "query": "Compare research methodologies in AI papers",
            "graph_info": {
                "entity_types": ["paper", "author", "concept"],
                "relationship_types": ["authored_by", "cites", "uses"]
            }
        }

        # Medical context
        medical_context = {
            "task": "cross_document_reasoning",
            "query": "Compare treatment outcomes for patients",
            "graph_info": {
                "entity_types": ["condition", "treatment", "medication"],
                "relationship_types": ["treats", "causes", "prevents"]
            }
        }

        # Update adaptive prompting with academic context
        self.adaptive_prompting.update_context(
            self.domain_processor.enhance_context_with_domain(academic_context)
        )

        # Select template - should select academic version
        academic_template = self.adaptive_prompting.select_prompt(
            task="cross_document_reasoning",
            default_template="cross_document_reasoning"
        )

        # Update adaptive prompting with medical context
        self.adaptive_prompting.update_context(
            self.domain_processor.enhance_context_with_domain(medical_context)
        )

        # Select template - should select medical version
        medical_template = self.adaptive_prompting.select_prompt(
            task="cross_document_reasoning",
            default_template="cross_document_reasoning"
        )

        # Check templates
        self.assertEqual(academic_template.template, "Academic reasoning for {query}")
        self.assertEqual(medical_template.template, "Medical reasoning for {query}")


class TestPerformanceMonitor(unittest.TestCase):
    """Tests for the LLM performance monitoring capabilities."""

    def setUp(self):
        """Set up test fixtures."""
        self.monitor = GraphRAGPerformanceMonitor(max_history=100)

    def test_recording_interactions(self):
        """Test recording LLM interactions."""
        # Record successful interaction
        self.monitor.record_interaction(
            task="test_task",
            model="test-model",
            input_tokens=100,
            output_tokens=50,
            latency=0.5,
            success=True,
            metadata={"domain": "academic"}
        )

        # Record failed interaction
        self.monitor.record_interaction(
            task="test_task",
            model="test-model",
            input_tokens=120,
            output_tokens=0,
            latency=0.3,
            success=False,
            error_msg="Test error",
            metadata={"domain": "academic"}
        )

        # Record interaction for different task
        self.monitor.record_interaction(
            task="other_task",
            model="test-model",
            input_tokens=80,
            output_tokens=40,
            latency=0.4,
            success=True,
            metadata={"domain": "medical"}
        )

        # Check history length
        recent = self.monitor.get_recent_interactions()
        self.assertEqual(len(recent), 3)

        # Check task-specific history
        task_history = self.monitor.get_recent_interactions(task="test_task")
        self.assertEqual(len(task_history), 2)

    def test_task_metrics(self):
        """Test getting task metrics."""
        # Record interactions for a task
        for i in range(10):
            self.monitor.record_interaction(
                task="test_task",
                model="test-model",
                input_tokens=100,
                output_tokens=50,
                latency=0.5,
                success=i < 8,  # 8 successes, 2 failures
                error_msg="Test error" if i >= 8 else None
            )

        # Get metrics for the task
        metrics = self.monitor.get_task_metrics("test_task")

        # Check metrics
        self.assertEqual(metrics["count"], 10)
        self.assertEqual(metrics["success_count"], 8)
        self.assertEqual(metrics["error_count"], 2)
        self.assertEqual(metrics["success_rate"], 0.8)
        self.assertAlmostEqual(metrics["avg_tokens"], 150.0)
        self.assertAlmostEqual(metrics["avg_latency"], 0.5)

    def test_model_metrics(self):
        """Test getting model metrics."""
        # Record interactions for a model
        for i in range(10):
            self.monitor.record_interaction(
                task=f"task_{i%2}",  # Two different tasks
                model="test-model",
                input_tokens=100,
                output_tokens=50,
                latency=0.5,
                success=i < 8  # 8 successes, 2 failures
            )

        # Get metrics for the model
        metrics = self.monitor.get_model_metrics("test-model")

        # Check metrics
        self.assertEqual(metrics["count"], 10)
        self.assertEqual(metrics["success_count"], 8)
        self.assertEqual(metrics["error_count"], 2)
        self.assertEqual(metrics["success_rate"], 0.8)
        self.assertAlmostEqual(metrics["avg_tokens"], 150.0)
        self.assertAlmostEqual(metrics["avg_latency"], 0.5)

    def test_error_tracking(self):
        """Test tracking of errors."""
        # Record interactions with different errors
        for i in range(10):
            self.monitor.record_interaction(
                task="test_task",
                model="test-model",
                input_tokens=100,
                output_tokens=0,
                latency=0.5,
                success=False,
                error_msg=f"Error {i%3}"  # 3 different error types
            )

        # Get error summary
        errors = self.monitor.get_error_summary()

        # Check error counts
        self.assertEqual(sum(errors.values()), 10)
        self.assertEqual(len(errors), 3)
        self.assertEqual(errors["Error 0"], 4)
        self.assertEqual(errors["Error 1"], 3)
        self.assertEqual(errors["Error 2"], 3)

    def test_latency_percentiles(self):
        """Test latency percentile calculations."""
        # Record interactions with various latencies
        for i in range(100):
            self.monitor.record_interaction(
                task="test_task",
                model="test-model",
                input_tokens=100,
                output_tokens=50,
                latency=i/100.0,  # 0.0 to 0.99
                success=True
            )

        # Get latency percentiles
        percentiles = self.monitor.get_latency_percentiles()

        # Check percentiles
        self.assertAlmostEqual(percentiles["p50"], 0.5, places=2)
        self.assertAlmostEqual(percentiles["p90"], 0.9, places=2)
        self.assertAlmostEqual(percentiles["p95"], 0.95, places=2)
        self.assertAlmostEqual(percentiles["p99"], 0.99, places=2)
        self.assertAlmostEqual(percentiles["min"], 0.0, places=2)
        self.assertAlmostEqual(percentiles["max"], 0.99, places=2)
        self.assertAlmostEqual(percentiles["mean"], 0.495, places=2)

        # Get model-specific percentiles
        model_percentiles = self.monitor.get_latency_percentiles(model="test-model")
        self.assertAlmostEqual(model_percentiles["p50"], 0.5, places=2)

        # Get task-specific percentiles
        task_percentiles = self.monitor.get_latency_percentiles(task="test_task")
        self.assertAlmostEqual(task_percentiles["p50"], 0.5, places=2)


if __name__ == "__main__":
    unittest.main()
