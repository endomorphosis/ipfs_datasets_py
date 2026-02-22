"""
Tests for audit logging infrastructure.

Tests cover:
- Event creation and serialization
- Audit logger initialization
- Event logging for all event types
- JSON export/import
- Summary report generation
- Round-specific queries
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ipfs_datasets_py.optimizers.graphrag.audit_logger import (
    AuditEvent,
    AuditLogger,
    EventType,
    create_audit_logger,
    load_audit_trail,
)


class TestAuditEvent:
    """Tests for AuditEvent dataclass."""
    
    def test_create_event_basic(self):
        """Test creating a basic audit event."""
        event = AuditEvent.create(
            event_type=EventType.STRATEGY_DECISION,
            round_num=1,
            event_data={"action": "merge_duplicates"},
        )
        
        assert event.event_type == EventType.STRATEGY_DECISION
        assert event.round_num == 1
        assert event.event_data == {"action": "merge_duplicates"}
        assert isinstance(event.timestamp, str)
        assert event.timestamp.endswith("Z")  # UTC timezone
        assert event.metadata == {}
    
    def test_create_event_with_metadata(self):
        """Test creating event with metadata."""
        metadata = {"session_id": "test123", "user": "alice"}
        event = AuditEvent.create(
            event_type=EventType.ACTION_APPLY,
            round_num=2,
            event_data={"action_name": "normalize_names"},
            metadata=metadata,
        )
        
        assert event.metadata == metadata
    
    def test_to_dict(self):
        """Test serializing event to dictionary."""
        event = AuditEvent.create(
            event_type=EventType.SCORE_UPDATE,
            round_num=3,
            event_data={"before": 0.5, "after": 0.7},
        )
        
        data = event.to_dict()
        
        assert data["event_type"] == "score_update"
        assert data["round_num"] == 3
        assert data["event_data"] == {"before": 0.5, "after": 0.7}
        assert "timestamp" in data
    
    def test_from_dict(self):
        """Test deserializing event from dictionary."""
        data = {
            "event_type": "strategy_decision",
            "timestamp": "2025-02-20T10:30:00Z",
            "round_num": 1,
            "event_data": {"action": "split_entity"},
            "metadata": {"domain": "legal"},
        }
        
        event = AuditEvent.from_dict(data)
        
        assert event.event_type == EventType.STRATEGY_DECISION
        assert event.timestamp == "2025-02-20T10:30:00Z"
        assert event.round_num == 1
        assert event.event_data == {"action": "split_entity"}
        assert event.metadata == {"domain": "legal"}
    
    def test_round_trip_serialization(self):
        """Test event can be serialized and deserialized."""
        original = AuditEvent.create(
            event_type=EventType.CONVERGENCE_ACHIEVED,
            round_num=5,
            event_data={"final_score": 0.87, "total_rounds": 5},
            metadata={"domain": "medical"},
        )
        
        data = original.to_dict()
        restored = AuditEvent.from_dict(data)
        
        assert restored.event_type == original.event_type
        assert restored.round_num == original.round_num
        assert restored.event_data == original.event_data
        assert restored.metadata == original.metadata


class TestAuditLogger:
    """Tests for AuditLogger class."""
    
    def test_init_memory_only(self):
        """Test initializing logger without file output."""
        logger = AuditLogger(session_id="test123", output_dir=None)
        
        assert logger.session_id == "test123"
        assert logger.output_dir is None
        assert logger.enable_file_logging is False
        assert logger.events == []
    
    def test_init_with_output_dir(self):
        """Test initializing logger with output directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = AuditLogger(session_id="test456", output_dir=tmpdir)
            
            assert logger.session_id == "test456"
            assert logger.output_dir == Path(tmpdir)
            assert logger.enable_file_logging is True
            assert Path(tmpdir).exists()
    
    def test_auto_generate_session_id(self):
        """Test automatic session ID generation."""
        logger = AuditLogger()
        
        assert logger.session_id is not None
        assert len(logger.session_id) > 0
        # Format: YYYYMMDD_HHMMSS_<uuid>
        parts = logger.session_id.split("_")
        assert len(parts) >= 2
    
    def test_log_cycle_start(self):
        """Test logging refinement cycle start."""
        logger = AuditLogger()
        
        context = MagicMock()
        context.data_source = "contract.pdf"
        context.domain = "legal"
        context.extraction_strategy = "hybrid"
        
        logger.log_cycle_start(
            data="contract text",
            context=context,
            max_rounds=10,
            convergence_threshold=0.85,
        )
        
        assert len(logger.events) == 1
        event = logger.events[0]
        assert event.event_type == EventType.REFINEMENT_CYCLE_START
        assert event.round_num == 0
        assert event.event_data["max_rounds"] == 10
        assert event.event_data["convergence_threshold"] == 0.85
        assert event.event_data["domain"] == "legal"
    
    def test_log_refinement_decision(self):
        """Test logging refinement strategy decision."""
        logger = AuditLogger()
        
        ontology = {
            "entities": [{"id": "e1"}, {"id": "e2"}],
            "relationships": [{"id": "r1"}],
        }
        
        score = MagicMock()
        score.overall = 0.65
        score.completeness = 0.70
        score.consistency = 0.60
        score.clarity = 0.65
        
        strategy = {
            "action": "add_missing_properties",
            "priority": "high",
            "rationale": "clarity score low",
            "estimated_impact": 0.12,
            "affected_entity_count": 5,
            "alternative_actions": ["normalize_names"],
        }
        
        context = MagicMock()
        context.domain = "legal"
        
        logger.log_refinement_decision(
            round_num=1,
            ontology=ontology,
            score=score,
            strategy=strategy,
            context=context,
        )
        
        assert len(logger.events) == 1
        event = logger.events[0]
        assert event.event_type == EventType.STRATEGY_DECISION
        assert event.round_num == 1
        assert event.event_data["ontology_stats"]["entity_count"] == 2
        assert event.event_data["ontology_stats"]["relationship_count"] == 1
        assert event.event_data["score"]["overall"] == 0.65
        assert event.event_data["strategy"]["action"] == "add_missing_properties"
        assert event.event_data["strategy"]["priority"] == "high"
    
    def test_log_action_apply(self):
        """Test logging action application."""
        logger = AuditLogger()
        
        ontology_before = {
            "entities": [{"id": "e1"}, {"id": "e2"}],
            "relationships": [{"id": "r1"}],
        }
        
        ontology_after = {
            "entities": [{"id": "e1"}],  # Merged e2 into e1
            "relationships": [{"id": "r1"}],
        }
        
        logger.log_action_apply(
            round_num=1,
            action_name="merge_duplicates",
            ontology_before=ontology_before,
            ontology_after=ontology_after,
            execution_time_ms=125.5,
        )
        
        assert len(logger.events) == 1
        event = logger.events[0]
        assert event.event_type == EventType.ACTION_APPLY
        assert event.event_data["action_name"] == "merge_duplicates"
        assert event.event_data["before"]["entity_count"] == 2
        assert event.event_data["after"]["entity_count"] == 1
        assert event.event_data["delta"]["entities"] == -1
        assert event.event_data["delta"]["relationships"] == 0
        assert event.event_data["execution_time_ms"] == 125.5
    
    def test_log_score_update(self):
        """Test logging score updates."""
        logger = AuditLogger()
        
        score_before = MagicMock()
        score_before.overall = 0.60
        score_before.completeness = 0.65
        score_before.consistency = 0.55
        score_before.clarity = 0.60
        
        score_after = MagicMock()
        score_after.overall = 0.72
        score_after.completeness = 0.75
        score_after.consistency = 0.70
        score_after.clarity = 0.71
        
        logger.log_score_update(
            round_num=1,
            score_before=score_before,
            score_after=score_after,
        )
        
        assert len(logger.events) == 1
        event = logger.events[0]
        assert event.event_type == EventType.SCORE_UPDATE
        assert event.event_data["before"]["overall"] == 0.60
        assert event.event_data["after"]["overall"] == 0.72
        assert event.event_data["delta"]["overall"] == pytest.approx(0.12)
        assert event.event_data["delta"]["completeness"] == pytest.approx(0.10)
    
    def test_log_recommendations(self):
        """Test logging critic recommendations."""
        logger = AuditLogger()
        
        score = MagicMock()
        score.overall = 0.65
        score.recommendations = [
            "Add missing properties to 5 entities",
            "Normalize entity names for consistency",
            "Split overly broad entities into more granular ones",
        ]
        
        logger.log_recommendations(round_num=1, score=score)
        
        assert len(logger.events) == 1
        event = logger.events[0]
        assert event.event_type == EventType.RECOMMENDATION_ISSUED
        assert event.event_data["recommendation_count"] == 3
        assert len(event.event_data["recommendations"]) == 3
        assert "Add missing properties" in event.event_data["recommendations"][0]
    
    def test_log_convergence(self):
        """Test logging convergence achievement."""
        logger = AuditLogger()
        
        final_score = MagicMock()
        final_score.overall = 0.87
        final_score.completeness = 0.88
        final_score.consistency = 0.85
        final_score.clarity = 0.88
        
        logger.log_convergence(
            round_num=5,
            final_score=final_score,
            reason="threshold_reached",
        )
        
        assert len(logger.events) == 1
        event = logger.events[0]
        assert event.event_type == EventType.CONVERGENCE_ACHIEVED
        assert event.event_data["final_score"]["overall"] == 0.87
        assert event.event_data["reason"] == "threshold_reached"
        assert event.event_data["total_rounds"] == 5
    
    def test_log_max_rounds(self):
        """Test logging max rounds reached."""
        logger = AuditLogger()
        
        final_score = MagicMock()
        final_score.overall = 0.80
        final_score.completeness = 0.82
        final_score.consistency = 0.78
        final_score.clarity = 0.79
        
        logger.log_max_rounds(round_num=10, final_score=final_score)
        
        assert len(logger.events) == 1
        event = logger.events[0]
        assert event.event_type == EventType.MAX_ROUNDS_REACHED
        assert event.event_data["final_score"]["overall"] == 0.80
        assert event.event_data["total_rounds"] == 10
    
    def test_log_error(self):
        """Test logging errors."""
        logger = AuditLogger()
        
        logger.log_error(
            round_num=3,
            error_type="ActionExecutionError",
            error_message="Failed to merge entities: duplicate IDs",
            context={"entity_ids": ["e1", "e1"]},
        )
        
        assert len(logger.events) == 1
        event = logger.events[0]
        assert event.event_type == EventType.ERROR_OCCURRED
        assert event.event_data["error_type"] == "ActionExecutionError"
        assert "duplicate IDs" in event.event_data["error_message"]
        assert event.event_data["context"]["entity_ids"] == ["e1", "e1"]
    
    def test_export_json_pretty(self):
        """Test exporting audit trail to pretty JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = AuditLogger()
            
            # Add some events
            logger.log_error(1, "TestError", "test message")
            logger.log_error(2, "TestError2", "test message 2")
            
            output_file = Path(tmpdir) / "audit.json"
            logger.export_json(output_file, pretty=True)
            
            assert output_file.exists()
            
            with open(output_file, "r") as f:
                data = json.load(f)
            
            assert data["session_id"] == logger.session_id
            assert data["event_count"] == 2
            assert len(data["events"]) == 2
    
    def test_export_json_compact(self):
        """Test exporting audit trail to compact JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = AuditLogger()
            logger.log_error(1, "TestError", "test")
            
            output_file = Path(tmpdir) / "audit.json"
            logger.export_json(output_file, pretty=False)
            
            with open(output_file, "r") as f:
                content = f.read()
            
            # Compact JSON should not have newlines (except trailing)
            assert content.count("\n") <= 1
    
    def test_get_round_summary(self):
        """Test getting summary for specific round."""
        logger = AuditLogger()
        
        # Round 1 events
        logger.log_error(1, "Error1", "msg1")
        logger.log_error(1, "Error2", "msg2")
        
        # Round 2 events
        logger.log_error(2, "Error3", "msg3")
        
        summary = logger.get_round_summary(1)
        
        assert summary["round_num"] == 1
        assert summary["event_count"] == 2
        assert len(summary["events"]) == 2
    
    def test_get_score_evolution(self):
        """Test getting score evolution across rounds."""
        logger = AuditLogger()
        
        score1 = MagicMock()
        score1.overall = 0.60
        score1.completeness = 0.65
        score1.consistency = 0.55
        score1.clarity = 0.60
        
        score2 = MagicMock()
        score2.overall = 0.70
        score2.completeness = 0.72
        score2.consistency = 0.68
        score2.clarity = 0.70
        
        score3 = MagicMock()
        score3.overall = 0.80
        score3.completeness = 0.82
        score3.consistency = 0.78
        score3.clarity = 0.80
        
        logger.log_score_update(1, score1, score2)
        logger.log_score_update(2, score2, score3)
        
        evolution = logger.get_score_evolution()
        
        assert len(evolution) == 2
        assert evolution[0]["round"] == 1
        assert evolution[0]["score"]["overall"] == 0.70
        assert evolution[1]["round"] == 2
        assert evolution[1]["score"]["overall"] == 0.80
    
    def test_get_action_history(self):
        """Test getting action history."""
        logger = AuditLogger()
        
        ont = {"entities": [], "relationships": []}
        
        logger.log_action_apply(1, "merge_duplicates", ont, ont, 100.0)
        logger.log_action_apply(2, "normalize_names", ont, ont, 150.0)
        logger.log_action_apply(3, "add_missing_properties", ont, ont, 200.0)
        
        history = logger.get_action_history()
        
        assert len(history) == 3
        assert history[0]["action"] == "merge_duplicates"
        assert history[1]["action"] == "normalize_names"
        assert history[2]["action"] == "add_missing_properties"
        assert history[0]["execution_time_ms"] == 100.0
    
    def test_generate_summary_report(self):
        """Test generating human-readable summary report."""
        logger = AuditLogger()
        
        # Add various events
        context = MagicMock()
        context.data_source = "test.txt"
        context.domain = "legal"
        context.extraction_strategy = "hybrid"
        
        logger.log_cycle_start("data", context, 10, 0.85)
        
        ont = {"entities": [{"id": "e1"}], "relationships": []}
        score = MagicMock()
        score.overall = 0.70
        score.completeness = 0.70
        score.consistency = 0.70
        score.clarity = 0.70
        
        logger.log_action_apply(1, "merge_duplicates", ont, ont)
        logger.log_score_update(1, score, score)
        logger.log_convergence(1, score)
        
        report = logger.generate_summary_report()
        
        assert "AUDIT SUMMARY" in report
        assert logger.session_id in report
        assert "Total Events:" in report
        assert "Rounds:" in report
        assert "✅ CONVERGED" in report
    
    def test_file_logging_enabled(self):
        """Test that events are written to file when enabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = AuditLogger(
                session_id="test789",
                output_dir=tmpdir,
                enable_file_logging=True,
            )
            
            logger.log_error(1, "TestError", "test message")
            
            # Check JSONL file exists and contains event
            log_file = Path(tmpdir) / "audit_test789.jsonl"
            assert log_file.exists()
            
            with open(log_file, "r") as f:
                lines = f.readlines()
            
            assert len(lines) == 1
            event_data = json.loads(lines[0])
            assert event_data["event_type"] == "error_occurred"


class TestConvenienceFunctions:
    """Tests for convenience functions."""
    
    def test_create_audit_logger(self):
        """Test create_audit_logger factory function."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = create_audit_logger(output_dir=tmpdir, session_id="custom123")
            
            assert logger.session_id == "custom123"
            assert logger.output_dir == Path(tmpdir)
            assert logger.enable_file_logging is True
    
    def test_load_audit_trail(self):
        """Test loading audit trail from JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create and export logger
            logger = AuditLogger()
            logger.log_error(1, "Error1", "message1")
            logger.log_error(2, "Error2", "message2")
            
            output_file = Path(tmpdir) / "audit.json"
            logger.export_json(output_file)
            
            # Load trail
            events = load_audit_trail(output_file)
            
            assert len(events) == 2
            assert events[0].event_type == EventType.ERROR_OCCURRED
            assert events[1].event_type == EventType.ERROR_OCCURRED
            assert events[0].round_num == 1
            assert events[1].round_num == 2


class TestAuditLoggerIntegration:
    """Integration tests simulating full refinement cycles."""
    
    def test_full_refinement_cycle_converged(self):
        """Test full refinement cycle that converges."""
        logger = AuditLogger()
        
        # Start cycle
        context = MagicMock()
        context.data_source = "contract.pdf"
        context.domain = "legal"
        context.extraction_strategy = "hybrid"
        
        logger.log_cycle_start("data", context, max_rounds=10, convergence_threshold=0.85)
        
        # Round 1
        ont = {"entities": [{"id": "e1"}, {"id": "e2"}], "relationships": []}
        
        score1 = MagicMock()
        score1.overall = 0.60
        score1.completeness = 0.60
        score1.consistency = 0.60
        score1.clarity = 0.60
        score1.recommendations = ["Add properties"]
        
        strategy1 = {
            "action": "add_missing_properties",
            "priority": "high",
            "rationale": "Low clarity",
             "estimated_impact": 0.15,
            "affected_entity_count": 5,
            "alternative_actions": [],
        }
        
        logger.log_refinement_decision(1, ont, score1, strategy1, context)
        logger.log_recommendations(1, score1)
        logger.log_action_apply(1, "add_missing_properties", ont, ont, 100.0)
        
        score2 = MagicMock()
        score2.overall = 0.75
        score2.completeness = 0.75
        score2.consistency = 0.75
        score2.clarity = 0.75
        
        logger.log_score_update(1, score1, score2)
        
        # Round 2 - convergence
        score3 = MagicMock()
        score3.overall = 0.87
        score3.completeness = 0.87
        score3.consistency = 0.87
        score3.clarity = 0.87
        
        logger.log_convergence(2, score3, "threshold_reached")
        
        # Verify audit trail
        # 1. cycle_start, 2. decision_r1, 3. recommendations_r1, 4. action_r1, 5. score_update_r1, 6. convergence
        assert len(logger.events) == 6
        
        # Verify summary
        report = logger.generate_summary_report()
        assert "✅ CONVERGED" in report
        assert "Rounds: 2" in report
        
        # Verify score evolution
        evolution = logger.get_score_evolution()
        assert len(evolution) == 1
        assert evolution[0]["score"]["overall"] == 0.75
    
    def test_full_refinement_cycle_max_rounds(self):
        """Test full refinement cycle hitting max rounds."""
        logger = AuditLogger()
        
        context = MagicMock()
        context.data_source = "test.txt"
        context.domain = "medical"
        context.extraction_strategy = "llm"
        
        logger.log_cycle_start("data", context, 5, 0.85)
        
        # Simulate 5 rounds without convergence
        ont = {"entities": [], "relationships": []}
        for round_num in range(1, 6):
            score = MagicMock()
            score.overall = 0.60 + (round_num * 0.03)
            score.completeness = 0.60
            score.consistency = 0.60
            score.clarity = 0.60
            
            logger.log_action_apply(round_num, f"action_{round_num}", ont, ont)
            
            if round_num < 5:
                score_after = MagicMock()
                score_after.overall = 0.60 + ((round_num + 1) * 0.03)
                score_after.completeness = 0.60
                score_after.consistency = 0.60
                score_after.clarity = 0.60
                logger.log_score_update(round_num, score, score_after)
        
        # Max rounds reached
        final_score = MagicMock()
        final_score.overall = 0.75
        final_score.completeness = 0.75
        final_score.consistency = 0.75
        final_score.clarity = 0.75
        
        logger.log_max_rounds(5, final_score)
        
        # Verify
        report = logger.generate_summary_report()
        assert "⚠️  MAX ROUNDS REACHED" in report
        assert "Rounds: 5" in report


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
