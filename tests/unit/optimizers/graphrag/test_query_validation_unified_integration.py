"""Tests for QueryValidationMixin integration with UnifiedGraphRAGQueryOptimizer.

Tests that the validation mixin properly sanitizes query parameters and provides
safe defaults for the unified optimizer.
"""

import pytest
import numpy as np
from ipfs_datasets_py.optimizers.graphrag.query_unified_optimizer import UnifiedGraphRAGQueryOptimizer


class TestUnifiedOptimizerValidation:
    """Test QueryValidationMixin integration with UnifiedGraphRAGQueryOptimizer."""
    
    def test_validates_max_vector_results(self):
        """Optimizer validates max_vector_results parameter."""
        optimizer = UnifiedGraphRAGQueryOptimizer()
        
        query = {
            "query_vector": [0.1, 0.2, 0.3],
            "max_vector_results": 5000  # Exceeds max of 1000
        }
        
        result = optimizer._validate_query_parameters(query)
        
        # Should clamp to max allowed
        assert result["max_vector_results"] == 1000
    
    def test_validates_min_similarity(self):
        """Optimizer validates min_similarity parameter."""
        optimizer = UnifiedGraphRAGQueryOptimizer()
        
        query = {
            "query_vector": [0.1, 0.2, 0.3],
            "min_similarity": 1.5  # Exceeds max of 1.0
        }
        
        result = optimizer._validate_query_parameters(query)
        
        # Should clamp to max allowed
        assert result["min_similarity"] == 1.0
    
    def test_validates_traversal_max_depth(self):
        """Optimizer validates traversal.max_depth parameter."""
        optimizer = UnifiedGraphRAGQueryOptimizer()
        
        query = {
            "traversal": {
                "max_depth": 50  # Exceeds max of 10
            }
        }
        
        result = optimizer._validate_query_parameters(query)
        
        # Should clamp to max allowed
        assert result["traversal"]["max_depth"] == 10
    
    def test_ensures_traversal_dict_exists(self):
        """Optimizer ensures traversal dict exists with defaults."""
        optimizer = UnifiedGraphRAGQueryOptimizer()
        
        query = {
            "query_vector": [0.1, 0.2, 0.3]
            # No traversal section
        }
        
        result = optimizer._validate_query_parameters(query)
        
        # Should create traversal section
        assert "traversal" in result
        assert isinstance(result["traversal"], dict)
        assert result["traversal"]["max_depth"] == 2  # Default
    
    def test_validates_priority_enum(self):
        """Optimizer validates priority parameter against allowed values."""
        optimizer = UnifiedGraphRAGQueryOptimizer()
        
        query = {
            "priority": "invalid_priority"
        }
        
        result = optimizer._validate_query_parameters(query)
        
        # Should default to "normal"
        assert result["priority"] == "normal"
    
    def test_allows_valid_priority_values(self):
        """Optimizer allows valid priority values."""
        optimizer = UnifiedGraphRAGQueryOptimizer()
        
        for priority in ["low", "normal", "high", "critical"]:
            query = {"priority": priority}
            result = optimizer._validate_query_parameters(query)
            assert result["priority"] == priority
    
    def test_validation_in_optimize_query(self):
        """optimize_query integrates validation."""
        optimizer = UnifiedGraphRAGQueryOptimizer()
        
        query = {
            "query_vector": np.array([0.1, 0.2, 0.3]),
            "max_vector_results": 2000,  # Exceeds max
            "min_similarity": -0.5,  # Below min
            "traversal": {
                "max_depth": 20  # Exceeds max
            }
        }
        
        result = optimizer.optimize_query(query)
        
        # Check validated query within result
        planned = result.get("query", query)
        assert planned["max_vector_results"] <= 1000
        assert planned["min_similarity"] >= 0.0
        assert planned["traversal"]["max_depth"] <= 10
    
    def test_validation_in_optimize_wikipedia_traversal(self):
        """optimize_wikipedia_traversal integrates validation."""
        optimizer = UnifiedGraphRAGQueryOptimizer()
        
        query = {
            "query_text": "test query",
            "min_similarity": 5.0,  # Invalid
            "traversal": {
                "max_depth": 100  # Exceeds max
            }
        }
        
        entity_scores = {"entity1": 0.9, "entity2": 0.7}
        result = optimizer.optimize_wikipedia_traversal(query, entity_scores)
        
        # Should validate parameters
        assert result["min_similarity"] == 1.0  # Clamped to max
        assert result["traversal"]["max_depth"] == 10  # Clamped to max
    
    def test_validation_in_optimize_ipld_traversal(self):
        """optimize_ipld_traversal integrates validation."""
        optimizer = UnifiedGraphRAGQueryOptimizer()
        
        query = {
            "max_vector_results": -10,  # Invalid
            "traversal": {
                "max_depth": 0  # Below min
            }
        }
        
        entity_scores = {}
        result = optimizer.optimize_ipld_traversal(query, entity_scores)
        
        # Should validate parameters
        assert result["max_vector_results"] == 1  # Clamped to min
        assert result["traversal"]["max_depth"] == 1  # Clamped to min


class TestValidationEdgeCases:
    """Test edge cases in validation integration."""
    
    def test_handles_none_values_gracefully(self):
        """Validation handles None values gracefully."""
        optimizer = UnifiedGraphRAGQueryOptimizer()
        
        query = {
            "max_vector_results": None,
            "min_similarity": None
        }
        
        result = optimizer._validate_query_parameters(query)
        
        # Should use defaults
        assert result["max_vector_results"] == 5
        assert result["min_similarity"] == 0.5
    
    def test_handles_missing_keys(self):
        """Validation handles missing keys gracefully."""
        optimizer = UnifiedGraphRAGQueryOptimizer()
        
        query = {}  # Empty query
        
        result = optimizer._validate_query_parameters(query)
        
        # Should have defaults
        assert result["max_vector_results"] == 5
        assert result["min_similarity"] == 0.5
        assert "traversal" in result
        assert result["traversal"]["max_depth"] == 2
    
    def test_handles_string_numbers(self):
        """Validation converts string numbers to proper types."""
        optimizer = UnifiedGraphRAGQueryOptimizer()
        
        query = {
            "max_vector_results": "100",
            "min_similarity": "0.8",
            "traversal": {
                "max_depth": "3"
            }
        }
        
        result = optimizer._validate_query_parameters(query)
        
        # Should convert to proper types
        assert result["max_vector_results"] == 100
        assert isinstance(result["max_vector_results"], (int, float))
        assert result["min_similarity"] == 0.8
        assert isinstance(result["min_similarity"], float)
        assert result["traversal"]["max_depth"] == 3
        assert isinstance(result["traversal"]["max_depth"], (int, float))
    
    def test_handles_edge_types_none(self):
        """Validation handles edge_types=None correctly."""
        optimizer = UnifiedGraphRAGQueryOptimizer()
        
        query = {
            "traversal": {
                "edge_types": None
            }
        }
        
        result = optimizer._validate_query_parameters(query)
        
        # Should preserve None (means no filtering)
        assert result["traversal"]["edge_types"] is None
    
    def test_handles_edge_types_list(self):
        """Validation handles edge_types as list."""
        optimizer = UnifiedGraphRAGQueryOptimizer()
        
        query = {
            "traversal": {
                "edge_types": ["type_a", "type_b", "type_c"]
            }
        }
        
        result = optimizer._validate_query_parameters(query)
        
        # Should preserve list
        assert result["traversal"]["edge_types"] == ["type_a", "type_b", "type_c"]


class TestValidationDoesNotMutateInput:
    """Test that validation doesn't mutate original input."""
    
    def test_validation_creates_copy(self):
        """Validation creates copy of input query."""
        optimizer = UnifiedGraphRAGQueryOptimizer()
        
        original_query = {
            "max_vector_results": 2000,
            "traversal": {
                "max_depth": 50
            }
        }
        
        original_max = original_query["max_vector_results"]
        original_depth = original_query["traversal"]["max_depth"]
        
        result = optimizer._validate_query_parameters(original_query)
        
        # Original should be unchanged
        assert original_query["max_vector_results"] == original_max
        assert original_query["traversal"]["max_depth"] == original_depth
        
        # Result should have validated values
        assert result["max_vector_results"] != original_max
        assert result["traversal"]["max_depth"] != original_depth
    
    def test_optimize_query_does_not_mutate_input(self):
        """optimize_query does not mutate original input."""
        optimizer = UnifiedGraphRAGQueryOptimizer()
        
        original_query = {
            "query_vector": np.array([0.1, 0.2, 0.3]),
            "max_vector_results": 3000
        }
        
        original_max = original_query["max_vector_results"]
        
        result = optimizer.optimize_query(original_query)
        
        # Original should be unchanged
        assert original_query["max_vector_results"] == original_max


class TestValidationWithRealWorkflow:
    """Test validation in realistic query workflows."""
    
    def test_validates_complex_wikipedia_query(self):
        """Validation works with complex Wikipedia query."""
        optimizer = UnifiedGraphRAGQueryOptimizer()
        
        query = {
            "query_text": "What are the main causes of climate change?",
            "query_vector": np.random.rand(384),
            "max_vector_results": 50,
            "min_similarity": 0.7,
            "traversal": {
                "max_depth": 3,
                "edge_types": ["cause", "effect", "related_to"],
                "strategy": "entity_importance"
            },
            "priority": "high"
        }
        
        result = optimizer.optimize_query(query)
        
        # Should successfully optimize without errors
        assert result is not None
        assert isinstance(result, dict)
    
    def test_validates_malformed_ipld_query(self):
        """Validation recovers from malformed IPLD query."""
        optimizer = UnifiedGraphRAGQueryOptimizer()
        
        query = {
            "max_vector_results": "not a number",
            "min_similarity": "invalid",
            "traversal": "not a dict"  # Wrong type
        }
        
        result = optimizer._validate_query_parameters(query)
        
        # Should recover with defaults
        assert isinstance(result["max_vector_results"], (int, float))
        assert isinstance(result["min_similarity"], float)
        assert isinstance(result["traversal"], dict)
        assert result["traversal"]["max_depth"] == 2
    
    def test_validation_with_empty_entity_scores(self):
        """Validation works with empty entity scores."""
        optimizer = UnifiedGraphRAGQueryOptimizer()
        
        query = {
            "query_text": "test",
            "max_vector_results": 10
        }
        
        # Should handle empty entity scores
        result_wiki = optimizer.optimize_wikipedia_traversal(query, {})
        result_ipld = optimizer.optimize_ipld_traversal(query, {})
        
        assert result_wiki is not None
        assert result_ipld is not None


class TestInheritanceStructure:
    """Test that QueryValidationMixin methods are available."""
    
    def test_has_validation_mixin_methods(self):
        """UnifiedGraphRAGQueryOptimizer has QueryValidationMixin methods."""
        optimizer = UnifiedGraphRAGQueryOptimizer()
        
        # Check mixin methods exist
        assert hasattr(optimizer, "validate_numeric_param")
        assert hasattr(optimizer, "validate_list_param")
        assert hasattr(optimizer, "validate_string_param")
        assert callable(optimizer.validate_numeric_param)
        assert callable(optimizer.validate_list_param)
        assert callable(optimizer.validate_string_param)
    
    def test_can_call_mixin_methods_directly(self):
        """Can call mixin methods directly on optimizer."""
        optimizer = UnifiedGraphRAGQueryOptimizer()
        
        result = optimizer.validate_numeric_param(
            value=150,
            param_name="test_value",
            min_value=0,
            max_value=100,
            default=50
        )
        
        # Should clamp to max
        assert result == 100
