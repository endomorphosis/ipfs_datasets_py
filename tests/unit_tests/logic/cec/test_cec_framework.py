"""
Unit tests for CEC Framework.

These tests validate the main CEC framework functionality.
"""

import pytest
import sys
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from ipfs_datasets_py.logic.CEC.cec_framework import (
    CECFramework,
    FrameworkConfig,
    ReasoningMode,
    ReasoningTask
)


class TestFrameworkConfig:
    """Test suite for FrameworkConfig."""
    
    def test_default_config(self):
        """
        GIVEN default parameters
        WHEN creating a FrameworkConfig
        THEN it should have expected default values
        """
        config = FrameworkConfig()
        
        assert config.use_dcec is True
        assert config.use_talos is True
        assert config.use_eng_dcec is True
        assert config.use_shadow_prover is False
        assert config.reasoning_mode == ReasoningMode.SIMULTANEOUS
        assert config.gf_server_url is None
        assert config.spass_path is None
    
    def test_custom_config(self):
        """
        GIVEN custom parameters
        WHEN creating a FrameworkConfig
        THEN it should have the specified values
        """
        config = FrameworkConfig(
            use_dcec=False,
            use_shadow_prover=True,
            reasoning_mode=ReasoningMode.TEMPORAL
        )
        
        assert config.use_dcec is False
        assert config.use_shadow_prover is True
        assert config.reasoning_mode == ReasoningMode.TEMPORAL


class TestReasoningMode:
    """Test suite for ReasoningMode enum."""
    
    def test_reasoning_modes(self):
        """
        GIVEN ReasoningMode enum
        WHEN accessing its values
        THEN it should have all expected modes
        """
        assert ReasoningMode.SIMULTANEOUS.value == "simultaneous"
        assert ReasoningMode.TEMPORAL.value == "temporal"
        assert ReasoningMode.HYBRID.value == "hybrid"


class TestReasoningTask:
    """Test suite for ReasoningTask dataclass."""
    
    def test_reasoning_task_creation(self):
        """
        GIVEN reasoning task parameters
        WHEN creating a ReasoningTask
        THEN it should have correct attributes
        """
        task = ReasoningTask(
            natural_language="The agent must act",
            dcec_formula="O(act(agent))",
            success=True
        )
        
        assert task.natural_language == "The agent must act"
        assert task.dcec_formula == "O(act(agent))"
        assert task.success is True
        assert task.error_message is None


class TestCECFramework:
    """Test suite for CECFramework."""
    
    def test_framework_initialization_default(self):
        """
        GIVEN a CECFramework instance with default config
        WHEN initializing
        THEN it should create with expected state
        """
        framework = CECFramework()
        
        assert framework.config is not None
        assert framework.dcec_wrapper is None
        assert framework.talos_wrapper is None
        assert framework.eng_dcec_wrapper is None
        assert framework.shadow_prover_wrapper is None
        assert framework.reasoning_tasks == []
        assert framework._initialized is False
    
    def test_framework_initialization_custom_config(self):
        """
        GIVEN a CECFramework instance with custom config
        WHEN creating the framework
        THEN it should use the provided config
        """
        config = FrameworkConfig(
            use_dcec=False,
            use_shadow_prover=True
        )
        framework = CECFramework(config)
        
        assert framework.config.use_dcec is False
        assert framework.config.use_shadow_prover is True
    
    def test_framework_initialize_components(self):
        """
        GIVEN a CECFramework instance
        WHEN calling initialize
        THEN it should attempt to initialize all enabled components
        """
        framework = CECFramework()
        
        # This may succeed or fail depending on available dependencies
        # The test validates that it doesn't crash
        results = framework.initialize()
        
        assert isinstance(results, dict)
        # At least one of the keys should be present
        possible_keys = {"dcec", "talos", "eng_dcec", "shadow_prover"}
        assert any(key in results for key in possible_keys)
    
    def test_framework_repr(self):
        """
        GIVEN a CECFramework instance
        WHEN getting its string representation
        THEN it should return meaningful description
        """
        framework = CECFramework()
        repr_str = repr(framework)
        
        assert "CECFramework" in repr_str
        assert "not initialized" in repr_str
        assert "tasks=0" in repr_str
    
    def test_add_knowledge_without_initialization(self):
        """
        GIVEN a CECFramework that is not initialized
        WHEN adding knowledge
        THEN it should handle gracefully
        """
        framework = CECFramework()
        
        result = framework.add_knowledge("test statement")
        
        assert result is False
    
    def test_convert_natural_language_without_eng_dcec(self):
        """
        GIVEN a CECFramework without Eng-DCEC
        WHEN converting natural language
        THEN it should return a failure result
        """
        config = FrameworkConfig(use_eng_dcec=False)
        framework = CECFramework(config)
        framework.initialize()
        
        result = framework.convert_natural_language("The agent must act")
        
        assert result.success is False
        assert "not initialized" in result.error_message.lower()
    
    def test_prove_theorem_without_talos(self):
        """
        GIVEN a CECFramework without Talos
        WHEN proving a theorem
        THEN it should return an error result
        """
        config = FrameworkConfig(use_talos=False)
        framework = CECFramework(config)
        framework.initialize()
        
        result = framework.prove_theorem("test conjecture")
        
        assert result.result.value == "error"
        assert "not initialized" in result.error_message.lower()
    
    def test_reason_about_basic(self):
        """
        GIVEN a CECFramework
        WHEN reasoning about a statement
        THEN it should create a ReasoningTask
        """
        framework = CECFramework()
        framework.initialize()
        
        task = framework.reason_about(
            "The agent must act",
            prove=False
        )
        
        assert isinstance(task, ReasoningTask)
        assert task.natural_language == "The agent must act"
        assert len(framework.reasoning_tasks) == 1
    
    def test_batch_reason(self):
        """
        GIVEN a CECFramework and multiple statements
        WHEN batch reasoning
        THEN it should process all statements
        """
        framework = CECFramework()
        framework.initialize()
        
        statements = [
            "The agent must act",
            "The agent believes X",
            "The agent knows Y"
        ]
        
        tasks = framework.batch_reason(statements, prove=False)
        
        assert len(tasks) == 3
        assert all(isinstance(task, ReasoningTask) for task in tasks)
        assert len(framework.reasoning_tasks) == 3
    
    def test_get_statistics_empty(self):
        """
        GIVEN a new CECFramework
        WHEN getting statistics
        THEN it should return valid statistics with zero counts
        """
        framework = CECFramework()
        
        stats = framework.get_statistics()
        
        assert isinstance(stats, dict)
        assert "initialized" in stats
        assert stats["reasoning_tasks"] == 0
        assert stats["successful_tasks"] == 0
    
    def test_get_statistics_with_tasks(self):
        """
        GIVEN a CECFramework with reasoning tasks
        WHEN getting statistics
        THEN it should reflect the correct counts
        """
        framework = CECFramework()
        framework.initialize()
        
        # Add some tasks
        framework.reason_about("statement 1", prove=False)
        framework.reason_about("statement 2", prove=False)
        
        stats = framework.get_statistics()
        
        assert stats["reasoning_tasks"] == 2
        assert stats["successful_tasks"] >= 0  # May vary based on initialization


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
