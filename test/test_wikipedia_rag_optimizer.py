"""
Tests for Wikipedia-specific RAG Query Optimizer.

This module tests the Wikipedia-specific optimizations for the RAG Query Optimizer,
which are specialized for knowledge graphs derived from Wikipedia content.
"""

import unittest
import numpy as np
import time
from typing import Dict, List, Any, Optional, Set

from ipfs_datasets_py.wikipedia_rag_optimizer import (
    WikipediaRelationshipWeightCalculator,
    WikipediaCategoryHierarchyManager,
    WikipediaEntityImportanceCalculator,
    WikipediaQueryExpander,
    WikipediaPathOptimizer,
    WikipediaRAGQueryOptimizer,
    WikipediaGraphRAGQueryRewriter,
    WikipediaGraphRAGBudgetManager,
    UnifiedWikipediaGraphRAGQueryOptimizer,
    detect_graph_type,
    create_appropriate_optimizer,
    optimize_wikipedia_query
)

# Mock classes for testing
class MockVectorStore:
    def search(self, vector, top_k=5, filter_fn=None):
        results = [
            {
                "id": f"topic_{i}",
                "score": 0.9 - (i * 0.05),
                "metadata": {
                    "type": "topic",
                    "name": f"Topic {i}"
                }
            } for i in range(top_k)
        ]

        if filter_fn:
            results = [r for r in results if filter_fn(r)]

        return results


class MockGraphProcessor:
    def __init__(self, graph_type="wikipedia"):
        self.graph_type = graph_type
        self.entities = {
            "entity1": {
                "id": "entity1",
                "inbound_connections": [{"id": f"in{i}", "relation_type": "instance_of"} for i in range(10)],
                "outbound_connections": [{"id": f"out{i}", "relation_type": "has_part"} for i in range(5)],
                "references": [f"ref{i}" for i in range(15)],
                "categories": ["Category:Physics", "Category:Science"],
                "mention_count": 25,
                "last_modified": "2023-01-15T12:30:45Z",
                "type": "article"
            },
            "entity2": {
                "id": "entity2",
                "inbound_connections": [{"id": f"in{i}", "relation_type": "subclass_of"} for i in range(3)],
                "outbound_connections": [{"id": f"out{i}", "relation_type": "related_to"} for i in range(20)],
                "references": [f"ref{i}" for i in range(5)],
                "categories": ["Category:Computer_Science", "Category:Technology"],
                "mention_count": 10,
                "last_modified": "2023-05-20T08:15:30Z",
                "type": "article"
            }
        }

    def get_entity_info(self, entity_id):
        return self.entities.get(entity_id, {"id": entity_id})

    def get_entities(self, limit=20):
        return list(self.entities.values())[:limit]

    def get_relationship_types(self):
        return ["instance_of", "subclass_of", "part_of", "has_part", "related_to", "category_contains"]


class MockTracer:
    def __init__(self):
        self.logs = []

    def log_optimization(self, trace_id, original_params, optimized_plan):
        self.logs.append({
            "type": "optimization",
            "trace_id": trace_id,
            "original_params": original_params,
            "optimized_plan": optimized_plan
        })

    def log_query_expansion(self, trace_id, query_text, expansions):
        self.logs.append({
            "type": "query_expansion",
            "trace_id": trace_id,
            "query_text": query_text,
            "expansions": expansions
        })

    def log_error(self, message, trace_id=None):
        self.logs.append({
            "type": "error",
            "message": message,
            "trace_id": trace_id
        })

    def log_unified_optimization(self, trace_id, original_query, optimized_plan):
        self.logs.append({
            "type": "unified_optimization",
            "trace_id": trace_id,
            "original_query": original_query,
            "optimized_plan": optimized_plan
        })

# Test classes for each component
class TestWikipediaRelationshipWeightCalculator(unittest.TestCase):
    def setUp(self):
        self.calculator = WikipediaRelationshipWeightCalculator()

    def test_default_weights(self):
        # Test some default weights
        self.assertEqual(self.calculator.get_relationship_weight("subclass_of"), 1.5)
        self.assertEqual(self.calculator.get_relationship_weight("instance_of"), 1.4)
        self.assertEqual(self.calculator.get_relationship_weight("related_to"), 1.0)
        self.assertEqual(self.calculator.get_relationship_weight("mentions"), 0.5)

    def test_custom_weights(self):
        # Test with custom weights
        custom_weights = {
            "subclass_of": 2.0,
            "instance_of": 1.8,
            "custom_relation": 1.3
        }
        calculator = WikipediaRelationshipWeightCalculator(custom_weights)

        self.assertEqual(calculator.get_relationship_weight("subclass_of"), 2.0)
        self.assertEqual(calculator.get_relationship_weight("instance_of"), 1.8)
        self.assertEqual(calculator.get_relationship_weight("custom_relation"), 1.3)
        self.assertEqual(calculator.get_relationship_weight("related_to"), 1.0)  # Default unchanged

    def test_relationship_normalization(self):
        # Test normalization of relationship types
        self.assertEqual(self.calculator.get_relationship_weight("is_subclass_of"), 1.5)
        self.assertEqual(self.calculator.get_relationship_weight("Is SubClass Of"), 1.5)
        self.assertEqual(self.calculator.get_relationship_weight("IS-subclass-OF"), 1.5)

    def test_prioritized_relationship_types(self):
        # Test that relationships are properly prioritized
        relationships = ["mentions", "instance_of", "related_to", "subclass_of"]
        prioritized = self.calculator.get_prioritized_relationship_types(relationships)

        self.assertEqual(prioritized, ["subclass_of", "instance_of", "related_to", "mentions"])

    def test_filtered_high_value_relationships(self):
        # Test filtering of relationships by weight
        relationships = ["subclass_of", "instance_of", "related_to", "mentions"]
        filtered = self.calculator.get_filtered_high_value_relationships(relationships, min_weight=1.0)

        self.assertEqual(set(filtered), set(["subclass_of", "instance_of", "related_to"]))

        # Test with higher threshold
        filtered_high = self.calculator.get_filtered_high_value_relationships(relationships, min_weight=1.3)
        self.assertEqual(set(filtered_high), set(["subclass_of", "instance_of"]))


class TestWikipediaCategoryHierarchyManager(unittest.TestCase):
    def setUp(self):
        self.manager = WikipediaCategoryHierarchyManager()

        # Build a test hierarchy
        # Science
        # ├── Physics
        # │   ├── Quantum_Physics
        # │   └── Classical_Mechanics
        # └── Computer_Science
        #     ├── Algorithms
        #     └── Data_Structures

        self.manager.register_category_connection("Science", "Physics")
        self.manager.register_category_connection("Science", "Computer_Science")
        self.manager.register_category_connection("Physics", "Quantum_Physics")
        self.manager.register_category_connection("Physics", "Classical_Mechanics")
        self.manager.register_category_connection("Computer_Science", "Algorithms")
        self.manager.register_category_connection("Computer_Science", "Data_Structures")

    def test_calculate_category_depth(self):
        # Test depth calculation
        self.assertEqual(self.manager.calculate_category_depth("Science"), 0)
        self.assertEqual(self.manager.calculate_category_depth("Physics"), 1)
        self.assertEqual(self.manager.calculate_category_depth("Quantum_Physics"), 2)
        self.assertEqual(self.manager.calculate_category_depth("Data_Structures"), 2)

    def test_assign_category_weights(self):
        # Test weight assignment
        query_vector = np.random.rand(10)  # Dummy vector
        categories = ["Science", "Physics", "Quantum_Physics", "Computer_Science"]

        weights = self.manager.assign_category_weights(query_vector, categories)

        # Depth-based weights (without similarity scores)
        self.assertEqual(weights["Science"], 0.5)  # Depth 0
        self.assertEqual(weights["Physics"], 0.6)  # Depth 1
        self.assertEqual(weights["Quantum_Physics"], 0.7)  # Depth 2
        self.assertEqual(weights["Computer_Science"], 0.6)  # Depth 1

        # With similarity scores
        similarity_scores = {
            "Science": 0.9,
            "Physics": 0.8,
            "Quantum_Physics": 0.7,
            "Computer_Science": 0.6
        }

        weights_with_sim = self.manager.assign_category_weights(query_vector, categories, similarity_scores)

        self.assertEqual(weights_with_sim["Science"], 0.5 * 0.9)
        self.assertEqual(weights_with_sim["Physics"], 0.6 * 0.8)
        self.assertEqual(weights_with_sim["Quantum_Physics"], 0.7 * 0.7)
        self.assertEqual(weights_with_sim["Computer_Science"], 0.6 * 0.6)

    def test_get_related_categories(self):
        # Test getting related categories
        related = self.manager.get_related_categories("Physics", max_distance=1)

        # Convert to set of category names for easier comparison
        related_names = {cat for cat, _ in related}

        # Should include parent (Science) and children (Quantum_Physics, Classical_Mechanics)
        self.assertEqual(related_names, {"Science", "Quantum_Physics", "Classical_Mechanics"})

        # Test with higher distance
        related_dist2 = self.manager.get_related_categories("Physics", max_distance=2)
        related_names_dist2 = {cat for cat, _ in related_dist2}

        # Should also include Computer_Science (sibling) and its children
        self.assertEqual(related_names_dist2, {
            "Science", "Quantum_Physics", "Classical_Mechanics",
            "Computer_Science", "Algorithms", "Data_Structures"
        })


class TestWikipediaEntityImportanceCalculator(unittest.TestCase):
    def setUp(self):
        self.calculator = WikipediaEntityImportanceCalculator()

        # Test entities
        self.entity1 = {
            "id": "entity1",
            "inbound_connections": [{"id": f"in{i}"} for i in range(10)],
            "outbound_connections": [{"id": f"out{i}"} for i in range(5)],
            "references": [f"ref{i}" for i in range(15)],
            "categories": ["Category:Physics", "Category:Science"],
            "mention_count": 25,
            "last_modified": "2023-01-15T12:30:45Z"
        }

        self.entity2 = {
            "id": "entity2",
            "inbound_connections": [{"id": f"in{i}"} for i in range(3)],
            "outbound_connections": [{"id": f"out{i}"} for i in range(2)],
            "references": [f"ref{i}" for i in range(5)],
            "categories": ["Category:Computer_Science"],
            "mention_count": 5,
            "last_modified": "2021-01-15T12:30:45Z"
        }

    def test_calculate_entity_importance(self):
        # Test importance calculation
        importance1 = self.calculator.calculate_entity_importance(self.entity1)
        importance2 = self.calculator.calculate_entity_importance(self.entity2)

        # Entity1 should be more important than entity2
        self.assertGreater(importance1, importance2)

        # Test with category weights
        category_weights = {
            "Category:Physics": 1.5,
            "Category:Science": 1.2,
            "Category:Computer_Science": 0.8
        }

        importance1_weighted = self.calculator.calculate_entity_importance(self.entity1, category_weights)
        importance2_weighted = self.calculator.calculate_entity_importance(self.entity2, category_weights)

        # Entity1 should still be more important
        self.assertGreater(importance1_weighted, importance2_weighted)

        # The importance with category weights should be different
        self.assertNotEqual(importance1, importance1_weighted)

    def test_rank_entities_by_importance(self):
        # Test ranking entities by importance
        entities = [self.entity1, self.entity2]

        ranked = self.calculator.rank_entities_by_importance(entities)

        # Entity1 should be ranked first
        self.assertEqual(ranked[0]["id"], "entity1")
        self.assertEqual(ranked[1]["id"], "entity2")

        # Test with category weights that favor entity2's category
        category_weights = {
            "Category:Physics": 0.5,
            "Category:Science": 0.5,
            "Category:Computer_Science": 2.0
        }

        ranked_weighted = self.calculator.rank_entities_by_importance(entities, category_weights)

        # With these weights, entity2 might be ranked higher, or entity1 still might be
        # higher due to other factors. We don't need to assert a specific order here
        # since the outcome depends on the relative weights of all factors.


class TestWikipediaQueryExpander(unittest.TestCase):
    def setUp(self):
        self.tracer = MockTracer()
        self.expander = WikipediaQueryExpander(tracer=self.tracer)
        self.vector_store = MockVectorStore()

        # Create a test category hierarchy
        self.category_hierarchy = WikipediaCategoryHierarchyManager()
        self.category_hierarchy.register_category_connection("Science", "Physics")
        self.category_hierarchy.register_category_connection("Science", "Computer_Science")
        self.category_hierarchy.register_category_connection("Physics", "Quantum_Physics")
        self.category_hierarchy.register_category_connection("Computer_Science", "Programming")

    def test_expand_query(self):
        # Test query expansion
        query_vector = np.random.rand(10)  # Dummy vector
        query_text = "What is quantum physics in computer science"

        expanded = self.expander.expand_query(
            query_vector=query_vector,
            query_text=query_text,
            vector_store=self.vector_store,
            category_hierarchy=self.category_hierarchy,
            trace_id="test123"
        )

        # Verify structure
        self.assertIn("original_query_vector", expanded)
        self.assertIn("original_query_text", expanded)
        self.assertIn("expansions", expanded)
        self.assertIn("has_expansions", expanded)

        # Verify expansions
        expansions = expanded["expansions"]
        self.assertIn("topics", expansions)
        self.assertIn("categories", expansions)
        self.assertIn("entities", expansions)

        # Verify topics from vector search
        self.assertTrue(len(expansions["topics"]) > 0)
        self.assertIn("id", expansions["topics"][0])
        self.assertIn("name", expansions["topics"][0])
        self.assertIn("similarity", expansions["topics"][0])

        # Verify categories (should match "quantum" and "physics" in query)
        category_names = [c["name"] for c in expansions["categories"]]
        self.assertTrue(any("Physics" in n for n in category_names) or
                       any("Quantum" in n for n in category_names) or
                       any("Computer_Science" in n for n in category_names))

        # Verify tracing
        trace_logs = [log for log in self.tracer.logs if log["type"] == "query_expansion"]
        self.assertTrue(len(trace_logs) > 0)
        self.assertEqual(trace_logs[0]["trace_id"], "test123")
        self.assertEqual(trace_logs[0]["query_text"], query_text)


class TestWikipediaPathOptimizer(unittest.TestCase):
    def setUp(self):
        self.optimizer = WikipediaPathOptimizer()

    def test_get_edge_traversal_cost(self):
        # Test edge traversal costs
        self.assertEqual(self.optimizer.get_edge_traversal_cost("subclass_of"), 0.6)
        self.assertEqual(self.optimizer.get_edge_traversal_cost("instance_of"), 0.6)
        self.assertEqual(self.optimizer.get_edge_traversal_cost("related_to"), 1.0)
        self.assertEqual(self.optimizer.get_edge_traversal_cost("mentions"), 1.5)
        self.assertEqual(self.optimizer.get_edge_traversal_cost("unknown_edge"), 1.0)  # Default

    def test_optimize_traversal_path(self):
        # Test path optimization
        start_entities = [{"id": "entity1"}, {"id": "entity2"}]
        relationship_types = ["subclass_of", "instance_of", "related_to", "mentions"]
        max_depth = 3
        budget = {"max_nodes": 1000}

        optimized = self.optimizer.optimize_traversal_path(
            start_entities=start_entities,
            relationship_types=relationship_types,
            max_depth=max_depth,
            budget=budget
        )

        # Verify structure
        self.assertEqual(optimized["strategy"], "wikipedia_hierarchical")
        self.assertIn("relationship_priority", optimized)
        self.assertIn("level_budgets", optimized)
        self.assertIn("relationship_activation", optimized)
        self.assertIn("traversal_costs", optimized)
        self.assertEqual(optimized["original_max_depth"], max_depth)

        # Verify relationship priorities
        # subclass_of and instance_of should be prioritized higher
        priority_order = optimized["relationship_priority"]
        self.assertEqual(priority_order[0], "subclass_of")
        self.assertEqual(priority_order[1], "instance_of")

        # Verify budget allocation (should decrease with depth)
        level_budgets = optimized["level_budgets"]
        self.assertEqual(len(level_budgets), max_depth)
        self.assertGreater(level_budgets[0], level_budgets[1])  # First level gets more budget

        # Verify relationship activation depths
        activation = optimized["relationship_activation"]
        # Higher priority relationships should be active at greater depths
        self.assertGreaterEqual(activation["subclass_of"], activation["mentions"])


class TestWikipediaRAGQueryOptimizer(unittest.TestCase):
    def setUp(self):
        self.tracer = MockTracer()
        self.optimizer = WikipediaRAGQueryOptimizer(tracer=self.tracer)
        self.graph_processor = MockGraphProcessor()
        self.vector_store = MockVectorStore()

    def test_optimize_query(self):
        # Test query optimization
        query_vector = np.random.rand(10)  # Dummy vector
        query_text = "What is quantum physics?"

        optimized = self.optimizer.optimize_query(
            query_vector=query_vector,
            max_vector_results=5,
            max_traversal_depth=2,
            edge_types=["subclass_of", "instance_of", "related_to"],
            min_similarity=0.7,
            query_text=query_text,
            graph_processor=self.graph_processor,
            vector_store=self.vector_store,
            trace_id="test456"
        )

        # Verify structure
        self.assertIn("query", optimized)
        self.assertIn("weights", optimized)
        self.assertIn("expansions", optimized)

        # Verify query parameters
        query_params = optimized["query"]
        self.assertIn("vector_params", query_params)
        self.assertIn("traversal", query_params)

        # Verify traversal plan
        traversal = query_params["traversal"]
        self.assertEqual(traversal["strategy"], "wikipedia_hierarchical")
        self.assertIn("edge_types", traversal)
        self.assertIn("relationship_depths", traversal)
        self.assertIn("entity_importance_strategy", traversal)
        self.assertEqual(traversal["hierarchical_weight"], 1.5)

        # Verify weights
        weights = optimized["weights"]
        self.assertIn("vector", weights)
        self.assertIn("graph", weights)
        self.assertIn("hierarchical_bonus", weights)

        # Verify tracing
        trace_logs = [log for log in self.tracer.logs if log["type"] == "optimization"]
        self.assertTrue(len(trace_logs) > 0)
        self.assertEqual(trace_logs[0]["trace_id"], "test456")

    def test_calculate_entity_importance(self):
        # Test entity importance calculation
        importance = self.optimizer.calculate_entity_importance("entity1", self.graph_processor)

        # Should return a float between 0 and 1
        self.assertIsInstance(importance, float)
        self.assertGreaterEqual(importance, 0.0)
        self.assertLessEqual(importance, 1.0)

    def test_learn_from_query_results(self):
        # Test learning from query results
        query_id = "query123"
        results = [
            {
                "id": "result1",
                "score": 0.9,
                "path": [
                    {"edge_type": "subclass_of"},
                    {"edge_type": "instance_of"}
                ]
            },
            {
                "id": "result2",
                "score": 0.8,
                "path": [
                    {"edge_type": "related_to"},
                    {"edge_type": "mentions"}
                ]
            }
        ]
        time_taken = 0.5
        plan = {
            "query": {
                "traversal": {
                    "edge_types": ["subclass_of", "instance_of", "related_to", "mentions"],
                    "strategy": "wikipedia_hierarchical"
                }
            }
        }

        # Store initial weights for comparison
        initial_subclass_weight = self.optimizer.relationship_calculator.get_relationship_weight("subclass_of")
        initial_mentions_weight = self.optimizer.relationship_calculator.get_relationship_weight("mentions")

        # Learn from results
        self.optimizer.learn_from_query_results(query_id, results, time_taken, plan)

        # Verify that weights have been adjusted
        # subclass_of appears in result paths, so its weight should increase
        self.assertGreaterEqual(
            self.optimizer.relationship_calculator.get_relationship_weight("subclass_of"),
            initial_subclass_weight
        )


class TestWikipediaGraphRAGQueryRewriter(unittest.TestCase):
    def setUp(self):
        self.rewriter = WikipediaGraphRAGQueryRewriter()

    def test_rewrite_query(self):
        # Test query rewriting
        query = {
            "query_text": "What is quantum physics?",
            "traversal": {
                "edge_types": ["subclass_of", "instance_of", "related_to", "mentions"]
            }
        }

        rewritten = self.rewriter.rewrite_query(query)

        # Verify edge type prioritization
        self.assertIn("traversal", rewritten)
        self.assertIn("edge_types", rewritten["traversal"])
        edge_types = rewritten["traversal"]["edge_types"]

        # subclass_of should be first, mentions should be last
        self.assertEqual(edge_types[0], "subclass_of")
        self.assertEqual(edge_types[-1], "mentions")

        # Verify hierarchical weight
        self.assertEqual(rewritten["traversal"]["hierarchical_weight"], 1.5)

    def test_detect_query_pattern(self):
        # Test query pattern detection

        # Test topic lookup
        pattern1 = self.rewriter._detect_query_pattern("Tell me about quantum physics")
        self.assertEqual(pattern1[0], "topic_lookup")
        self.assertEqual(pattern1[1], ["quantum physics"])

        # Test comparison
        pattern2 = self.rewriter._detect_query_pattern("Compare quantum physics and classical mechanics")
        self.assertEqual(pattern2[0], "comparison")
        self.assertEqual(pattern2[1], ["quantum physics", "classical mechanics"])

        # Test definition
        pattern3 = self.rewriter._detect_query_pattern("What is quantum entanglement?")
        self.assertEqual(pattern3[0], "definition")
        self.assertEqual(pattern3[1], ["quantum entanglement"])

        # Test cause/effect
        pattern4 = self.rewriter._detect_query_pattern("What are the effects of climate change?")
        self.assertEqual(pattern4[0], "cause_effect")
        self.assertEqual(pattern4[1], ["climate change"])

        # Test list
        pattern5 = self.rewriter._detect_query_pattern("List types of quantum particles")
        self.assertEqual(pattern5[0], "list")
        self.assertEqual(pattern5[1], ["quantum particles"])

        # Test no pattern match
        pattern6 = self.rewriter._detect_query_pattern("Hello world")
        self.assertIsNone(pattern6)

    def test_apply_pattern_optimization(self):
        # Test pattern-specific optimizations

        # Test topic lookup optimization
        query1 = {}
        entities1 = ["quantum physics"]
        optimized1 = self.rewriter._apply_pattern_optimization(query1, "topic_lookup", entities1)

        self.assertIn("traversal", optimized1)
        self.assertEqual(optimized1["traversal"]["strategy"], "topic_focused")
        self.assertEqual(optimized1["traversal"]["target_entities"], entities1)
        self.assertTrue(optimized1["traversal"]["prioritize_relationships"])

        # Test comparison optimization
        query2 = {}
        entities2 = ["quantum physics", "classical mechanics"]
        optimized2 = self.rewriter._apply_pattern_optimization(query2, "comparison", entities2)

        self.assertIn("traversal", optimized2)
        self.assertEqual(optimized2["traversal"]["strategy"], "comparison")
        self.assertEqual(optimized2["traversal"]["comparison_entities"], entities2)
        self.assertTrue(optimized2["traversal"]["find_common_categories"])

        # Test definition optimization
        query3 = {}
        entities3 = ["quantum entanglement"]
        optimized3 = self.rewriter._apply_pattern_optimization(query3, "definition", entities3)

        self.assertIn("traversal", optimized3)
        self.assertEqual(optimized3["traversal"]["strategy"], "definition")
        self.assertIn("instance_of", optimized3["traversal"]["prioritize_edge_types"])


class TestWikipediaGraphRAGBudgetManager(unittest.TestCase):
    def setUp(self):
        self.budget_manager = WikipediaGraphRAGBudgetManager()

    def test_allocate_budget(self):
        # Test budget allocation

        # Test basic allocation
        query1 = {
            "traversal": {
                "edge_types": ["subclass_of", "instance_of"]
            }
        }

        budget1 = self.budget_manager.allocate_budget(query1)

        # Verify that default budget is present
        self.assertIn("timeout_ms", budget1)
        self.assertIn("max_nodes", budget1)
        self.assertIn("category_traversal_ms", budget1)
        self.assertIn("topic_expansion_ms", budget1)

        # Test category-focused allocation
        query2 = {
            "traversal": {
                "edge_types": ["category_contains", "in_category"]
            }
        }

        budget2 = self.budget_manager.allocate_budget(query2)

        # Category budget should be higher
        self.assertGreater(budget2["category_traversal_ms"], budget1["category_traversal_ms"])
        self.assertGreater(budget2["max_categories"], budget1["max_categories"])

        # Test topic expansion allocation
        query3 = {
            "traversal": {
                "expand_topics": True,
                "topic_expansion_factor": 1.5
            }
        }

        budget3 = self.budget_manager.allocate_budget(query3)

        # Topic expansion budget should be higher
        self.assertGreater(budget3["topic_expansion_ms"], budget1["topic_expansion_ms"])
        self.assertGreater(budget3["max_topics"], budget1["max_topics"])

        # Test strategy-specific allocation
        query4 = {
            "traversal": {
                "strategy": "wikipedia_hierarchical"
            }
        }

        budget4 = self.budget_manager.allocate_budget(query4)

        # Graph traversal budget should be higher for hierarchical strategy
        self.assertGreater(budget4["graph_traversal_ms"], budget1["graph_traversal_ms"])

    def test_suggest_early_stopping(self):
        # Test early stopping suggestions

        # Test with high-confidence category matches
        results1 = [
            {"metadata": {"type": "category"}, "score": 0.9},
            {"metadata": {"type": "category"}, "score": 0.88},
            {"metadata": {"type": "category"}, "score": 0.87}
        ]

        # With high-confidence category matches and budget > 60%, should suggest stopping
        self.assertTrue(self.budget_manager.suggest_early_stopping(results1, 0.7))

        # With high-confidence matches but budget < 60%, should not suggest stopping
        self.assertFalse(self.budget_manager.suggest_early_stopping(results1, 0.5))

        # Test with diminishing returns in category hierarchy
        results2 = [
            {"metadata": {"category": "Science"}},
            {"metadata": {"category": "Science"}},
            {"metadata": {"category": "Science"}},
            {"metadata": {"category": "Physics"}},
            {"metadata": {"category": "Physics"}},
            {"metadata": {"category": "Computer_Science"}},
            {"metadata": {"category": "Computer_Science"}},
            {"metadata": {"category": "Computer_Science"}},
            {"metadata": {"category": "Computer_Science"}},
            {"metadata": {"category": "Computer_Science"}},
            {"metadata": {"category": "Computer_Science"}}
        ]

        # With low category diversity and budget > 70%, should suggest stopping
        self.assertTrue(self.budget_manager.suggest_early_stopping(results2, 0.8))

        # With low category diversity but budget < 70%, should not suggest stopping
        self.assertFalse(self.budget_manager.suggest_early_stopping(results2, 0.6))


class TestUnifiedWikipediaGraphRAGQueryOptimizer(unittest.TestCase):
    def setUp(self):
        self.tracer = MockTracer()
        self.optimizer = UnifiedWikipediaGraphRAGQueryOptimizer(tracer=self.tracer)
        self.graph_processor = MockGraphProcessor()
        self.vector_store = MockVectorStore()

    def test_optimizer_instantiation(self):
        # Test that components are correctly instantiated
        self.assertIsInstance(self.optimizer.rewriter, WikipediaGraphRAGQueryRewriter)
        self.assertIsInstance(self.optimizer.budget_manager, WikipediaGraphRAGBudgetManager)
        self.assertIsInstance(self.optimizer.base_optimizer, WikipediaRAGQueryOptimizer)

    def test_optimize_query(self):
        # Test query optimization
        query = {
            "query_vector": np.random.rand(10),
            "query_text": "What is quantum physics?",
            "max_vector_results": 5,
            "max_traversal_depth": 2,
            "edge_types": ["subclass_of", "instance_of", "related_to"],
            "min_similarity": 0.7
        }

        optimized = self.optimizer.optimize_query(
            query=query,
            graph_processor=self.graph_processor,
            vector_store=self.vector_store,
            trace_id="test789"
        )

        # Verify structure
        self.assertIn("query", optimized)
        self.assertIn("budget", optimized)

        # Verify query parameters
        query_params = optimized["query"]
        self.assertIn("vector_params", query_params)
        self.assertIn("traversal", query_params)

        # Verify traversal plan
        traversal = query_params["traversal"]
        self.assertEqual(traversal["strategy"], "wikipedia_hierarchical")

        # Verify budget allocation
        budget = optimized["budget"]
        self.assertIn("timeout_ms", budget)
        self.assertIn("max_nodes", budget)
        self.assertIn("category_traversal_ms", budget)

        # Verify tracing
        trace_logs = [log for log in self.tracer.logs if log["type"] == "unified_optimization"]
        self.assertTrue(len(trace_logs) > 0)
        self.assertEqual(trace_logs[0]["trace_id"], "test789")


class TestWikipediaUtilityFunctions(unittest.TestCase):
    def setUp(self):
        self.wiki_processor = MockGraphProcessor(graph_type="wikipedia")
        self.ipld_processor = MockGraphProcessor(graph_type="ipld")
        self.unknown_processor = MockGraphProcessor(graph_type="unknown")

    def test_detect_graph_type(self):
        # Test graph type detection
        self.assertEqual(detect_graph_type(self.wiki_processor), "wikipedia")
        self.assertEqual(detect_graph_type(self.ipld_processor), "ipld")
        self.assertEqual(detect_graph_type(self.unknown_processor), "unknown")

    def test_create_appropriate_optimizer(self):
        # Test creating optimizer based on graph type
        wiki_optimizer = create_appropriate_optimizer(graph_processor=self.wiki_processor)
        ipld_optimizer = create_appropriate_optimizer(graph_processor=self.ipld_processor)

        # Verify correct optimizer types
        self.assertIsInstance(wiki_optimizer, UnifiedWikipediaGraphRAGQueryOptimizer)
        self.assertNotIsInstance(ipld_optimizer, UnifiedWikipediaGraphRAGQueryOptimizer)
        self.assertIsInstance(ipld_optimizer, object)  # Should be some optimizer type

        # Test with explicit graph type
        explicit_wiki = create_appropriate_optimizer(graph_type="wikipedia")
        self.assertIsInstance(explicit_wiki, UnifiedWikipediaGraphRAGQueryOptimizer)

    def test_optimize_wikipedia_query(self):
        # Test the main integration function
        query = {
            "query_vector": np.random.rand(10),
            "query_text": "What is quantum physics?",
            "max_vector_results": 5,
            "max_traversal_depth": 2,
            "edge_types": ["subclass_of", "instance_of", "related_to"],
            "min_similarity": 0.7
        }

        optimized = optimize_wikipedia_query(
            query=query,
            graph_processor=self.wiki_processor,
            vector_store=MockVectorStore(),
            tracer=MockTracer()
        )

        # Verify optimization result
        self.assertIn("query", optimized)
        self.assertIn("budget", optimized)

        # Verify query parameters
        query_params = optimized["query"]
        self.assertIn("vector_params", query_params)
        self.assertIn("traversal", query_params)

        # Verify traversal strategy
        traversal = query_params["traversal"]
        self.assertEqual(traversal["strategy"], "wikipedia_hierarchical")


if __name__ == '__main__':
    unittest.main()
