"""Tests for Prover Integration Adapter.

Tests for Phase 2 integration with theorem provers.
"""

import pytest
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    ProverIntegrationAdapter,
    ProverVerificationResult,
    AggregatedProverResult,
    LogicExtractor,
    LogicExtractionContext,
    DataType
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.prover_integration import ProverStatus


class TestProverIntegrationAdapter:
    """Tests for ProverIntegrationAdapter."""
    
    def test_init_default(self):
        """Test adapter initialization with defaults."""
        adapter = ProverIntegrationAdapter()
        
        assert adapter.use_provers == ['z3']
        assert adapter.enable_cache == True
        assert adapter.default_timeout == 5.0
    
    def test_init_multiple_provers(self):
        """Test adapter initialization with multiple provers."""
        adapter = ProverIntegrationAdapter(use_provers=['z3', 'cvc5'])
        
        assert 'z3' in adapter.use_provers
        assert 'cvc5' in adapter.use_provers
    
    def test_init_with_cache_disabled(self):
        """Test adapter initialization with cache disabled."""
        adapter = ProverIntegrationAdapter(enable_cache=False)
        
        assert adapter.cache is None
    
    def test_verify_statement_basic(self):
        """Test basic statement verification."""
        # GIVEN an adapter and a simple statement
        adapter = ProverIntegrationAdapter(use_provers=[])
        extractor = LogicExtractor()
        context = LogicExtractionContext(
            data="All employees must complete training",
            data_type=DataType.TEXT
        )
        result = extractor.extract(context)
        
        if result.statements:
            statement = result.statements[0]
            
            # WHEN verifying the statement (no provers, should return empty result)
            verification = adapter.verify_statement(statement)
            
            # THEN result should be valid structure
            assert isinstance(verification, AggregatedProverResult)
            assert isinstance(verification.prover_results, list)
    
    def test_statistics_tracking(self):
        """Test verification statistics tracking."""
        # GIVEN an adapter
        adapter = ProverIntegrationAdapter(use_provers=[])
        
        # WHEN getting statistics
        stats = adapter.get_statistics()
        
        # THEN statistics should be valid
        assert 'verifications' in stats
        assert 'cache_hits' in stats
        assert 'cache_misses' in stats
        assert 'available_provers' in stats
        assert isinstance(stats['available_provers'], list)
    
    def test_close(self):
        """Test adapter cleanup."""
        # GIVEN an adapter
        adapter = ProverIntegrationAdapter()
        
        # WHEN closing
        adapter.close()
        
        # THEN should not raise exception
        assert True


class TestProverVerificationResult:
    """Tests for ProverVerificationResult."""
    
    def test_create_valid_result(self):
        """Test creating a valid verification result."""
        result = ProverVerificationResult(
            prover_name='z3',
            status=ProverStatus.VALID,
            is_valid=True,
            confidence=0.95,
            proof_time=0.5
        )
        
        assert result.prover_name == 'z3'
        assert result.status == ProverStatus.VALID
        assert result.is_valid == True
        assert result.confidence == 0.95
        assert result.proof_time == 0.5
    
    def test_create_error_result(self):
        """Test creating an error result."""
        result = ProverVerificationResult(
            prover_name='lean',
            status=ProverStatus.ERROR,
            is_valid=False,
            confidence=0.0,
            proof_time=0.1,
            error_message="Prover unavailable"
        )
        
        assert result.status == ProverStatus.ERROR
        assert result.is_valid == False
        assert result.error_message == "Prover unavailable"


class TestAggregatedProverResult:
    """Tests for AggregatedProverResult."""
    
    def test_create_aggregated_result(self):
        """Test creating an aggregated result."""
        prover_results = [
            ProverVerificationResult(
                prover_name='z3',
                status=ProverStatus.VALID,
                is_valid=True,
                confidence=0.95,
                proof_time=0.5
            ),
            ProverVerificationResult(
                prover_name='cvc5',
                status=ProverStatus.VALID,
                is_valid=True,
                confidence=0.90,
                proof_time=0.6
            )
        ]
        
        result = AggregatedProverResult(
            overall_valid=True,
            confidence=0.925,
            prover_results=prover_results,
            agreement_rate=1.0,
            verified_by=['z3', 'cvc5']
        )
        
        assert result.overall_valid == True
        assert result.confidence == 0.925
        assert len(result.prover_results) == 2
        assert result.agreement_rate == 1.0
        assert 'z3' in result.verified_by
        assert 'cvc5' in result.verified_by


class TestProverIntegrationWithCritic:
    """Integration tests with LogicCritic."""
    
    def test_critic_with_prover_integration(self):
        """Test LogicCritic with prover integration enabled."""
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import LogicCritic
        
        # GIVEN a critic with prover integration enabled
        critic = LogicCritic(use_provers=[], enable_prover_integration=True)
        
        # WHEN evaluating an extraction result
        extractor = LogicExtractor()
        context = LogicExtractionContext(
            data="All employees must complete training"
        )
        extraction_result = extractor.extract(context)
        
        score = critic.evaluate(extraction_result)
        
        # THEN score should be valid
        assert score is not None
        assert 0.0 <= score.overall <= 1.0
    
    def test_critic_without_prover_integration(self):
        """Test LogicCritic with prover integration disabled."""
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import LogicCritic
        
        # GIVEN a critic with prover integration disabled (legacy mode)
        critic = LogicCritic(use_provers=[], enable_prover_integration=False)
        
        # WHEN evaluating an extraction result
        extractor = LogicExtractor()
        context = LogicExtractionContext(
            data="All employees must complete training"
        )
        extraction_result = extractor.extract(context)
        
        score = critic.evaluate(extraction_result)
        
        # THEN score should be valid
        assert score is not None
        assert 0.0 <= score.overall <= 1.0
    
    def test_critic_backwards_compatible(self):
        """Test that LogicCritic is backwards compatible."""
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import LogicCritic
        
        # GIVEN a critic initialized the old way (no enable_prover_integration param)
        critic = LogicCritic(use_provers=[])
        
        # THEN it should work with default Phase 2 behavior
        assert hasattr(critic, 'enable_prover_integration')
        assert critic.enable_prover_integration == True


class TestProverCaching:
    """Tests for proof caching functionality."""
    
    def test_cache_statistics(self):
        """Test cache statistics tracking."""
        # GIVEN an adapter with cache enabled
        adapter = ProverIntegrationAdapter(enable_cache=True, use_provers=[])
        
        # WHEN getting statistics
        stats = adapter.get_statistics()
        
        # THEN cache statistics should be present
        assert 'cache_hits' in stats
        assert 'cache_misses' in stats
        assert 'cache_hit_rate' in stats
        assert stats['cache_hit_rate'] >= 0.0
        assert stats['cache_hit_rate'] <= 1.0
