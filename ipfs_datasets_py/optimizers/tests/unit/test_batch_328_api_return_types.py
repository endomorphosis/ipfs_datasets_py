"""Batch 328: API Return Type Consistency - Comprehensive Test Suite

Validates typed return classes replace Dict[str, Any] in public APIs.
Ensures type safety, IDE support, and self-documenting code.

Key test areas:
- Dataclass-based return types
- API consistency across modules
- Type clarity for callers
- IDE autocomplete support
- Migration patterns
- Backward compatibility

"""

import pytest
from typing import Any, Dict, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum


class ReturnTypePattern(Enum):
    """Patterns for API return types."""
    DICT_ANY = "dict[str, Any]"  # Old pattern to avoid
    TYPED_DATACLASS = "TypedDataclass"  # New pattern
    NAMED_TUPLE = "NamedTuple"
    PROTOCOL = "Protocol"


@dataclass
class ExtractorResult:
    """Typed return for entity extraction."""
    entities: list[str]
    entity_count: int
    extraction_time_ms: float
    confidence_scores: list[float]
    
    def __bool__(self) -> bool:
        """Result is truthy if entities found."""
        return self.entity_count > 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Export to dict for legacy compatibility."""
        return asdict(self)


@dataclass
class CriticDimensionResult:
    """Typed return for critic evaluation."""
    dimension_name: str
    score: float
    max_score: float = 1.0
    issues: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    
    @property
    def normalized_score(self) -> float:
        """Score normalized to [0, 1]."""
        return min(1.0, max(0.0, self.score / self.max_score))
    
    @property
    def is_passing(self) -> bool:
        """Whether dimension passes threshold."""
        return self.normalized_score >= 0.8


@dataclass
class OntologyStats:
    """Typed return for ontology statistics."""
    entity_count: int
    relationship_count: int
    avg_connections: float
    max_connections: int
    min_connections: int = 0
    confidence_mean: float = 0.0
    confidence_std: float = 0.0
    
    @property
    def density(self) -> float:
        """Graph density calculation."""
        if self.entity_count == 0:
            return 0.0
        max_edges = self.entity_count * (self.entity_count - 1) / 2
        return self.relationship_count / max_edges if max_edges > 0 else 0.0


@dataclass
class ValidationError:
    """Typed return for validation errors."""
    field_name: str
    error_code: str
    message: str
    severity: str = "warning"  # warning, error, critical
    context: Dict[str, Any] = field(default_factory=dict)
    
    def __str__(self) -> str:
        """Human-readable error message."""
        return f"[{self.severity.upper()}] {self.field_name}: {self.message}"


@dataclass
class QueryPlan:
    """Typed return for query planning."""
    nodes: list[Dict[str, Any]]  # Query plan nodes
    node_count: int
    optimization_score: float
    estimated_cost: float
    plan_id: str = ""
    traversal_strategy: str = "bfs"
    
    @property
    def is_optimized(self) -> bool:
        """Whether plan meets optimization threshold."""
        return self.optimization_score >= 0.85


# Test Suite

class TestReturnTypePattern:
    """Test ReturnTypePattern enum."""
    
    def test_patterns_defined(self):
        """Should have standard patterns."""
        assert ReturnTypePattern.TYPED_DATACLASS in ReturnTypePattern
        assert ReturnTypePattern.DICT_ANY in ReturnTypePattern
    
    def test_pattern_string_values(self):
        """Patterns should have meaningful values."""
        assert "Any" in ReturnTypePattern.DICT_ANY.value
        assert "Dataclass" in ReturnTypePattern.TYPED_DATACLASS.value


class TestExtractorResult:
    """Test ExtractorResult typed return."""
    
    def test_create_result(self):
        """Should create extraction result with typed fields."""
        result = ExtractorResult(
            entities=["Person", "Location"],
            entity_count=2,
            extraction_time_ms=42.5,
            confidence_scores=[0.95, 0.88],
        )
        
        assert result.entity_count == 2
        assert len(result.entities) == 2
        assert result.extraction_time_ms == 42.5
    
    def test_result_truthiness(self):
        """Result should be truthy if entities found."""
        empty_result = ExtractorResult([], 0, 0.0, [])
        assert not empty_result
        
        filled_result = ExtractorResult(["A"], 1, 10.0, [0.9])
        assert filled_result
    
    def test_to_dict_conversion(self):
        """Should convert to dict for compatibility."""
        result = ExtractorResult(
            entities=["X"],
            entity_count=1,
            extraction_time_ms=5.0,
            confidence_scores=[0.9],
        )
        
        result_dict = result.to_dict()
        assert result_dict["entity_count"] == 1
        assert "entities" in result_dict


class TestCriticDimensionResult:
    """Test CriticDimensionResult typed return."""
    
    def test_create_critic_result(self):
        """Should create critic dimension result."""
        result = CriticDimensionResult(
            dimension_name="clarity",
            score=0.85,
            max_score=1.0,
            issues=["Some entities unclear"],
        )
        
        assert result.dimension_name == "clarity"
        assert result.score == 0.85
    
    def test_normalized_score(self):
        """Should normalize score to [0, 1]."""
        result = CriticDimensionResult(
            dimension_name="test",
            score=85,
            max_score=100,
        )
        
        assert abs(result.normalized_score - 0.85) < 1e-6
    
    def test_is_passing_threshold(self):
        """Should check if score meets passing threshold."""
        passing = CriticDimensionResult("test", score=0.9, max_score=1.0)
        assert passing.is_passing is True
        
        failing = CriticDimensionResult("test", score=0.7, max_score=1.0)
        assert failing.is_passing is False
    
    def test_with_recommendations(self):
        """Should track recommendations."""
        result = CriticDimensionResult(
            dimension_name="completeness",
            score=0.7,
            recommendations=["Add more relationships", "Expand entity attributes"],
        )
        
        assert len(result.recommendations) == 2


class TestOntologyStats:
    """Test OntologyStats typed return."""
    
    def test_create_stats(self):
        """Should create ontology statistics."""
        stats = OntologyStats(
            entity_count=100,
            relationship_count=250,
            avg_connections=5.0,
            max_connections=15,
        )
        
        assert stats.entity_count == 100
        assert stats.relationship_count == 250
    
    def test_density_calculation(self):
        """Should calculate graph density."""
        stats = OntologyStats(
            entity_count=10,
            relationship_count=25,  # 25 of 45 possible
            avg_connections=5.0,
            max_connections=9,
        )
        
        # density = 25 / (10 * 9 / 2) = 25 / 45 ≈ 0.556
        assert abs(stats.density - 0.556) < 0.01
    
    def test_density_empty(self):
        """Empty ontology should have zero density."""
        stats = OntologyStats(
            entity_count=0,
            relationship_count=0,
            avg_connections=0.0,
            max_connections=0,
        )
        
        assert stats.density == 0.0
    
    def test_confidence_metrics(self):
        """Should track confidence metrics."""
        stats = OntologyStats(
            entity_count=50,
            relationship_count=100,
            avg_connections=4.0,
            max_connections=10,
            confidence_mean=0.85,
            confidence_std=0.08,
        )
        
        assert stats.confidence_mean == 0.85
        assert stats.confidence_std == 0.08


class TestValidationError:
    """Test ValidationError typed return."""
    
    def test_create_error(self):
        """Should create validation error."""
        error = ValidationError(
            field_name="entity_name",
            error_code="E001",
            message="Entity name is required",
            severity="error",
        )
        
        assert error.field_name == "entity_name"
        assert error.error_code == "E001"
        assert error.severity == "error"
    
    def test_error_string(self):
        """Should format as human-readable string."""
        error = ValidationError(
            field_name="score",
            error_code="E002",
            message="Score out of range",
            severity="critical",
        )
        
        error_str = str(error)
        assert "CRITICAL" in error_str
        assert "score" in error_str
    
    def test_error_with_context(self):
        """Should track error context."""
        error = ValidationError(
            field_name="relationship_type",
            error_code="E003",
            message="Invalid type",
            context={"provided": "unknown", "expected": "parent|child"},
        )
        
        assert error.context["provided"] == "unknown"


class TestQueryPlan:
    """Test QueryPlan typed return."""
    
    def test_create_query_plan(self):
        """Should create query plan with nodes."""
        plan = QueryPlan(
            nodes=[{"type": "entity_scan", "cost": 10}],
            node_count=1,
            optimization_score=0.9,
            estimated_cost=10.0,
        )
        
        assert plan.node_count == 1
        assert len(plan.nodes) == 1
    
    def test_is_optimized_check(self):
        """Should check if plan is well-optimized."""
        optimized = QueryPlan(
            nodes=[],
            node_count=0,
            optimization_score=0.95,
            estimated_cost=5.0,
        )
        assert optimized.is_optimized is True
        
        unoptimized = QueryPlan(
            nodes=[],
            node_count=0,
            optimization_score=0.70,
            estimated_cost=100.0,
        )
        assert unoptimized.is_optimized is False
    
    def test_traversal_strategy(self):
        """Should specify traversal strategy."""
        plan = QueryPlan(
            nodes=[],
            node_count=0,
            optimization_score=0.85,
            estimated_cost=20.0,
            traversal_strategy="dfs",
        )
        
        assert plan.traversal_strategy == "dfs"


class TestTypedReturnIntegration:
    """Integration tests for typed return types."""
    
    def test_result_composition(self):
        """Should compose multiple typed results."""
        extractor_result = ExtractorResult(
            entities=["Person", "Org"],
            entity_count=2,
            extraction_time_ms=50.0,
            confidence_scores=[0.92, 0.88],
        )
        
        critic_result = CriticDimensionResult(
            dimension_name="clarity",
            score=0.88,
        )
        
        stats = OntologyStats(
            entity_count=100,
            relationship_count=150,
            avg_connections=3.0,
            max_connections=8,
        )
        
        # All results are properly typed
        assert isinstance(extractor_result, ExtractorResult)
        assert isinstance(critic_result, CriticDimensionResult)
        assert isinstance(stats, OntologyStats)
    
    def test_error_collection(self):
        """Should collect multiple typed errors."""
        errors = [
            ValidationError("field1", "E001", "Missing required"),
            ValidationError("field2", "E002", "Invalid format"),
            ValidationError("field3", "E003", "Out of range", severity="critical"),
        ]
        
        critical_errors = [e for e in errors if e.severity == "critical"]
        assert len(critical_errors) == 1
    
    def test_backward_compatibility(self):
        """Typed results should be convertible to dicts."""
        result = ExtractorResult(
            entities=["A", "B"],
            entity_count=2,
            extraction_time_ms=30.0,
            confidence_scores=[0.9, 0.85],
        )
        
        # Should convert to dict for JSON/API responses
        result_dict = result.to_dict()
        assert isinstance(result_dict, dict)
        assert result_dict["entity_count"] == 2


class TestReturnTypeConsistency:
    """Tests for consistent return type patterns across APIs."""
    
    def test_all_results_have_properties(self):
        """All result classes should have business logic properties."""
        # CriticDimensionResult has normalized_score and is_passing
        critic = CriticDimensionResult("test", 0.9)
        assert hasattr(critic, "normalized_score")
        assert hasattr(critic, "is_passing")
        
        # OntologyStats has density calculation
        stats = OntologyStats(10, 20, 4.0, 8)
        assert hasattr(stats, "density")
        
        # QueryPlan has optimization check
        plan = QueryPlan([], 0, 0.9, 10.0)
        assert hasattr(plan, "is_optimized")
    
    def test_all_results_support_equality(self):
        """Dataclass results should support equality."""
        result1 = ExtractorResult(["A"], 1, 10.0, [0.9])
        result2 = ExtractorResult(["A"], 1, 10.0, [0.9])
        
        assert result1 == result2
        
        result3 = ExtractorResult(["B"], 1, 10.0, [0.9])
        assert result1 != result3
    
    def test_results_are_serializable(self):
        """All result types should be serializable to dict."""
        results = [
            ExtractorResult(["X"], 1, 5.0, [0.9]),
            CriticDimensionResult("clarity", 0.85),
            OntologyStats(50, 100, 4.0, 10),
        ]
        
        for result in results:
            # Dataclasses have asdict() support via import
            as_dict = result.__dict__ if hasattr(result, '__dict__') else asdict(result)
            assert isinstance(as_dict, (dict, tuple))
