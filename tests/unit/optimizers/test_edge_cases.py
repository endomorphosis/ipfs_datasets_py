"""
Edge case and boundary condition tests for optimizer modules.

This test suite covers edge cases and boundary conditions that should be
handled gracefully by all optimizers:

- Empty inputs (zero entities, zero queries, zero statements)
- Very large inputs (performance, memory usage)
- Malformed inputs (invalid JSON, missing fields, null values)
- Invalid types (wrong dtypes, incompatible formats)
- Boundary conditions (1 entity, 1 query, single statement)

The tests use deterministic, reproducible inputs to ensure consistent behavior.

pytest -xvs tests/unit/optimizers/test_edge_cases.py
"""

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.unified_optimizer import LogicTheoremOptimizer
from ipfs_datasets_py.optimizers.common.base_optimizer import OptimizerConfig, OptimizationContext


# ============================================================================
# OntologyOptimizer Edge Cases
# ============================================================================

class TestOntologyOptimizerEmptyInput:
    """Test OntologyOptimizer with empty inputs."""
    
    def test_analyze_batch_empty_list(self):
        """analyze_batch should handle empty session list gracefully."""
        optimizer = OntologyOptimizer()
        report = optimizer.analyze_batch([])
        
        assert report.average_score == 0.0
        assert report.trend == 'insufficient_data'
        assert len(report.recommendations) > 0
        assert 'Need more sessions' in report.recommendations[0]
    
    def test_analyze_batch_no_valid_scores(self):
        """analyze_batch should handle sessions with missing scores."""
        optimizer = OntologyOptimizer()
        
        # Create mock sessions with no scores
        mock_sessions = [
            type('Session', (), {'critic_scores': None, 'critic_score': None})(),
            type('Session', (), {'critic_scores': [], 'critic_score': None})(),
        ]
        
        report = optimizer.analyze_batch(mock_sessions)
        
        assert report.average_score == 0.0
        assert report.trend == 'no_scores'
        assert 'No valid scores' in report.recommendations[0]
    
    def test_analyze_trends_insufficient_history(self):
        """analyze_trends should require at least 2 historical batches."""
        optimizer = OntologyOptimizer()
        
        # Add only 1 batch to history (need 2+)
        from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OptimizationReport
        optimizer._history.append(
            OptimizationReport(average_score=0.75, trend='stable')
        )
        
        trends = optimizer.analyze_trends()
        
        assert trends['trend'] == 'insufficient_data'
        assert trends['improvement_rate'] == 0.0
        assert 'Need more batches' in trends['recommendations'][0]
    
    def test_analyze_trends_empty_history(self):
        """analyze_trends should handle completely empty history."""
        optimizer = OntologyOptimizer()
        
        # Don't add anything to history
        trends = optimizer.analyze_trends()
        
        assert trends['trend'] == 'insufficient_data'
        assert trends['convergence_estimate'] is None


class TestOntologyOptimizerLargeInput:
    """Test OntologyOptimizer with very large inputs."""
    
    def test_analyze_batch_many_sessions(self):
        """analyze_batch should handle 1000s of sessions efficiently."""
        optimizer = OntologyOptimizer()
        
        # Create 100 deterministic sessions with scores
        @dataclass
        class MockSession:
            id: int
            critic_scores: Optional[List] = None
            critic_score: Optional[Any] = None
        
        @dataclass
        class MockScore:
            overall: float
        
        sessions = []
        for i in range(100):
            session = MockSession(id=i)
            # Create deterministic scores (sine wave pattern)
            score = 0.5 + 0.3 * ((i % 10) / 10.0)
            session.critic_score = MockScore(overall=score)
            sessions.append(session)
        
        # Should complete without error or timeout
        report = optimizer.analyze_batch(sessions)
        
        assert report.average_score > 0.5
        assert report.average_score < 1.0
        assert report.metadata['num_sessions'] == 100
        assert len(report.recommendations) > 0
    
    def test_identify_patterns_large_ontology(self):
        """identify_patterns should handle ontologies with many entities."""
        optimizer = OntologyOptimizer()
        
        # Create large ontology
        large_ontology = {
            'entities': [
                {
                    'id': f'entity_{i}',
                    'type': f'type_{i % 10}',
                    'properties': {'name': f'Entity {i}'}
                }
                for i in range(1000)
            ],
            'relationships': [
                {
                    'source': f'entity_{i}',
                    'target': f'entity_{(i+1) % 1000}',
                    'type': 'connects_to'
                }
                for i in range(500)
            ]
        }
        
        patterns = optimizer.identify_patterns([large_ontology])
        
        assert patterns is not None
        assert isinstance(patterns, dict)


class TestOntologyOptimizerMalformedInput:
    """Test OntologyOptimizer with malformed/invalid inputs."""
    
    def test_analyze_batch_with_none_values(self):
        """analyze_batch should handle sessions with None values gracefully."""
        optimizer = OntologyOptimizer()
        
        sessions = [
            None,
            type('Session', (), {'critic_score': None})(),
            type('Session', (), {'critic_scores': None})(),
        ]
        
        report = optimizer.analyze_batch(sessions)
        
        # Should handle gracefully (may have low score or no scores)
        assert isinstance(report, object)
    
    def test_identify_patterns_missing_fields(self):
        """identify_patterns should handle ontologies missing expected fields."""
        optimizer = OntologyOptimizer()
        
        # Ontology missing 'entities' field
        incomplete_ontology = {
            'relationships': [
                {'source': 'a', 'target': 'b', 'type': 'connects'}
            ]
            # Missing 'entities' key
        }
        
        patterns = optimizer.identify_patterns([incomplete_ontology])
        
        # Should not crash
        assert patterns is not None


class TestOntologyOptimizerBoundaryConditions:
    """Test OntologyOptimizer boundary conditions."""
    
    def test_analyze_batch_single_session(self):
        """analyze_batch should handle single session without error."""
        optimizer = OntologyOptimizer()
        
        @dataclass
        class MockScore:
            overall: float
        
        session = type('Session', (), {
            'critic_score': MockScore(overall=0.75)
        })()
        
        report = optimizer.analyze_batch([session])
        
        assert report.average_score == 0.75
        assert report.metadata['num_sessions'] == 1
    
    def test_compute_std_single_value(self):
        """_compute_std should handle single value without division by zero."""
        optimizer = OntologyOptimizer()
        
        # Single value should give std of 0
        std = optimizer._compute_std([0.5])
        assert std == 0.0
    
    def test_compute_std_identical_values(self):
        """_compute_std should handle all identical values."""
        optimizer = OntologyOptimizer()
        
        # All same values should give std of 0
        std = optimizer._compute_std([0.5, 0.5, 0.5, 0.5])
        assert std == 0.0
    
    def test_analyze_trends_ascending_scores(self):
        """analyze_trends should detect improving trend."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OptimizationReport
        
        optimizer = OntologyOptimizer()
        
        # Add reports with strictly improving scores
        for i in range(5):
            report = OptimizationReport(
                average_score=0.5 + (i * 0.05),
                trend='improving'
            )
            optimizer._history.append(report)
        
        trends = optimizer.analyze_trends()
        
        assert trends['trend'] == 'improving'
        assert trends['improvement_rate'] > 0


# ============================================================================
# LogicTheoremOptimizer Edge Cases
# ============================================================================

class TestLogicTheoremOptimizerEmptyInput:
    """Test LogicTheoremOptimizer with empty inputs."""
    
    def test_validate_statements_empty_list(self):
        """validate_statements should handle empty statement list."""
        optimizer = LogicTheoremOptimizer()
        
        context = OptimizationContext(
            session_id='test-001',
            input_data='',
            domain='general'
        )
        
        result = optimizer.validate_statements([], context)
        
        # Empty list is technically valid (no invalid statements)
        assert isinstance(result, object)
        assert result.provers_used is not None
    
    def test_validate_statements_none_values(self):
        """validate_statements should handle None values gracefully."""
        optimizer = LogicTheoremOptimizer()
        
        context = OptimizationContext(
            session_id='test-001',
            input_data='',
            domain='general'
        )
        
        # Should handle None gracefully
        result = optimizer.validate_statements([None, None], context)
        
        assert isinstance(result, object)


class TestLogicTheoremOptimizerMalformedInput:
    """Test LogicTheoremOptimizer with malformed logical statements."""
    
    def test_validate_statements_invalid_tdfol(self):
        """validate_statements should handle invalid TDFOL syntax."""
        optimizer = LogicTheoremOptimizer()
        
        context = OptimizationContext(
            session_id='test-001',
            input_data='invalid tdfol',
            domain='general'
        )
        
        # Pass invalid TDFOL statement
        invalid_statement = 'INVALID %%% TDFOL [[[['
        
        result = optimizer.validate_statements([invalid_statement], context)
        
        # Should handle gracefully
        assert isinstance(result, object)
    
    def test_validate_statements_contradictory(self):
        """validate_statements should handle contradictory statements."""
        optimizer = LogicTheoremOptimizer()
        
        context = OptimizationContext(
            session_id='test-001',
            input_data='',
            domain='general'
        )
        
        # Contradictory statements
        statements = [
            'P',
            'NOT P',
        ]
        
        result = optimizer.validate_statements(statements, context)
        
        # May not all validate
        assert isinstance(result, object)


class TestLogicTheoremOptimizerBoundaryConditions:
    """Test LogicTheoremOptimizer boundary conditions."""
    
    def test_validate_statements_single_statement(self):
        """validate_statements should handle single statement."""
        optimizer = LogicTheoremOptimizer()
        
        context = OptimizationContext(
            session_id='test-001',
            input_data='',
            domain='general'
        )
        
        result = optimizer.validate_statements(['P'], context)
        
        assert isinstance(result, object)
        assert len(result.provers_used) >= 0


# ============================================================================
# JSON/Schema Edge Cases
# ============================================================================

class TestOntologySchemaEdgeCases:
    """Test ontology schema handling for edge cases."""
    
    def test_ontology_dict_empty_entities(self):
        """Ontology with empty entities list should be valid."""
        ontology = {
            'entities': [],
            'relationships': [],
            'metadata': {'source': 'test'}
        }
        
        # Should not crash when serialized/deserialized
        json_str = json.dumps(ontology)
        restored = json.loads(json_str)
        
        assert len(restored['entities']) == 0
    
    def test_ontology_dict_missing_metadata(self):
        """Ontology without metadata field should default gracefully."""
        ontology = {
            'entities': [{'id': 'e1', 'type': 'Entity'}],
            'relationships': []
        }
        
        # Missing 'metadata' is okay
        assert 'metadata' not in ontology
        
        # Add default if needed
        ontology.setdefault('metadata', {})
        assert ontology['metadata'] == {}
    
    def test_ontology_dict_with_nulls(self):
        """Ontology with null values should be handled."""
        ontology = {
            'entities': [
                {'id': 'e1', 'type': None, 'properties': None}
            ],
            'relationships': None,
            'metadata': None
        }
        
        # Should serialize without error
        json_str = json.dumps(ontology)
        restored = json.loads(json_str)
        
        assert restored['entities'][0]['type'] is None
    
    def test_malformed_json_recovery(self):
        """Test parsing error handling for bad JSON."""
        bad_json = '{ "entities": [ { "id": "e1" ] }'  # Missing closing brace
        
        with pytest.raises(json.JSONDecodeError):
            json.loads(bad_json)
        
        # Can parse corrected version
        good_json = '{ "entities": [ { "id": "e1" } ] }'
        restored = json.loads(good_json)
        assert restored['entities'][0]['id'] == 'e1'


# ============================================================================
# Integration Tests: Cross-Optimizer Edge Cases
# ============================================================================

class TestOptimizersUnderStress:
    """Test optimizers under stress conditions."""
    
    def test_ontology_optimizer_parallel_with_empty_batch(self):
        """analyze_batch_parallel should handle empty batch."""
        optimizer = OntologyOptimizer()
        
        report = optimizer.analyze_batch_parallel([], max_workers=4)
        
        assert report.average_score == 0.0
        assert report.trend == 'insufficient_data'
    
    def test_optimizer_config_with_extreme_values(self):
        """OptimizerConfig should handle extreme parameter values."""
        # Very large values
        config = OptimizerConfig(
            max_iterations=10000,
            target_score=0.9999,
            learning_rate=0.999,
            convergence_threshold=0.00001,
        )
        
        assert config.max_iterations == 10000
        assert config.target_score == 0.9999
        assert config.learning_rate == 0.999
    
    def test_optimization_context_with_large_metadata(self):
        """OptimizationContext should handle large metadata dicts."""
        # Create large metadata
        large_metadata = {
            f'key_{i}': f'value_{i}' * 100
            for i in range(1000)
        }
        
        context = OptimizationContext(
            session_id='test-001',
            input_data='test',
            domain='general',
            metadata=large_metadata
        )
        
        assert len(context.metadata) == 1000


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
