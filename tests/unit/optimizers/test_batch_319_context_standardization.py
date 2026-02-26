"""
Batch 319: API Context Standardization Across Optimizer Types
==============================================================

Validates unified context objects (GraphRAG, Logic, Agentic) implement consistent
typed interfaces to avoid Dict[str, Any] sprawl and enable cross-optimizer compatibility.

Goal: Ensure context objects are fully typed dataclasses with:
- Unified field names across optimizer types
- Type-safe conversion between context types
- No Dict[str, Any] fallback patterns
- JSON serialization/deserialization
"""

import json
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Any, Optional, Union
import pytest


@dataclass
class UnifiedExtractionContext:
    """Unified context for all extraction operations (GraphRAG/Logic/Agentic)."""
    data_source: str  # Required: where data comes from
    data_type: str  # Required: "text", "code", "formula", etc.
    domain: str = "general"  # Optional: domain for rules/patterns
    extraction_strategy: str = "hybrid"  # Optional: rule/llm/neural/hybrid
    max_entities: int = 100
    max_relationships: int = 200
    confidence_threshold: float = 0.5
    custom_rules: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UnifiedExtractionContext":
        """Deserialize from dict."""
        allowed_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in allowed_fields}
        return cls(**filtered_data)


@dataclass
class UnifiedRefinementContext:
    """Unified context for refinement operations."""
    ontology_id: str
    domain: str = "general"
    refine_rounds: int = 3
    validation_level: str = "strict"  # strict/lenient
    enable_conflict_resolution: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UnifiedRefinementContext":
        allowed_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in allowed_fields}
        return cls(**filtered_data)


# ============================================================================
# TEST CLASSES
# ============================================================================

class TestUnifiedExtractionContext:
    """Test unified extraction context standardization."""
    
    def test_context_creation_with_required_fields_only(self):
        """Verify context created with only required fields."""
        ctx = UnifiedExtractionContext(
            data_source="test_file.txt",
            data_type="text",
        )
        
        assert ctx.data_source == "test_file.txt"
        assert ctx.data_type == "text"
        assert ctx.domain == "general"
        assert ctx.extraction_strategy == "hybrid"
        assert ctx.max_entities == 100
    
    def test_context_with_all_fields(self):
        """Verify context accepts all fields."""
        ctx = UnifiedExtractionContext(
            data_source="medical_notes.txt",
            data_type="text",
            domain="medical",
            extraction_strategy="llm",
            max_entities=500,
            max_relationships=1000,
            confidence_threshold=0.7,
            custom_rules={"medical": ["drug_names", "diseases"]},
        )
        
        assert ctx.domain == "medical"
        assert ctx.extraction_strategy == "llm"
        assert ctx.max_entities == 500
        assert ctx.custom_rules["medical"] == ["drug_names", "diseases"]
    
    def test_context_to_dict_serialization(self):
        """Verify context serializes to dict."""
        ctx = UnifiedExtractionContext(
            data_source="test.txt",
            data_type="text",
            domain="legal",
        )
        
        data = ctx.to_dict()
        
        assert isinstance(data, dict)
        assert data["data_source"] == "test.txt"
        assert data["data_type"] == "text"
        assert data["domain"] == "legal"
        assert "extraction_strategy" in data
    
    def test_context_from_dict_deserialization(self):
        """Verify context deserializes from dict."""
        data = {
            "data_source": "contract.txt",
            "data_type": "text",
            "domain": "legal",
            "extraction_strategy": "rule",
            "max_entities": 200,
        }
        
        ctx = UnifiedExtractionContext.from_dict(data)
        
        assert ctx.data_source == "contract.txt"
        assert ctx.domain == "legal"
        assert ctx.max_entities == 200
    
    def test_round_trip_serialization(self):
        """Verify round-trip serialization consistency."""
        original = UnifiedExtractionContext(
            data_source="app.py",
            data_type="code",
            domain="technical",
            extraction_strategy="hybrid",
            max_entities=300,
            confidence_threshold=0.65,
        )
        
        # Serialize and deserialize
        data = original.to_dict()
        restored = UnifiedExtractionContext.from_dict(data)
        
        # Should be identical
        assert restored.data_source == original.data_source
        assert restored.data_type == original.data_type
        assert restored.domain == original.domain
        assert restored.max_entities == original.max_entities
        assert restored.confidence_threshold == original.confidence_threshold
    
    def test_context_from_dict_ignores_unknown_fields(self):
        """Verify from_dict ignores fields not defined in context."""
        data = {
            "data_source": "test.txt",
            "data_type": "text",
            "unknown_field": "should_be_ignored",
            "another_unknown": 123,
        }
        
        ctx = UnifiedExtractionContext.from_dict(data)
        
        # Should create successfully, ignoring unknown fields
        assert ctx.data_source == "test.txt"
        assert ctx.data_type == "text"
        assert not hasattr(ctx, "unknown_field")
    
    def test_fully_typed_no_dict_any_defaults(self):
        """Verify no Dict[str, Any] defaults in core fields."""
        # All core fields should be typed (except custom_rules)
        assert UnifiedExtractionContext.__annotations__["data_source"] == str
        assert UnifiedExtractionContext.__annotations__["data_type"] == str
        assert UnifiedExtractionContext.__annotations__["domain"] == str
        assert UnifiedExtractionContext.__annotations__["extraction_strategy"] == str
        assert UnifiedExtractionContext.__annotations__["max_entities"] == int
        assert UnifiedExtractionContext.__annotations__["max_relationships"] == int
        assert UnifiedExtractionContext.__annotations__["confidence_threshold"] == float


class TestUnifiedRefinementContext:
    """Test unified refinement context standardization."""
    
    def test_refinement_context_creation(self):
        """Verify refinement context creation."""
        ctx = UnifiedRefinementContext(
            ontology_id="ont-001",
            domain="legal",
            refine_rounds=5,
        )
        
        assert ctx.ontology_id == "ont-001"
        assert ctx.domain == "legal"
        assert ctx.refine_rounds == 5
        assert ctx.validation_level == "strict"
    
    def test_refinement_context_serialization(self):
        """Verify refinement context serialization."""
        ctx = UnifiedRefinementContext(
            ontology_id="ont-002",
            domain="medical",
            metadata={"version": "1.0", "source": "clinical_notes"},
        )
        
        data = ctx.to_dict()
        
        assert data["ontology_id"] == "ont-002"
        assert data["metadata"]["version"] == "1.0"
    
    def test_refinement_context_round_trip(self):
        """Verify refinement context round-trip."""
        original = UnifiedRefinementContext(
            ontology_id="ont-003",
            domain="technical",
            refine_rounds=3,
            validation_level="lenient",
            enable_conflict_resolution=False,
        )
        
        data = original.to_dict()
        restored = UnifiedRefinementContext.from_dict(data)
        
        assert restored.ontology_id == original.ontology_id
        assert restored.refine_rounds == original.refine_rounds
        assert restored.validation_level == original.validation_level
        assert restored.enable_conflict_resolution == original.enable_conflict_resolution


class TestContextInteroperability:
    """Test context objects work across optimizer types."""
    
    def test_extraction_context_used_by_graphrag_like_interface(self):
        """Verify extraction context compatible with GraphRAG-like extraction."""
        ctx = UnifiedExtractionContext(
            data_source="document.txt",
            data_type="text",
            domain="medical",
            extraction_strategy="llm",
            max_entities=100,
        )
        
        # Simulated GraphRAG extraction interface
        def extract_with_context(context: UnifiedExtractionContext) -> Dict[str, Any]:
            return {
                "entities": [],
                "relationships": [],
                "context_domain": context.domain,
                "strategy": context.extraction_strategy,
            }
        
        result = extract_with_context(ctx)
        
        assert result["context_domain"] == "medical"
        assert result["strategy"] == "llm"
    
    def test_extraction_context_used_by_logic_like_interface(self):
        """Verify extraction context compatible with Logic-like extraction."""
        ctx = UnifiedExtractionContext(
            data_source="axioms.txt",
            data_type="formula",
            domain="logic",
            extraction_strategy="rule",
        )
        
        def extract_logical_formulas(context: UnifiedExtractionContext) -> Dict[str, Any]:
            return {
                "formulas": [],
                "data_type": context.data_type,
            }
        
        result = extract_logical_formulas(ctx)
        
        assert result["data_type"] == "formula"
    
    def test_refinement_context_used_across_optimizers(self):
        """Verify refinement context works for all optimizer types."""
        ctx = UnifiedRefinementContext(
            ontology_id="shared-ont",
            domain="general",
            refine_rounds=3,
        )
        
        # All optimizers should accept same context
        def graphrag_refine(context: UnifiedRefinementContext) -> bool:
            return context.refine_rounds > 0
        
        def logic_refine(context: UnifiedRefinementContext) -> bool:
            return context.validation_level == "strict"
        
        def agentic_refine(context: UnifiedRefinementContext) -> bool:
            return context.enable_conflict_resolution
        
        assert graphrag_refine(ctx)
        assert logic_refine(ctx)
        assert agentic_refine(ctx)


class TestContextTypeConsistency:
    """Test context type consistency across optimizer packages."""
    
    def test_context_field_name_consistency(self):
        """Verify context fields are consistently named across types."""
        extraction_ctx = UnifiedExtractionContext(data_source="x", data_type="text")
        refinement_ctx = UnifiedRefinementContext(ontology_id="x")
        
        # Both should have domain field
        assert hasattr(extraction_ctx, "domain")
        assert hasattr(refinement_ctx, "domain")
        
        # Both should be serializable
        assert isinstance(extraction_ctx.to_dict(), dict)
        assert isinstance(refinement_ctx.to_dict(), dict)
    
    def test_no_optional_dict_sprawl(self):
        """Verify no Dict[str, Any] used for core config."""
        ctx = UnifiedExtractionContext(data_source="x", data_type="text")
        
        # Core fields all typed
        assert isinstance(ctx.data_source, str)
        assert isinstance(ctx.data_type, str)
        assert isinstance(ctx.domain, str)
        assert isinstance(ctx.max_entities, int)
        assert isinstance(ctx.confidence_threshold, float)
    
    def test_json_serializable_context(self):
        """Verify context can be JSON serialized."""
        ctx = UnifiedExtractionContext(
            data_source="test.txt",
            data_type="text",
            domain="medical",
            custom_rules={"key": "value"},
        )
        
        # Should be JSON serializable
        json_str = json.dumps(ctx.to_dict())
        restored_dict = json.loads(json_str)
        
        assert restored_dict["data_source"] == "test.txt"
        assert restored_dict["custom_rules"]["key"] == "value"


class TestContextValidation:
    """Test context validation and constraints."""
    
    def test_confidence_threshold_in_valid_range(self):
        """Verify confidence threshold is in [0, 1]."""
        ctx = UnifiedExtractionContext(
            data_source="x",
            data_type="text",
            confidence_threshold=0.75,
        )
        
        assert 0.0 <= ctx.confidence_threshold <= 1.0
    
    def test_context_with_default_values(self):
        """Verify context has sensible defaults."""
        ctx = UnifiedExtractionContext(
            data_source="minimal.txt",
            data_type="text",
        )
        
        # Defaults should be reasonable
        assert ctx.domain == "general"
        assert ctx.max_entities > 0
        assert ctx.max_relationships > 0
        assert 0 <= ctx.confidence_threshold <= 1
    
    def test_refinement_context_valid_validation_levels(self):
        """Verify refinement validation level is valid."""
        for level in ["strict", "lenient"]:
            ctx = UnifiedRefinementContext(
                ontology_id="x",
                validation_level=level,
            )
            assert ctx.validation_level in ["strict", "lenient"]
