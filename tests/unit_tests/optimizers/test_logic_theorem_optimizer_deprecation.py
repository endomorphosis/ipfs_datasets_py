"""Tests for Logic Theorem Optimizer deprecation warnings and migration.

This module tests:
1. Deprecation warnings for TheoremSession, LogicHarness, and their configs
2. Backward compatibility of deprecated classes
3. LogicTheoremOptimizer unified interface
4. Migration patterns from old to new API
"""

import pytest
import warnings
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    # Deprecated classes (should issue warnings)
    TheoremSession,
    SessionConfig,
    SessionResult,
    LogicHarness,
    HarnessConfig,
    HarnessResult,
    # New unified optimizer
    LogicTheoremOptimizer,
    # Supporting classes
    LogicExtractor,
    LogicCritic,
)
from ipfs_datasets_py.optimizers.common import (
    OptimizerConfig,
    OptimizationContext,
    OptimizationStrategy,
)


class TestDeprecationWarnings:
    """Test that deprecated classes issue appropriate warnings."""
    
    def test_session_config_deprecation(self):
        """Test SessionConfig issues deprecation warning.
        
        GIVEN: SessionConfig class
        WHEN: Instantiating SessionConfig
        THEN: DeprecationWarning is issued
        """
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = SessionConfig(max_rounds=5)
            
            # Check warning was issued
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "SessionConfig is deprecated" in str(w[0].message)
            assert "OptimizerConfig" in str(w[0].message)
            
            # Check config still works
            assert config.max_rounds == 5
    
    def test_harness_config_deprecation(self):
        """Test HarnessConfig issues deprecation warning.
        
        GIVEN: HarnessConfig class
        WHEN: Instantiating HarnessConfig
        THEN: DeprecationWarning is issued
        """
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = HarnessConfig(parallelism=2)
            
            # Check warning was issued
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "HarnessConfig is deprecated" in str(w[0].message)
            assert "OptimizerConfig" in str(w[0].message)
            
            # Check config still works
            assert config.parallelism == 2
    
    def test_theorem_session_deprecation(self):
        """Test TheoremSession issues deprecation warning.
        
        GIVEN: TheoremSession class
        WHEN: Instantiating TheoremSession
        THEN: DeprecationWarning is issued
        """
        extractor = LogicExtractor()
        critic = LogicCritic(use_provers=[])
        
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            session = TheoremSession(extractor, critic)
            
            # Check warning was issued (1 from TheoremSession + 1 from SessionConfig)
            assert len(w) >= 1
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) >= 1
            
            # Check at least one mentions TheoremSession
            messages = [str(x.message) for x in deprecation_warnings]
            assert any("TheoremSession is deprecated" in msg for msg in messages)
            assert any("LogicTheoremOptimizer" in msg for msg in messages)
    
    def test_logic_harness_deprecation(self):
        """Test LogicHarness issues deprecation warning.
        
        GIVEN: LogicHarness class
        WHEN: Instantiating LogicHarness
        THEN: DeprecationWarning is issued
        """
        extractor = LogicExtractor()
        critic = LogicCritic(use_provers=[])
        
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            harness = LogicHarness(extractor, critic)
            
            # Check warning was issued (1 from LogicHarness + 1 from HarnessConfig)
            assert len(w) >= 1
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) >= 1
            
            # Check at least one mentions LogicHarness
            messages = [str(x.message) for x in deprecation_warnings]
            assert any("LogicHarness is deprecated" in msg for msg in messages)
            assert any("LogicTheoremOptimizer" in msg for msg in messages)


class TestBackwardCompatibility:
    """Test that deprecated classes still work correctly."""
    
    def test_session_config_backward_compat(self):
        """Test SessionConfig still functions correctly.
        
        GIVEN: SessionConfig with custom parameters
        WHEN: Using the config
        THEN: All parameters work as expected
        """
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            config = SessionConfig(
                max_rounds=15,
                convergence_threshold=0.9,
                use_ontology=False,
                strict_evaluation=True
            )
            
            assert config.max_rounds == 15
            assert config.convergence_threshold == 0.9
            assert config.use_ontology is False
            assert config.strict_evaluation is True
    
    def test_harness_config_backward_compat(self):
        """Test HarnessConfig still functions correctly.
        
        GIVEN: HarnessConfig with custom parameters
        WHEN: Using the config
        THEN: All parameters work as expected
        """
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            config = HarnessConfig(
                parallelism=8,
                max_retries=5,
                timeout_per_session=600.0,
                batch_size=20
            )
            
            assert config.parallelism == 8
            assert config.max_retries == 5
            assert config.timeout_per_session == 600.0
            assert config.batch_size == 20
    
    def test_theorem_session_backward_compat(self):
        """Test TheoremSession still functions correctly.
        
        GIVEN: TheoremSession with extractor and critic
        WHEN: Using the session
        THEN: Session can be created and has expected attributes
        """
        extractor = LogicExtractor()
        critic = LogicCritic(use_provers=[])
        
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            session = TheoremSession(extractor, critic)
            
            assert session.extractor is extractor
            assert session.critic is critic
            assert session.config is not None
            assert isinstance(session.config, SessionConfig)
    
    def test_logic_harness_backward_compat(self):
        """Test LogicHarness still functions correctly.
        
        GIVEN: LogicHarness with extractor and critic
        WHEN: Using the harness
        THEN: Harness can be created and has expected attributes
        """
        extractor = LogicExtractor()
        critic = LogicCritic(use_provers=[])
        
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            harness = LogicHarness(extractor, critic)
            
            assert harness.extractor is extractor
            assert harness.critic is critic
            assert harness.config is not None
            assert isinstance(harness.config, HarnessConfig)


class TestUnifiedOptimizer:
    """Test the new LogicTheoremOptimizer unified interface."""
    
    def test_unified_optimizer_init(self):
        """Test LogicTheoremOptimizer initialization.
        
        GIVEN: OptimizerConfig
        WHEN: Creating LogicTheoremOptimizer
        THEN: Optimizer is created successfully with correct config
        """
        config = OptimizerConfig(
            max_iterations=5,
            target_score=0.9,
            metrics_enabled=True
        )
        
        optimizer = LogicTheoremOptimizer(
            config=config,
            use_provers=['z3'],
            domain='legal'
        )
        
        assert optimizer.config == config
        assert optimizer.config.max_iterations == 5
        assert optimizer.config.target_score == 0.9
        assert optimizer.config.metrics_enabled is True
    
    def test_unified_optimizer_default_config(self):
        """Test LogicTheoremOptimizer with default config.
        
        GIVEN: No config specified
        WHEN: Creating LogicTheoremOptimizer
        THEN: Default config is used
        """
        optimizer = LogicTheoremOptimizer()
        
        assert optimizer.config is not None
        assert optimizer.config.max_iterations == 10  # Default
        assert optimizer.config.target_score == 0.85  # Default
        assert optimizer.config.metrics_enabled is True  # Default
    
    def test_unified_optimizer_run_session_structure(self):
        """Test LogicTheoremOptimizer.run_session returns correct structure.
        
        GIVEN: LogicTheoremOptimizer and sample data
        WHEN: Running a session
        THEN: Result has expected structure with artifact, score, iterations, valid, metrics
        """
        optimizer = LogicTheoremOptimizer(
            config=OptimizerConfig(max_iterations=2)
        )
        
        context = OptimizationContext(
            session_id="test-001",
            input_data="All employees must complete training",
            domain="general"
        )
        
        result = optimizer.run_session(
            data="All employees must complete training",
            context=context
        )
        
        # Check result structure
        assert 'artifact' in result
        assert 'score' in result
        assert 'iterations' in result
        assert 'valid' in result
        assert 'execution_time' in result
        assert 'metrics' in result
        
        # Check metrics structure (from BaseOptimizer)
        metrics = result['metrics']
        assert 'initial_score' in metrics
        assert 'final_score' in metrics
        assert 'improvement' in metrics
        assert 'iterations' in metrics
        assert 'execution_time' in metrics


class TestMigrationPatterns:
    """Test that migration patterns from old to new API work correctly."""
    
    def test_migration_config_pattern(self):
        """Test migration from SessionConfig to OptimizerConfig.
        
        GIVEN: Old SessionConfig parameters
        WHEN: Migrating to OptimizerConfig
        THEN: Equivalent configuration is achieved
        """
        # Old way
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            old_config = SessionConfig(
                max_rounds=10,
                convergence_threshold=0.85
            )
        
        # New way (equivalent)
        new_config = OptimizerConfig(
            max_iterations=10,  # Was max_rounds
            target_score=0.85   # Was convergence_threshold
        )
        
        assert new_config.max_iterations == old_config.max_rounds
        assert new_config.target_score == old_config.convergence_threshold
    
    def test_migration_context_pattern(self):
        """Test migration from dict context to OptimizationContext.
        
        GIVEN: Old context dict pattern
        WHEN: Migrating to OptimizationContext
        THEN: Context is properly structured
        """
        # Old way (dict)
        old_context = {
            'domain': 'legal',
            'data_type': 'text'
        }
        
        # New way (OptimizationContext)
        new_context = OptimizationContext(
            session_id="session-001",
            input_data="sample data",
            domain=old_context['domain']
        )
        
        assert new_context.domain == old_context['domain']
        assert new_context.session_id is not None
    
    def test_migration_result_pattern(self):
        """Test migration from SessionResult to result dict.
        
        GIVEN: Result dict from LogicTheoremOptimizer
        WHEN: Accessing result data
        THEN: Can map to old SessionResult attributes
        """
        optimizer = LogicTheoremOptimizer(
            config=OptimizerConfig(max_iterations=2)
        )
        
        context = OptimizationContext(
            session_id="test-001",
            input_data="All employees must complete training",
            domain="general"
        )
        
        result = optimizer.run_session(
            data="All employees must complete training",
            context=context
        )
        
        # Map new result to old SessionResult attributes
        converged = result['score'] >= optimizer.config.target_score
        num_rounds = result['iterations']
        success = result['valid']
        total_time = result['execution_time']
        extraction_result = result['artifact']
        
        # All mappings should work
        assert isinstance(converged, bool)
        assert isinstance(num_rounds, int)
        assert isinstance(success, bool)
        assert isinstance(total_time, float)
        assert extraction_result is not None


class TestOptimizerCapabilities:
    """Test LogicTheoremOptimizer specific capabilities."""
    
    def test_optimizer_has_base_methods(self):
        """Test that optimizer has all BaseOptimizer methods.
        
        GIVEN: LogicTheoremOptimizer instance
        WHEN: Checking for required methods
        THEN: All BaseOptimizer methods are present
        """
        optimizer = LogicTheoremOptimizer()
        
        # Check required methods from BaseOptimizer
        assert hasattr(optimizer, 'generate')
        assert hasattr(optimizer, 'critique')
        assert hasattr(optimizer, 'optimize')
        assert hasattr(optimizer, 'validate')
        assert hasattr(optimizer, 'run_session')
        assert callable(optimizer.generate)
        assert callable(optimizer.critique)
        assert callable(optimizer.optimize)
        assert callable(optimizer.validate)
        assert callable(optimizer.run_session)
    
    def test_optimizer_config_validation(self):
        """Test that optimizer validates configuration.
        
        GIVEN: OptimizerConfig with various settings
        WHEN: Creating optimizer
        THEN: Configuration is properly stored
        """
        config = OptimizerConfig(
            strategy=OptimizationStrategy.SGD,
            max_iterations=15,
            target_score=0.9,
            early_stopping=True,
            validation_enabled=True,
            metrics_enabled=True
        )
        
        optimizer = LogicTheoremOptimizer(config=config)
        
        assert optimizer.config.strategy == OptimizationStrategy.SGD
        assert optimizer.config.max_iterations == 15
        assert optimizer.config.target_score == 0.9
        assert optimizer.config.early_stopping is True
        assert optimizer.config.validation_enabled is True
        assert optimizer.config.metrics_enabled is True
