"""Unit tests for custom __repr__ implementations on public dataclasses.

Verifies that all public dataclasses have useful REPL-friendly repr strings
that show key fields concisely.
"""

import pytest
from datetime import datetime
from ipfs_datasets_py.optimizers.common.base_session import RoundRecord, BaseSession
from ipfs_datasets_py.optimizers.common.performance_monitor import OptimizationCycleMetrics


class TestRoundRecordRepr:
    """Test __repr__ for RoundRecord dataclass."""

    def test_repr_basic(self):
        """Test repr shows round number, score, and duration."""
        record = RoundRecord(
            round_number=1,
            score=0.75,
            feedback=["Add more entities"],
            duration_ms=123.4,
        )
        repr_str = repr(record)
        
        assert "RoundRecord" in repr_str
        assert "round=1" in repr_str
        assert "score=0.750" in repr_str
        assert "duration_ms=123.4" in repr_str

    def test_repr_includes_feedback_count(self):
        """Test repr shows count of feedback items."""
        record = RoundRecord(
            round_number=2,
            score=0.82,
            feedback=["Improve consistency", "Add relationships", "Fix typos"],
            duration_ms=200.0,
        )
        repr_str = repr(record)
        
        assert "feedback_items=3" in repr_str

    def test_repr_shows_artifact_presence(self):
        """Test repr indicates whether artifact snapshot exists."""
        # With artifact
        record_with = RoundRecord(
            round_number=1,
            score=0.65,
            artifact_snapshot={"entities": [], "relationships": []},
            duration_ms=100.0,
        )
        assert "has_artifact=True" in repr(record_with)
        
        # Without artifact
        record_without = RoundRecord(
            round_number=2,
            score=0.70,
            duration_ms=100.0,
        )
        assert "has_artifact=False" in repr(record_without)

    def test_repr_no_feedback(self):
        """Test repr handles empty feedback list."""
        record = RoundRecord(
            round_number=1,
            score=0.50,
            duration_ms=50.0,
        )
        repr_str = repr(record)
        
        assert "feedback_items=0" in repr_str

    def test_repr_evaluates_without_error(self):
        """Test repr can be safely evaluated in REPL context."""
        record = RoundRecord(round_number=3, score=0.88, duration_ms=150.0)
        repr_str = repr(record)
        
        # Should not raise exception
        assert isinstance(repr_str, str)
        assert len(repr_str) > 0


class TestBaseSessionRepr:
    """Test __repr__ for BaseSession dataclass."""

    def test_repr_active_session(self):
        """Test repr for active session (not finished)."""
        session = BaseSession(
            session_id="test-001",
            domain="graphrag",
            max_rounds=10,
            target_score=0.85,
        )
        session.record_round(score=0.62, feedback=["Improve coverage"])
        session.record_round(score=0.75, feedback=["Add entities"])
        
        repr_str = repr(session)
        
        assert "BaseSession" in repr_str
        assert "id='test-001'" in repr_str
        assert "domain='graphrag'" in repr_str
        assert "rounds=2/10" in repr_str
        assert "best_score=0.750" in repr_str
        assert "status=active" in repr_str

    def test_repr_converged_session(self):
        """Test repr for converged session."""
        session = BaseSession(
            session_id="test-002",
            domain="logic",
            max_rounds=5,
            target_score=0.90,
        )
        session.record_round(score=0.80, feedback=["Good start"])
        session.record_round(score=0.92, feedback=["Excellent"])
        
        repr_str = repr(session)
        
        assert "status=converged" in repr_str
        assert "best_score=0.920" in repr_str

    def test_repr_finished_session(self):
        """Test repr for finished but not converged session."""
        session = BaseSession(
            session_id="test-003",
            domain="agentic",
            max_rounds=3,
            target_score=0.95,
        )
        session.record_round(score=0.60, feedback=["Try harder"])
        session.record_round(score=0.65, feedback=["Still low"])
        session.finish()
        
        repr_str = repr(session)
        
        assert "status=finished" in repr_str
        assert "rounds=2/3" in repr_str

    def test_repr_no_rounds(self):
        """Test repr for session with no rounds recorded."""
        session = BaseSession(
            session_id="test-004",
            domain="general",
        )
        repr_str = repr(session)
        
        assert "rounds=0/10" in repr_str
        assert "best_score=0.000" in repr_str
        assert "status=active" in repr_str

    def test_repr_shows_best_not_latest(self):
        """Test repr shows best score, not latest."""
        session = BaseSession(session_id="test-005", domain="test")
        session.record_round(score=0.70, feedback=["Good"])
        session.record_round(score=0.90, feedback=["Excellent"])
        session.record_round(score=0.75, feedback=["Degraded"])
        
        repr_str = repr(session)
        
        # Best is 0.90, not latest (0.75)
        assert "best_score=0.900" in repr_str


class TestOptimizationCycleMetricsRepr:
    """Test __repr__ for OptimizationCycleMetrics dataclass."""

    def test_repr_basic(self):
        """Test repr shows cycle ID, duration, and status."""
        metrics = OptimizationCycleMetrics(
            cycle_id="cycle-001",
            start_time=datetime.now(),
            llm_calls=10,
            llm_cache_hits=7,
            llm_cache_misses=3,
            validation_count=5,
            success=True,
        )
        metrics.finalize()
        
        repr_str = repr(metrics)
        
        assert "OptimizationCycleMetrics" in repr_str
        assert "id='cycle-001'" in repr_str
        assert "duration=" in repr_str
        assert "llm_calls=10" in repr_str
        assert "validations=5" in repr_str
        assert "status=success" in repr_str

    def test_repr_shows_cache_rate(self):
        """Test repr includes LLM cache hit rate."""
        metrics = OptimizationCycleMetrics(
            cycle_id="cycle-002",
            start_time=datetime.now(),
            llm_calls=20,
            llm_cache_hits=15,
            llm_cache_misses=5,
            success=True,
        )
        metrics.finalize()
        
        repr_str = repr(metrics)
        
        # 15/20 = 75% cache rate
        assert "cache_rate=75.0%" in repr_str

    def test_repr_failed_status(self):
        """Test repr shows failed status."""
        metrics = OptimizationCycleMetrics(
            cycle_id="cycle-003",
            start_time=datetime.now(),
            llm_calls=5,
            success=False,
            error="Validation failed",
        )
        metrics.finalize()
        
        repr_str = repr(metrics)
        
        assert "status=failed" in repr_str

    def test_repr_zero_llm_calls(self):
        """Test repr handles zero LLM calls gracefully (no division by zero)."""
        metrics = OptimizationCycleMetrics(
            cycle_id="cycle-004",
            start_time=datetime.now(),
            llm_calls=0,
            success=True,
        )
        metrics.finalize()
        
        repr_str = repr(metrics)
        
        # Should not crash
        assert "llm_calls=0" in repr_str
        assert "cache_rate=" in repr_str

    def test_repr_concise_format(self):
        """Test repr is reasonably concise (< 200 chars)."""
        metrics = OptimizationCycleMetrics(
            cycle_id="c-005",
            start_time=datetime.now(),
            llm_calls=100,
            llm_cache_hits=80,
            validation_count=10,
            success=True,
        )
        metrics.finalize()
        
        repr_str = repr(metrics)
        
        # Should be concise enough for terminal display
        assert len(repr_str) < 200


class TestMediatorStateRepr:
    """Test __repr__ for MediatorState dataclass."""

    def test_repr_basic(self):
        """Test repr shows mediator-specific fields."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import MediatorState
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
        
        state = MediatorState(
            session_id="mediator-001",
            domain="graphrag",
            max_rounds=10,
        )
        
        # Add some scores
        state.add_round(
            ontology={"entities": [], "relationships": []},
            score=CriticScore(
                completeness=0.6,
                consistency=0.65,
                clarity=0.7,
                granularity=0.6,
                domain_alignment=0.65,
            ),
            refinement_action="Initial extraction",
        )
        state.add_round(
            ontology={"entities": ["Entity1"], "relationships": []},
            score=CriticScore(
                completeness=0.75,
                consistency=0.72,
                clarity=0.8,
                granularity=0.75,
                domain_alignment=0.78,
            ),
            refinement_action="Add entities",
        )
        
        repr_str = repr(state)
        
        assert "MediatorState" in repr_str
        assert "id='mediator-001'" in repr_str
        assert "rounds=2/10" in repr_str
        # Overall is a computed property
        assert "latest_score=" in repr_str

    def test_repr_shows_trend(self):
        """Test repr includes score trend."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import MediatorState
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
        
        state = MediatorState(session_id="mediator-002", max_rounds=5)
        
        state.add_round(
            ontology={},
            score=CriticScore(
                completeness=0.5,
                consistency=0.5,
                clarity=0.5,
                granularity=0.5,
                domain_alignment=0.5,
            ),
            refinement_action="Start",
        )
        state.add_round(
            ontology={},
            score=CriticScore(
                completeness=0.6,
                consistency=0.6,
                clarity=0.6,
                granularity=0.6,
                domain_alignment=0.6,
            ),
            refinement_action="Improve",
        )
        
        repr_str = repr(state)
        
        assert "trend=improving" in repr_str

    def test_repr_no_scores(self):
        """Test repr handles state with no scores."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import MediatorState
        
        state = MediatorState(session_id="mediator-003")
        repr_str = repr(state)
        
        assert "MediatorState" in repr_str
        assert "rounds=0/10" in repr_str
        assert "latest_score=0.000" in repr_str
        assert "trend=insufficient_data" in repr_str


class TestReprGeneralProperties:
    """Test general properties that all __repr__ methods should have."""

    def test_all_repr_return_strings(self):
        """Test all __repr__ methods return strings."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import MediatorState
        
        objects = [
            RoundRecord(round_number=1, score=0.5, duration_ms=100.0),
            BaseSession(session_id="s-001", domain="test"),
            OptimizationCycleMetrics(cycle_id="c-001", start_time=datetime.now()),
            MediatorState(session_id="m-001"),
        ]
        
        for obj in objects:
            repr_str = repr(obj)
            assert isinstance(repr_str, str)
            assert len(repr_str) > 0

    def test_all_repr_include_class_name(self):
        """Test all __repr__ methods include class name."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import MediatorState
        
        test_cases = [
            (RoundRecord(round_number=1, score=0.5, duration_ms=100.0), "RoundRecord"),
            (BaseSession(session_id="s-001", domain="test"), "BaseSession"),
            (OptimizationCycleMetrics(cycle_id="c-001", start_time=datetime.now()), "OptimizationCycleMetrics"),
            (MediatorState(session_id="m-001"), "MediatorState"),
        ]
        
        for obj, expected_name in test_cases:
            repr_str = repr(obj)
            assert expected_name in repr_str

    def test_all_repr_are_concise(self):
        """Test all __repr__ methods produce reasonably concise output."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import MediatorState
        
        objects = [
            RoundRecord(round_number=1, score=0.5, feedback=["A" * 100], duration_ms=100.0),
            BaseSession(session_id="very-long-session-id-" + "x" * 50, domain="test"),
            OptimizationCycleMetrics(cycle_id="c-001", start_time=datetime.now()),
            MediatorState(session_id="m-001"),
        ]
        
        for obj in objects:
            repr_str = repr(obj)
            # Should be displayable in a terminal (< 300 chars)
            assert len(repr_str) < 300
