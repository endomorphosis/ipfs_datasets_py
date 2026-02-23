"""Tests for formalized logic session contracts.

Tests cover:
- Configuration validation and constraints
- Result schema validation
- Serialization/deserialization (to_dict/from_dict)
- Type constraints and enum handling
- Round results and metrics tracking
"""

import pytest
from datetime import datetime, timedelta
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_session_contracts import (
    LogicSessionConfig,
    LogicSessionResult,
    RoundResult,
    ExtractionMetrics,
    ExtractionMode,
    ConvergenceReason,
)


class TestExtractionMode:
    """Tests for ExtractionMode enum."""
    
    def test_extraction_mode_values(self):
        """Verify all extraction modes are defined."""
        modes = [ExtractionMode.AUTO, ExtractionMode.FOL, ExtractionMode.TDFOL,
                 ExtractionMode.CEC, ExtractionMode.MODAL, ExtractionMode.DEONTIC]
        assert len(modes) == 6
        assert ExtractionMode.AUTO.value == "AUTO"
        assert ExtractionMode.FOL.value == "FOL"
    

class TestConvergenceReason:
    """Tests for ConvergenceReason enum."""
    
    def test_convergence_reason_values(self):
        """Verify all convergence reasons are defined."""
        reasons = [
            ConvergenceReason.THRESHOLD_MET,
            ConvergenceReason.MAX_ROUNDS,
            ConvergenceReason.NO_IMPROVEMENT,
            ConvergenceReason.MANUAL_STOP,
            ConvergenceReason.ERROR,
        ]
        assert len(reasons) == 5


class TestExtractionMetrics:
    """Tests for ExtractionMetrics validation."""
    
    def test_valid_metrics(self):
        """Valid metrics should not raise."""
        metrics = ExtractionMetrics(
            num_statements=42,
            avg_confidence=0.85,
            num_entities=10,
            num_relationships=5,
            num_contradictions=0,
            prover_validation_success=0.95,
            extraction_time=2.5,
            critique_time=1.2
        )
        metrics.validate()  # Should not raise
    
    def test_metrics_negative_statements(self):
        """Negative num_statements should fail validation."""
        metrics = ExtractionMetrics(num_statements=-1)
        with pytest.raises(ValueError, match="num_statements must be non-negative"):
            metrics.validate()
    
    def test_metrics_invalid_confidence(self):
        """Confidence outside [0, 1] should fail."""
        metrics = ExtractionMetrics(avg_confidence=1.5)
        with pytest.raises(ValueError, match="avg_confidence must be in"):
            metrics.validate()
        
        metrics = ExtractionMetrics(avg_confidence=-0.1)
        with pytest.raises(ValueError, match="avg_confidence must be in"):
            metrics.validate()
    
    def test_metrics_invalid_prover_success(self):
        """Prover validation success outside [0, 1] should fail."""
        metrics = ExtractionMetrics(prover_validation_success=1.1)
        with pytest.raises(ValueError, match="prover_validation_success must be in"):
            metrics.validate()
    
    def test_metrics_negative_time(self):
        """Negative times should fail."""
        metrics = ExtractionMetrics(extraction_time=-1.0)
        with pytest.raises(ValueError, match="extraction_time must be non-negative"):
            metrics.validate()


class TestRoundResult:
    """Tests for RoundResult validation and serialization."""
    
    def test_valid_round(self):
        """Valid round result should not raise."""
        result = RoundResult(
            round_number=1,
            score=0.85,
            dimension_scores={'clarity': 0.90, 'completeness': 0.80},
            metrics=ExtractionMetrics(num_statements=10),
            strengths=['Good coverage'],
            weaknesses=['Sparse relationships'],
            recommendations=['Add more entities']
        )
        result.validate()  # Should not raise
    
    def test_round_zero_number(self):
        """Round number must be positive."""
        result = RoundResult(round_number=0, score=0.5)
        with pytest.raises(ValueError, match="round_number must be positive"):
            result.validate()
    
    def test_round_invalid_score(self):
        """Score outside [0, 1] should fail."""
        result = RoundResult(round_number=1, score=1.5)
        with pytest.raises(ValueError, match="score must be in"):
            result.validate()
    
    def test_round_dimension_score_validation(self):
        """Dimension scores outside [0, 1] should fail."""
        result = RoundResult(
            round_number=1,
            score=0.5,
            dimension_scores={'clarity': 1.2}
        )
        with pytest.raises(ValueError, match="dimension score clarity=1.2"):
            result.validate()
    
    def test_round_to_dict_from_dict(self):
        """Round result should serialize and deserialize correctly."""
        original = RoundResult(
            round_number=2,
            score=0.88,
            dimension_scores={'clarity': 0.9},
            metrics=ExtractionMetrics(num_statements=15, avg_confidence=0.85),
            strengths=['Good'],
            weaknesses=['Bad'],
            recommendations=['Improve'],
            error=None
        )
        
        data = original.to_dict()
        restored = RoundResult.from_dict(data)
        
        assert restored.round_number == 2
        assert restored.score == 0.88
        assert restored.dimension_scores == {'clarity': 0.9}
        assert restored.metrics.num_statements == 15
        assert restored.metrics.avg_confidence == 0.85
        assert restored.strengths == ['Good']
    
    def test_round_with_error(self):
        """Round with error should load correctly."""
        result = RoundResult(
            round_number=1,
            score=0.0,
            error="Extraction failed"
        )
        
        data = result.to_dict()
        restored = RoundResult.from_dict(data)
        
        assert restored.error == "Extraction failed"


class TestLogicSessionConfig:
    """Tests for LogicSessionConfig validation."""
    
    def test_valid_config(self):
        """Valid config should not raise."""
        config = LogicSessionConfig(
            max_rounds=10,
            convergence_threshold=0.85,
            extraction_mode=ExtractionMode.AUTO,
            use_provers=['z3', 'cvc5'],
            domain='legal',
            use_ontology=True,
            strict_evaluation=False
        )
        config.validate()  # Should not raise
    
    def test_config_max_rounds_constraint(self):
        """max_rounds must be in [1, 1000]."""
        config = LogicSessionConfig(max_rounds=0)
        with pytest.raises(ValueError, match="max_rounds must be in"):
            config.validate()
        
        config = LogicSessionConfig(max_rounds=1001)
        with pytest.raises(ValueError, match="max_rounds must be in"):
            config.validate()
    
    def test_config_convergence_threshold(self):
        """convergence_threshold must be in [0, 1]."""
        config = LogicSessionConfig(convergence_threshold=-0.1)
        with pytest.raises(ValueError, match="convergence_threshold must be in"):
            config.validate()
        
        config = LogicSessionConfig(convergence_threshold=1.1)
        with pytest.raises(ValueError, match="convergence_threshold must be in"):
            config.validate()
    
    def test_config_extraction_mode_type(self):
        """extraction_mode must be ExtractionMode enum."""
        config = LogicSessionConfig(extraction_mode="INVALID")
        with pytest.raises(ValueError, match="extraction_mode must be ExtractionMode"):
            config.validate()
    
    def test_config_empty_provers(self):
        """use_provers must not be empty."""
        config = LogicSessionConfig(use_provers=[])
        with pytest.raises(ValueError, match="use_provers must not be empty"):
            config.validate()
    
    def test_config_empty_domain(self):
        """domain must be non-empty string."""
        config = LogicSessionConfig(domain='')
        with pytest.raises(ValueError, match="domain must be a non-empty string"):
            config.validate()
    
    def test_config_cache_max_size(self):
        """cache_max_size must be in [0, 10000]."""
        config = LogicSessionConfig(cache_max_size=-1)
        with pytest.raises(ValueError, match="cache_max_size must be in"):
            config.validate()
        
        config = LogicSessionConfig(cache_max_size=10001)
        with pytest.raises(ValueError, match="cache_max_size must be in"):
            config.validate()
    
    def test_config_learning_rate(self):
        """learning_rate must be in [0, 1]."""
        config = LogicSessionConfig(learning_rate=-0.5)
        with pytest.raises(ValueError, match="learning_rate must be in"):
            config.validate()
    
    def test_config_to_dict_from_dict(self):
        """Config should serialize and deserialize correctly."""
        original = LogicSessionConfig(
            max_rounds=15,
            convergence_threshold=0.9,
            extraction_mode=ExtractionMode.TDFOL,
            use_provers=['z3', 'cvc5'],
            domain='medical',
            use_ontology=False,
            strict_evaluation=True,
            learning_rate=0.15,
            seed=42
        )
        
        data = original.to_dict()
        restored = LogicSessionConfig.from_dict(data)
        
        assert restored.max_rounds == 15
        assert restored.convergence_threshold == 0.9
        assert restored.extraction_mode == ExtractionMode.TDFOL
        assert restored.use_provers == ['z3', 'cvc5']
        assert restored.domain == 'medical'
        assert restored.use_ontology is False
        assert restored.strict_evaluation is True
        assert restored.learning_rate == 0.15
        assert restored.seed == 42


class TestLogicSessionResult:
    """Tests for LogicSessionResult validation."""
    
    def test_valid_result(self):
        """Valid result should not raise."""
        result = LogicSessionResult(
            session_id='sess-001',
            success=True,
            converged=True,
            num_rounds=5,
            final_score=0.92,
            best_score=0.92,
            total_time=15.0,
            convergence_reason=ConvergenceReason.THRESHOLD_MET,
            round_results=[
                RoundResult(round_number=i, score=0.80+i*0.02)
                for i in range(1, 6)
            ]
        )
        result.validate()  # Should not raise
    
    def test_result_empty_session_id(self):
        """session_id must be non-empty."""
        result = LogicSessionResult(
            session_id='',
            success=True,
            converged=True,
            num_rounds=1,
            final_score=0.85,
            total_time=1.0
        )
        with pytest.raises(ValueError, match="session_id must be non-empty"):
            result.validate()
    
    def test_result_invalid_final_score(self):
        """final_score must be in [0, 1]."""
        result = LogicSessionResult(
            session_id='sess-001',
            success=True,
            converged=False,
            num_rounds=1,
            final_score=1.5,
            total_time=1.0
        )
        with pytest.raises(ValueError, match="final_score must be in"):
            result.validate()
    
    def test_result_best_less_than_final(self):
        """best_score must be >= final_score."""
        result = LogicSessionResult(
            session_id='sess-001',
            success=True,
            converged=False,
            num_rounds=1,
            final_score=0.9,
            best_score=0.8,
            total_time=1.0
        )
        with pytest.raises(ValueError, match="best_score must be >= final_score"):
            result.validate()
    
    def test_result_round_history_mismatch(self):
        """round_results length must match num_rounds."""
        result = LogicSessionResult(
            session_id='sess-001',
            success=True,
            converged=False,
            num_rounds=3,
            final_score=0.85,
            best_score=0.85,
            total_time=1.0,
            round_results=[RoundResult(round_number=1, score=0.85)]
        )
        with pytest.raises(ValueError, match="round_results length"):
            result.validate()
    
    def test_result_convergence_reason_when_converged(self):
        """convergence_reason must be set when converged=True."""
        result = LogicSessionResult(
            session_id='sess-001',
            success=True,
            converged=True,
            convergence_reason=None,
            num_rounds=1,
            final_score=0.85,
            best_score=0.85,
            total_time=1.0,
            round_results=[RoundResult(round_number=1, score=0.85)]
        )
        with pytest.raises(ValueError, match="convergence_reason must be set"):
            result.validate()
    
    def test_result_convergence_reason_when_not_converged(self):
        """convergence_reason should be None when converged=False."""
        result = LogicSessionResult(
            session_id='sess-001',
            success=True,
            converged=False,
            convergence_reason=ConvergenceReason.MAX_ROUNDS,
            num_rounds=1,
            final_score=0.85,
            best_score=0.85,
            total_time=1.0,
            round_results=[RoundResult(round_number=1, score=0.85)]
        )
        with pytest.raises(ValueError, match="convergence_reason should be None"):
            result.validate()
    
    def test_result_to_dict_from_dict(self):
        """Result should serialize and deserialize correctly."""
        rounds = [
            RoundResult(round_number=i, score=0.80+i*0.01,
                       strengths=['Strong'], weaknesses=['Weak'],
                       recommendations=['Improve'])
            for i in range(1, 4)
        ]
        
        original = LogicSessionResult(
            session_id='sess-001',
            success=True,
            converged=True,
            num_rounds=3,
            final_score=0.92,
            best_score=0.93,
            improvement=0.12,
            total_time=10.5,
            convergence_reason=ConvergenceReason.THRESHOLD_MET,
            round_results=rounds,
            final_extraction={'statements': ['a', 'b']},
            final_critic_score={'overall': 0.92},
            errors=['error1'],
            warnings=['warning1']
        )
        
        data = original.to_dict()
        restored = LogicSessionResult.from_dict(data)
        
        assert restored.session_id == 'sess-001'
        assert restored.success is True
        assert restored.converged is True
        assert restored.num_rounds == 3
        assert restored.final_score == 0.92
        assert restored.best_score == 0.93
        assert restored.improvement == 0.12
        assert restored.convergence_reason == ConvergenceReason.THRESHOLD_MET
        assert restored.final_extraction == {'statements': ['a', 'b']}
        assert len(restored.round_results) == 3
        assert restored.round_results[0].round_number == 1
    
    def test_result_get_summary_success(self):
        """get_summary should return proper summary for successful result."""
        rounds = [
            RoundResult(round_number=i, score=0.80+i*0.01)
            for i in range(1, 6)
        ]
        
        result = LogicSessionResult(
            session_id='sess-001',
            success=True,
            converged=True,
            num_rounds=5,
            final_score=0.94,
            best_score=0.94,
            improvement=0.14,
            total_time=20.0,
            convergence_reason=ConvergenceReason.THRESHOLD_MET,
            round_results=rounds
        )
        
        summary = result.get_summary()
        
        assert summary['success'] is True
        assert summary['converged'] is True
        assert summary['num_rounds'] == 5
        assert summary['final_score'] == 0.94
        assert summary['best_score'] == 0.94
        assert summary['improvement'] == 0.14
        assert summary['total_time'] == 20.0
        assert summary['avg_round_time'] == pytest.approx(4.0, rel=0.01)
    
    def test_result_get_summary_failure(self):
        """get_summary should return limited info for failed result."""
        result = LogicSessionResult(
            session_id='sess-001',
            success=False,
            converged=False,
            num_rounds=2,
            final_score=0.0,
            total_time=5.0,
            errors=['Extraction failed', 'Prover error']
        )
        
        summary = result.get_summary()
        
        assert summary['success'] is False
        assert summary['num_rounds'] == 2
        assert summary['total_time'] == 5.0
        assert 'errors' in summary


class TestIntegration:
    """Integration tests combining config and result."""
    
    def test_result_with_config_snapshot(self):
        """Result should properly store and restore config snapshot."""
        config = LogicSessionConfig(
            max_rounds=20,
            convergence_threshold=0.88,
            extraction_mode=ExtractionMode.TDFOL,
            domain='legal'
        )
        
        result = LogicSessionResult(
            session_id='sess-001',
            success=True,
            converged=True,
            num_rounds=10,
            final_score=0.90,
            total_time=30.0,
            convergence_reason=ConvergenceReason.THRESHOLD_MET,
            config=config.to_dict()
        )
        
        data = result.to_dict()
        restored = LogicSessionResult.from_dict(data)
        
        assert restored.config['max_rounds'] == 20
        assert restored.config['domain'] == 'legal'
    
    def test_complete_session_workflow(self):
        """Test a complete session from config to result."""
        # Create config
        config = LogicSessionConfig(
            max_rounds=5,
            convergence_threshold=0.90,
            extraction_mode=ExtractionMode.AUTO,
            use_provers=['z3'],
            domain='general'
        )
        config.validate()
        
        # Create rounds - generate scores from 0.84 to 0.98
        rounds = []
        for i in range(1, 6):
            metrics = ExtractionMetrics(
                num_statements=10*i,
                avg_confidence=0.80+i*0.02,
                num_entities=5*i,
                extraction_time=1.0*i,
                critique_time=0.5*i
            )
            metrics.validate()
            
            # Scores: 0.84, 0.88, 0.92, 0.96, 0.98
            round_score = min(0.98, 0.80 + i*0.04)
            round_result = RoundResult(
                round_number=i,
                score=round_score,
                dimension_scores={'clarity': 0.85, 'completeness': 0.82},
                metrics=metrics,
                strengths=['Good progress'],
                weaknesses=['Need more depth']
            )
            round_result.validate()
            rounds.append(round_result)
        
        # Create result
        result = LogicSessionResult(
            session_id='complete-001',
            success=True,
            converged=True,
            num_rounds=5,
            final_score=0.98,
            best_score=0.98,
            improvement=0.14,  # 0.98 - 0.84
            total_time=15.0,
            convergence_reason=ConvergenceReason.THRESHOLD_MET,
            round_results=rounds,
            config=config.to_dict()
        )
        result.validate()
        
        # Serialize and restore
        data = result.to_dict()
        restored = LogicSessionResult.from_dict(data)
        restored.validate()
        
        # Verify
        assert restored.session_id == 'complete-001'
        assert restored.converged is True
        assert len(restored.round_results) == 5
        assert restored.round_results[-1].score == 0.98
        assert restored.config['convergence_threshold'] == 0.90
