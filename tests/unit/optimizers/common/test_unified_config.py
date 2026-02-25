"""Tests for unified configuration and context dataclasses."""

import pytest
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
)


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
