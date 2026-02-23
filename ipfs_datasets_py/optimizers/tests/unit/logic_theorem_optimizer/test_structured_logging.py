"""Tests for structured JSON logging in logic theorem optimizer."""

from __future__ import annotations

import json
import logging
import pytest
from unittest.mock import Mock, patch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.unified_optimizer import (
    LogicTheoremOptimizer,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_optimizer import (
    LogicOptimizer,
    OptimizationReport,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_extractor import (
    ExtractionMode,
)
from ipfs_datasets_py.optimizers.common.base_optimizer import (
    OptimizerConfig,
    OptimizationContext,
)


class TestLogicTheoremOptimizerStructuredLogging:
    """Tests for LogicTheoremOptimizer.run_session() JSON logging."""
    
    def test_run_session_emits_structured_json_log(self, caplog):
        """LogicTheoremOptimizer.run_session() emits LOGIC_SESSION_RUN JSON log."""
        caplog.set_level(logging.INFO)
        
        optimizer = LogicTheoremOptimizer(
            config=OptimizerConfig(max_rounds=1, target_score=0.5),
            extraction_mode=ExtractionMode.FOL,
            use_provers=['z3'],
        )
        
        context = OptimizationContext(
            session_id="test-session-001",
            input_data="All humans are mortal. Socrates is human.",
            domain="general",
        )
        
        result = optimizer.run_session(
            input_data="All humans are mortal. Socrates is human.",
            context=context,
        )
        
        # Find the LOGIC_SESSION_RUN log
        log_records = [r for r in caplog.records if "LOGIC_SESSION_RUN:" in r.message]
        assert len(log_records) == 1, "Expected exactly one LOGIC_SESSION_RUN log"
        
        log_msg = log_records[0].message
        json_str = log_msg.split("LOGIC_SESSION_RUN: ")[1]
        payload = json.loads(json_str)
        
        # Verify schema metadata
        assert payload["schema"] == "ipfs_datasets_py.optimizer_log"
        assert payload["schema_version"] == 1
        
        # Verify event metadata
        assert payload["event"] == "logic_theorem_optimizer_run_session"
        assert payload["session_id"] == "test-session-001"
        assert payload["domain"] == "general"
        assert payload["extraction_mode"] == "fol"
        assert payload["provers"] == ['z3']
        
        # Verify result metrics
        assert "score" in payload
        assert "valid" in payload
        assert "iterations" in payload
        assert "statement_count" in payload
        assert "duration_ms" in payload
        assert "timestamp" in payload
        
        # Type checks
        assert isinstance(payload["score"], (int, float))
        assert isinstance(payload["valid"], bool)
        assert isinstance(payload["iterations"], int)
        assert isinstance(payload["statement_count"], int)
        assert isinstance(payload["duration_ms"], (int, float))
        assert isinstance(payload["timestamp"], str)
        
    def test_run_session_logging_does_not_crash_on_error(self, caplog):
        """Logging errors are suppressed and logged at debug level."""
        caplog.set_level(logging.DEBUG)
        
        optimizer = LogicTheoremOptimizer(
            config=OptimizerConfig(max_rounds=1),
            extraction_mode=ExtractionMode.FOL,
        )
        
        context = OptimizationContext(
            session_id="test-session-002",
            input_data="Test input",
            domain="general",
        )
        
        # Patch with_schema to fail
        with patch("ipfs_datasets_py.optimizers.logic_theorem_optimizer.unified_optimizer.with_schema", side_effect=RuntimeError("Schema error")):
            result = optimizer.run_session(
                input_data="Test input",
                context=context,
            )
        
        # Optimizer should still return a result
        assert result is not None
        assert "score" in result
        
        # Check for debug log about logging failure
        debug_msgs = [r.message for r in caplog.records if r.levelname == "DEBUG"]
        assert any("Logic session JSON logging failed" in msg for msg in debug_msgs)
    
    def test_run_session_log_includes_statement_count(self, caplog):
        """LOGIC_SESSION_RUN log includes statement_count from extraction."""
        caplog.set_level(logging.INFO)
        
        optimizer = LogicTheoremOptimizer(
            config=OptimizerConfig(max_rounds=1),
            extraction_mode=ExtractionMode.FOL,
        )
        
        context = OptimizationContext(
            session_id="test-session-003",
            input_data="P implies Q. P. Therefore Q.",
            domain="general",
        )
        
        result = optimizer.run_session(
            input_data="P implies Q. P. Therefore Q.",
            context=context,
        )
        
        # Parse the JSON log
        log_records = [r for r in caplog.records if "LOGIC_SESSION_RUN:" in r.message]
        assert len(log_records) == 1
        
        log_msg = log_records[0].message
        json_str = log_msg.split("LOGIC_SESSION_RUN: ")[1]
        payload = json.loads(json_str)
        
        # statement_count should be non-negative
        assert payload["statement_count"] >= 0
        assert isinstance(payload["statement_count"], int)


class TestLogicOptimizerStructuredLogging:
    """Tests for LogicOptimizer.analyze_batch() JSON logging."""
    
    def test_analyze_batch_emits_structured_json_log(self, caplog):
        """LogicOptimizer.analyze_batch() emits LOGIC_BATCH_ANALYSIS JSON log."""
        caplog.set_level(logging.INFO)
        
        optimizer_logic = LogicOptimizer(
            convergence_threshold=0.85,
            min_improvement_rate=0.01,
        )
        
        # Create mock session results
        mock_results = []
        for i in range(3):
            mock_result = Mock()
            mock_result.critic_score = Mock()
            mock_result.critic_score.overall = 0.7 + i * 0.05
            mock_result.critic_score.dimension_scores = []
            mock_result.critic_score.weaknesses = ["weak_completeness"]
            mock_result.success = True
            mock_results.append(mock_result)
        
        report = optimizer_logic.analyze_batch(mock_results)
        
        # Find the LOGIC_BATCH_ANALYSIS log
        log_records = [r for r in caplog.records if "LOGIC_BATCH_ANALYSIS:" in r.message]
        assert len(log_records) == 1, "Expected exactly one LOGIC_BATCH_ANALYSIS log"
        
        log_msg = log_records[0].message
        json_str = log_msg.split("LOGIC_BATCH_ANALYSIS: ")[1]
        payload = json.loads(json_str)
        
        # Verify schema metadata
        assert payload["schema"] == "ipfs_datasets_py.optimizer_log"
        assert payload["schema_version"] == 1
        
        # Verify event metadata
        assert payload["event"] == "logic_optimizer_analyze_batch"
        assert payload["batch_index"] == 1  # First batch
        assert payload["session_count"] == 3
        
        # Verify metrics
        assert "average_score" in payload
        assert "trend" in payload
        assert "convergence_status" in payload
        assert "recommendation_count" in payload
        assert "insight_count" in payload
        assert "dimension_count" in payload
        assert "timestamp" in payload
        
        # Type checks
        assert isinstance(payload["average_score"], (int, float))
        assert isinstance(payload["trend"], str)
        assert isinstance(payload["convergence_status"], str)
        assert isinstance(payload["recommendation_count"], int)
        assert isinstance(payload["insight_count"], int)
        assert isinstance(payload["dimension_count"], int)
        assert isinstance(payload["timestamp"], str)
        
    def test_analyze_batch_logging_does_not_crash_on_error(self, caplog):
        """Logging errors are suppressed and logged at debug level."""
        caplog.set_level(logging.DEBUG)
        
        optimizer_logic = LogicOptimizer()
        
        # Create minimal mock results
        mock_result = Mock()
        mock_result.critic_score = Mock()
        mock_result.critic_score.overall = 0.8
        mock_result.critic_score.dimension_scores = []
        mock_result.critic_score.weaknesses = []
        mock_result.success = True
        
        # Patch with_schema to fail
        with patch("ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_optimizer.with_schema", side_effect=RuntimeError("Schema error")):
            report = optimizer_logic.analyze_batch([mock_result])
        
        # Optimizer should still return a report
        assert report is not None
        assert report.average_score > 0
        
        # Check for debug log about logging failure
        debug_msgs = [r.message for r in caplog.records if r.levelname == "DEBUG"]
        assert any("Logic batch analysis JSON logging failed" in msg for msg in debug_msgs)
    
    def test_analyze_batch_empty_results_no_log_for_insufficient_data(self, caplog):
        """Empty results return early without emitting JSON log."""
        caplog.set_level(logging.INFO)
        
        optimizer_logic = LogicOptimizer()
        report = optimizer_logic.analyze_batch([])
        
        # No LOGIC_BATCH_ANALYSIS log for empty results
        log_records = [r for r in caplog.records if "LOGIC_BATCH_ANALYSIS:" in r.message]
        assert len(log_records) == 0
        
        # But report should still be returned
        assert report.trend == "insufficient_data"
    
    def test_analyze_batch_increments_batch_index(self, caplog):
        """analyze_batch increments batch_index on subsequent calls."""
        caplog.set_level(logging.INFO)
        
        optimizer_logic = LogicOptimizer()
        
        # Create mock results
        mock_result = Mock()
        mock_result.critic_score = Mock()
        mock_result.critic_score.overall = 0.75
        mock_result.critic_score.dimension_scores = []
        mock_result.critic_score.weaknesses = []
        mock_result.success = True
        
        # Analyze first batch
        optimizer_logic.analyze_batch([mock_result])
        
        # Analyze second batch
        caplog.clear()
        optimizer_logic.analyze_batch([mock_result])
        
        # Parse the second batch log
        log_records = [r for r in caplog.records if "LOGIC_BATCH_ANALYSIS:" in r.message]
        assert len(log_records) == 1
        
        log_msg = log_records[0].message
        json_str = log_msg.split("LOGIC_BATCH_ANALYSIS: ")[1]
        payload = json.loads(json_str)
        
        # batch_index should be 2 for the second batch
        assert payload["batch_index"] == 2


class TestStructuredLoggingSchema:
    """Tests for structured logging schema consistency."""
    
    def test_schema_version_is_consistent(self, caplog):
        """All structured logs use the same schema and version."""
        caplog.set_level(logging.INFO)
        
        # Test LogicTheoremOptimizer
        optimizer = LogicTheoremOptimizer(
            config=OptimizerConfig(max_rounds=1),
            extraction_mode=ExtractionMode.FOL,
        )
        
        context = OptimizationContext(
            session_id="schema-test-001",
            input_data="Test",
            domain="general",
        )
        
        optimizer.run_session(input_data="Test", context=context)
        
        # Test LogicOptimizer
        optimizer_logic = LogicOptimizer()
        mock_result = Mock()
        mock_result.critic_score = Mock()
        mock_result.critic_score.overall = 0.8
        mock_result.critic_score.dimension_scores = []
        mock_result.critic_score.weaknesses = []
        mock_result.success = True
        optimizer_logic.analyze_batch([mock_result])
        
        # Find all JSON logs
        log_msgs = [r.message for r in caplog.records if ":" in r.message and "{" in r.message]
        
        schemas = set()
        versions = set()
        
        for msg in log_msgs:
            if "LOGIC_SESSION_RUN:" in msg or "LOGIC_BATCH_ANALYSIS:" in msg:
                json_str = msg.split(": ", 1)[1]
                payload = json.loads(json_str)
                schemas.add(payload.get("schema"))
                versions.add(payload.get("schema_version"))
        
        # All logs should use the same schema
        assert len(schemas) == 1
        assert "ipfs_datasets_py.optimizer_log" in schemas
        
        # All logs should use the same version
        assert len(versions) == 1
        assert 1 in versions
