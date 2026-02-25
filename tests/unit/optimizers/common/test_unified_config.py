"""Tests for unified configuration and context dataclasses."""

import pytest
from types import SimpleNamespace
from ipfs_datasets_py.optimizers.agentic.llm_integration import LLMProvider
from ipfs_datasets_py.optimizers.common.unified_config import (
    DomainType,
    GraphRAGConfig,
    LogicConfig,
    AgenticConfig,
    UnifiedOptimizerConfig,
    GraphRAGContext,
    LogicContext,
    AgenticContext,
    create_context,
    context_from_optimization_context,
    context_from_ontology_generation_context,
    backend_config_from_constructor_kwargs,
    domain_type_from_value,
    ensure_shared_backend_config,
    ensure_shared_context_metadata,
    supported_backend_config_source_aliases,
)
from ipfs_datasets_py.optimizers.common.base_optimizer import OptimizationContext


class TestDomainType:
    """Test DomainType enum."""
    
    def test_domain_type_values(self):
        """Verify all domain types are defined."""
        assert DomainType.GRAPHRAG.value == "graphrag"
        assert DomainType.LOGIC.value == "logic"
        assert DomainType.AGENTIC.value == "agentic"
        assert DomainType.CODE.value == "code"
        assert DomainType.HYBRID.value == "hybrid"


class TestGraphRAGConfig:
    """Test GraphRAG configuration."""
    
    def test_default_values(self):
        """Verify default configuration values."""
        config = GraphRAGConfig()
        assert config.extraction_strategy == "heuristic"
        assert config.confidence_threshold == 0.5
        assert config.language == "en"
        assert config.domain_specific_rules == set()
    
    def test_custom_values(self):
        """Test setting custom configuration."""
        config = GraphRAGConfig(
            extraction_strategy="llm",
            confidence_threshold=0.75,
            language="fr",
        )
        assert config.extraction_strategy == "llm"
        assert config.confidence_threshold == 0.75
        assert config.language == "fr"
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        config = GraphRAGConfig(extraction_strategy="llm")
        config_dict = config.to_dict()
        assert isinstance(config_dict, dict)
        assert config_dict["extraction_strategy"] == "llm"
    
    def test_from_dict(self):
        """Test creation from dictionary."""
        data = {"extraction_strategy": "hybrid", "language": "de"}
        config = GraphRAGConfig.from_dict(data)
        assert config.extraction_strategy == "hybrid"
        assert config.language == "de"


class TestLogicConfig:
    """Test logic theorem optimizer configuration."""
    
    def test_default_values(self):
        """Verify default configuration values."""
        config = LogicConfig()
        assert config.formula_format == "tdfol"
        assert config.prover_backend == "z3"
        assert config.proof_timeout_ms == 5000
    
    def test_neural_symbolic_enabled(self):
        """Test neural-symbolic configuration."""
        config = LogicConfig(
            enable_neural_symbolic=True,
            neural_confidence_threshold=0.9,
        )
        assert config.enable_neural_symbolic is True
        assert config.neural_confidence_threshold == 0.9


class TestAgenticConfig:
    """Test agentic optimizer configuration."""
    
    def test_default_values(self):
        """Verify default configuration values."""
        config = AgenticConfig()
        assert config.mode == "autonomous"
        assert config.max_parallel_actions == 4
        assert config.enable_logging is True


class TestUnifiedOptimizerConfig:
    """Test unified optimizer configuration."""
    
    def test_initialization(self):
        """Test unified config initialization."""
        config = UnifiedOptimizerConfig()
        assert config.domain == DomainType.HYBRID
        assert config.max_iterations == 10
        assert config.target_score == 0.85
        assert isinstance(config.graphrag_config, GraphRAGConfig)
        assert isinstance(config.logic_config, LogicConfig)
        assert isinstance(config.agentic_config, AgenticConfig)
    
    def test_custom_domain_config(self):
        """Test with custom domain configuration."""
        graphrag = GraphRAGConfig(extraction_strategy="llm")
        config = UnifiedOptimizerConfig(
            domain=DomainType.GRAPHRAG,
            graphrag_config=graphrag,
        )
        assert config.domain == DomainType.GRAPHRAG
        assert config.graphrag_config.extraction_strategy == "llm"
    
    def test_get_domain_config(self):
        """Test retrieving domain-specific config."""
        config = UnifiedOptimizerConfig()
        
        graphrag_cfg = config.get_domain_config(DomainType.GRAPHRAG)
        assert isinstance(graphrag_cfg, GraphRAGConfig)
        
        logic_cfg = config.get_domain_config(DomainType.LOGIC)
        assert isinstance(logic_cfg, LogicConfig)
        
        agentic_cfg = config.get_domain_config(DomainType.AGENTIC)
        assert isinstance(agentic_cfg, AgenticConfig)
    
    def test_get_invalid_domain_config_raises_error(self):
        """Test error handling for invalid domain."""
        config = UnifiedOptimizerConfig()
        with pytest.raises(ValueError):
            config.get_domain_config("invalid")
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        config = UnifiedOptimizerConfig(max_iterations=20)
        config_dict = config.to_dict()
        assert config_dict["max_iterations"] == 20


class TestGraphRAGContext:
    """Test GraphRAG optimization context."""
    
    def test_initialization(self):
        """Test context initialization."""
        context = GraphRAGContext(
            session_id="test-session",
            domain=DomainType.GRAPHRAG,
        )
        assert context.session_id == "test-session"
        assert context.domain == DomainType.GRAPHRAG
    
    def test_metadata_operations(self):
        """Test metadata get/set operations."""
        context = GraphRAGContext(
            session_id="test",
            domain=DomainType.GRAPHRAG,
        )
        context.set_metadata("key1", "value1")
        assert context.get_metadata("key1") == "value1"
        assert context.get_metadata("nonexistent", "default") == "default"
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        context = GraphRAGContext(
            session_id="test",
            domain=DomainType.GRAPHRAG,
            input_text="Sample text",
        )
        context_dict = context.to_dict()
        assert context_dict["session_id"] == "test"
        assert context_dict["input_text"] == "Sample text"


class TestContextFactory:
    """Test context creation factory function."""
    
    def test_create_graphrag_context(self):
        """Test creating GraphRAG context."""
        context = create_context(
            session_id="test",
            domain=DomainType.GRAPHRAG,
            input_text="Test text",
        )
        assert isinstance(context, GraphRAGContext)
        assert context.input_text == "Test text"
    
    def test_create_logic_context(self):
        """Test creating logic context."""
        context = create_context(
            session_id="test",
            domain=DomainType.LOGIC,
        )
        assert isinstance(context, LogicContext)
    
    def test_create_agentic_context(self):
        """Test creating agentic context."""
        context = create_context(
            session_id="test",
            domain=DomainType.AGENTIC,
        )
        assert isinstance(context, AgenticContext)
    
    def test_create_default_context(self):
        """Test creating context for unrecognized domain."""
        context = create_context(
            session_id="test",
            domain=DomainType.CODE,
        )
        from ipfs_datasets_py.optimizers.common.unified_config import BaseContext
        assert type(context).__name__ == "BaseContext"


class TestContextAdapters:
    """Test legacy-to-unified context adapters."""

    def test_domain_type_from_value_normalizes_aliases(self):
        assert domain_type_from_value("graph") == DomainType.GRAPHRAG
        assert domain_type_from_value("logic") == DomainType.LOGIC
        assert domain_type_from_value("unknown") == DomainType.HYBRID

    def test_context_from_optimization_context_graphrag(self):
        legacy = OptimizationContext(
            session_id="s1",
            input_data="sample text",
            domain="graphrag",
            metadata={"source": "test"},
        )
        adapted = context_from_optimization_context(legacy)

        assert isinstance(adapted, GraphRAGContext)
        assert adapted.session_id == "s1"
        assert adapted.input_text == "sample text"
        assert adapted.metadata["source"] == "test"
        assert adapted.metadata["session_id"] == "s1"
        assert "data_source" in adapted.metadata
        assert "data_type" in adapted.metadata
        assert "trace_id" in adapted.metadata

    def test_context_from_ontology_generation_context(self):
        fake_context = SimpleNamespace(
            data_source="doc.txt",
            data_type="text",
            domain="legal",
            extraction_strategy="hybrid",
            base_ontology={"entities": [], "relationships": []},
            config={"confidence_threshold": 0.7},
            trace_id="trace-123",
        )
        adapted = context_from_ontology_generation_context(
            fake_context,
            session_id="g1",
        )

        assert isinstance(adapted, GraphRAGContext)
        assert adapted.session_id == "g1"
        assert adapted.ontology_domain == "legal"
        assert adapted.metadata["data_source"] == "doc.txt"
        assert adapted.metadata["data_type"] == "text"
        assert adapted.metadata["session_id"] == "g1"
        assert adapted.metadata["trace_id"] == "trace-123"
        assert adapted.extraction_context == {"confidence_threshold": 0.7}

    def test_context_adapters_exported_from_common_namespace(self):
        from ipfs_datasets_py.optimizers import common

        assert hasattr(common, "domain_type_from_value")
        assert hasattr(common, "ensure_shared_backend_config")
        assert hasattr(common, "supported_backend_config_source_aliases")
        assert hasattr(common, "ensure_shared_context_metadata")
        assert hasattr(common, "context_from_optimization_context")
        assert hasattr(common, "context_from_ontology_generation_context")

    def test_ensure_shared_context_metadata_preserves_existing_values(self):
        result = ensure_shared_context_metadata(
            {"data_source": "already-set", "custom": 1},
            session_id="s-1",
            data_source="new-source",
            data_type="text",
            trace_id="t-1",
        )
        assert result["data_source"] == "already-set"
        assert result["session_id"] == "s-1"
        assert result["data_type"] == "text"
        assert result["trace_id"] == "t-1"
        assert result["custom"] == 1

    def test_ensure_shared_backend_config_sets_default_shared_keys(self):
        result = ensure_shared_backend_config(
            {"provider": "existing-provider"},
            provider="new-provider",
            model="gpt-4",
            use_llm=True,
            timeout_seconds=30.0,
            max_retries=2,
            circuit_failure_threshold=5,
        )
        assert result["provider"] == "existing-provider"
        assert result["model"] == "gpt-4"
        assert result["use_llm"] is True
        assert result["timeout_seconds"] == 30.0
        assert result["max_retries"] == 2
        assert result["circuit_failure_threshold"] == 5

    def test_backend_config_from_constructor_kwargs_graphrag_generator(self):
        result = backend_config_from_constructor_kwargs(
            "graphrag.ontology_generator",
            ipfs_accelerate_config={
                "provider": "openai",
                "model": "gpt-4",
                "timeout_seconds": 18.0,
                "max_retries": 3,
                "circuit_failure_threshold": 6,
            },
            use_ipfs_accelerate=True,
        )
        assert result["provider"] == "openai"
        assert result["model"] == "gpt-4"
        assert result["use_llm"] is True
        assert result["timeout_seconds"] == 18.0
        assert result["max_retries"] == 3
        assert result["circuit_failure_threshold"] == 6

    def test_backend_config_from_constructor_kwargs_logic_unified_optimizer(self):
        result = backend_config_from_constructor_kwargs(
            "logic_theorem_optimizer.unified_optimizer",
            llm_backend=object(),
            llm_backend_config={"provider": "anthropic", "model": "claude-3"},
        )
        assert result["provider"] == "anthropic"
        assert result["model"] == "claude-3"
        assert result["use_llm"] is True
        assert result["timeout_seconds"] == 30.0
        assert result["max_retries"] == 2
        assert result["circuit_failure_threshold"] == 5

    def test_backend_config_from_constructor_kwargs_graphrag_pipeline(self):
        result = backend_config_from_constructor_kwargs(
            "graphrag.ontology_pipeline",
            use_llm=True,
        )
        assert result["use_llm"] is True
        assert result["timeout_seconds"] == 20.0
        assert result["max_retries"] == 2
        assert result["circuit_failure_threshold"] == 5

    def test_backend_config_from_constructor_kwargs_graphrag_critic(self):
        result = backend_config_from_constructor_kwargs(
            "graphrag.ontology_critic",
            use_llm=False,
            backend_config={"provider": "openai", "model": "gpt-4"},
        )
        assert result["provider"] == "openai"
        assert result["model"] == "gpt-4"
        assert result["use_llm"] is False
        assert result["timeout_seconds"] == 20.0
        assert result["max_retries"] == 2
        assert result["circuit_failure_threshold"] == 5

    def test_backend_config_from_constructor_kwargs_logic_extractor(self):
        backend_stub = SimpleNamespace(name="accelerate")
        result = backend_config_from_constructor_kwargs(
            "logic.logic_extractor",
            model="gpt-4",
            backend=backend_stub,
        )
        assert result["provider"] == "accelerate"
        assert result["model"] == "gpt-4"
        assert result["use_llm"] is True
        assert result["timeout_seconds"] == 20.0
        assert result["max_retries"] == 2
        assert result["circuit_failure_threshold"] == 5

    def test_backend_config_from_constructor_kwargs_agentic_router(self):
        result = backend_config_from_constructor_kwargs(
            "agentic.llm_router",
            preferred_provider=LLMProvider.CLAUDE,
        )
        assert result["provider"] == "claude"
        assert result["use_llm"] is True
        assert result["timeout_seconds"] == 30.0
        assert result["max_retries"] == 0
        assert result["circuit_failure_threshold"] == 3

    def test_supported_backend_config_source_aliases_contains_expected_aliases(self):
        aliases = supported_backend_config_source_aliases()
        assert "graphrag_generator" in aliases
        assert "graphrag_pipeline" in aliases
        assert "graphrag_critic" in aliases
        assert "logic_extractor" in aliases
        assert "logic_unified_optimizer" in aliases
        assert "agentic_llm_router" in aliases
        assert "graphrag.ontology_generator" in aliases["graphrag_generator"]
        assert "logic_theorem_optimizer.unified_optimizer" in aliases["logic_unified_optimizer"]

    def test_backend_config_adapter_source_aliases_are_behaviorally_equivalent(self):
        graphrag_kwargs = {
            "ipfs_accelerate_config": {"provider": "openai", "model": "gpt-4"},
            "use_ipfs_accelerate": True,
        }
        base = backend_config_from_constructor_kwargs(
            "graphrag.ontology_generator",
            **graphrag_kwargs,
        )
        for alias in ("ontology_generator", "graphrag"):
            assert backend_config_from_constructor_kwargs(alias, **graphrag_kwargs) == base

        logic_kwargs = {"llm_backend": object(), "llm_backend_config": {"provider": "anthropic"}}
        base_logic = backend_config_from_constructor_kwargs(
            "logic_theorem_optimizer.unified_optimizer",
            **logic_kwargs,
        )
        for alias in ("logic.unified_optimizer", "logic_theorem_optimizer"):
            assert backend_config_from_constructor_kwargs(alias, **logic_kwargs) == base_logic

        agentic_kwargs = {"preferred_provider": LLMProvider.CLAUDE}
        base_agentic = backend_config_from_constructor_kwargs(
            "agentic.llm_router",
            **agentic_kwargs,
        )
        for alias in ("optimizer_llm_router", "agentic"):
            assert backend_config_from_constructor_kwargs(alias, **agentic_kwargs) == base_agentic


class TestConfigMerging:
    """Test configuration merging capability."""
    
    def test_merge_configs(self):
        """Test merging two configs."""
        config1 = GraphRAGConfig(
            extraction_strategy="heuristic",
            confidence_threshold=0.5,
        )
        config2 = GraphRAGConfig(
            extraction_strategy="llm",
            language="fr",
        )
        merged = config1.merge(config2)
        assert merged.extraction_strategy == "llm"
        assert merged.confidence_threshold == 0.5  # From config1
        assert merged.language == "fr"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
