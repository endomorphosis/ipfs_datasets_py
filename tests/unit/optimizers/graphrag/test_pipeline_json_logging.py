"""Tests for structured JSON logging in GraphRAG pipeline.

Tests verify that JSON logs are properly formatted, contain required metadata,
and capture all important pipeline lifecycle events.
"""

import json
import logging
import pytest
from io import StringIO

from ipfs_datasets_py.optimizers.graphrag.pipeline_json_logger import (
    PipelineJSONLogger,
    PipelineStage,
    LogContext,
    start_pipeline_run,
)


@pytest.fixture
def log_capture():
    """Capture logs to a string buffer."""
    handler = logging.StreamHandler(StringIO())
    handler.setFormatter(logging.Formatter('%(message)s'))
    return handler


@pytest.fixture
def logger_with_capture(log_capture):
    """Create a logger with captured output."""
    py_logger = logging.getLogger(__name__)
    py_logger.addHandler(log_capture)
    py_logger.setLevel(logging.DEBUG)
    json_logger = PipelineJSONLogger("test", logger=py_logger)
    return json_logger, log_capture


class TestLogContext:
    """Test LogContext data structure."""
    
    def test_context_initialization(self):
        """LogContext should initialize with required fields."""
        ctx = LogContext(
            run_id="run_123",
            domain="legal",
            data_source="test",
        )
        
        assert ctx.run_id == "run_123"
        assert ctx.domain == "legal"
        assert ctx.data_source == "test"
        assert len(ctx.stages) == 0
        assert len(ctx.stage_timings) == 0
    
    def test_elapsed_time_tracking(self):
        """LogContext should track elapsed time."""
        ctx = LogContext(
            run_id="run_123",
            domain="legal",
            data_source="test",
        )
        
        elapsed = ctx.elapsed_ms()
        assert elapsed >= 0
        assert isinstance(elapsed, float)
    
    def test_stage_timing_tracking(self):
        """LogContext should track timing for each stage."""
        import time
        
        ctx = LogContext(
            run_id="run_123",
            domain="legal",
            data_source="test",
        )
        
        ctx.mark_stage_start("extraction")
        time.sleep(0.01)  # Sleep 10ms
        ctx.mark_stage_end("extraction")
        
        assert "extraction" in ctx.stage_timings
        assert ctx.stage_timings["extraction"] >= 10  # At least 10ms
    
    def test_context_to_dict(self):
        """LogContext should serialize to dict."""
        ctx = LogContext(
            run_id="run_123",
            domain="legal",
            data_source="test",
            refine=True,
        )
        
        d = ctx.to_dict()
        
        assert d["run_id"] == "run_123"
        assert d["domain"] == "legal"
        assert d["data_source"] == "test"
        assert d["refine"] is True
        assert "total_elapsed_ms" in d


class TestPipelineJSONLogger:
    """Test PipelineJSONLogger functionality."""
    
    def test_logger_initialization(self):
        """Logger should initialize with domain."""
        logger = PipelineJSONLogger(domain="legal")
        assert logger.domain == "legal"
        assert logger.include_schema is True
        assert logger.include_timestamp is True
    
    def test_start_run_creates_context(self):
        """start_run should create a LogContext."""
        logger = PipelineJSONLogger(domain="legal")
        ctx = logger.start_run(
            run_id="run_123",
            data_source="test",
            data_type="text",
            refine=True,
        )
        
        assert ctx.run_id == "run_123"
        assert ctx.domain == "legal"
        assert ctx.data_source == "test"
        assert logger._context == ctx

    @pytest.mark.parametrize(
        "kwargs,expected_exception",
        [
            ({"run_id": 123, "data_source": "test"}, TypeError),
            ({"run_id": "   ", "data_source": "test"}, ValueError),
            ({"run_id": "run_123", "data_source": None}, TypeError),
            ({"run_id": "run_123", "data_source": ""}, ValueError),
            ({"run_id": "run_123", "data_source": "test", "data_type": 7}, TypeError),
            ({"run_id": "run_123", "data_source": "test", "data_type": "   "}, ValueError),
            ({"run_id": "run_123", "data_source": "test", "refine": "yes"}, TypeError),
            ({"run_id": "run_123", "data_source": "test", "max_workers": 1.5}, TypeError),
            ({"run_id": "run_123", "data_source": "test", "max_workers": 0}, ValueError),
        ],
    )
    def test_start_run_rejects_invalid_inputs(self, kwargs, expected_exception):
        """start_run should enforce basic type and value contracts."""
        logger = PipelineJSONLogger(domain="legal")

        with pytest.raises(expected_exception):
            logger.start_run(**kwargs)
    
    def test_end_run_clears_context(self):
        """end_run should clear the current context."""
        logger = PipelineJSONLogger(domain="legal")
        logger.start_run("run_123", "test")
        logger.end_run(success=True)
        
        assert logger._context is None
    
    def test_extraction_logging(self, logger_with_capture):
        """Logger should capture extraction lifecycle events."""
        json_logger, log_capture = logger_with_capture
        json_logger.start_run("run_123", "test")
        
        json_logger.log_extraction_started(data_length=1000, strategy="rule_based")
        json_logger.log_extraction_completed(entity_count=10, relationship_count=5)
        
        # Verify logs were captured
        output = log_capture.stream.getvalue()
        lines = output.strip().split('\n')
        
        # Should have at least 3 logs (start_run, extraction_started, extraction_completed)
        assert len(lines) >= 3

    @pytest.mark.parametrize(
        "kwargs,expected_exception",
        [
            ({"data_length": "100", "strategy": "rule_based"}, TypeError),
            ({"data_length": -1, "strategy": "rule_based"}, ValueError),
            ({"data_length": 100, "strategy": 1}, TypeError),
            ({"data_length": 100, "strategy": "   "}, ValueError),
        ],
    )
    def test_extraction_started_rejects_invalid_inputs(self, logger_with_capture, kwargs, expected_exception):
        """log_extraction_started should enforce argument contracts."""
        json_logger, _ = logger_with_capture

        with pytest.raises(expected_exception):
            json_logger.log_extraction_started(**kwargs)

    @pytest.mark.parametrize(
        "kwargs,expected_exception",
        [
            ({"entity_count": "10", "relationship_count": 5}, TypeError),
            ({"entity_count": 10, "relationship_count": -1}, ValueError),
            ({"entity_count": 10, "relationship_count": 5, "entity_types": []}, TypeError),
            ({"entity_count": 10, "relationship_count": 5, "entity_types": {1: 2}}, TypeError),
            ({"entity_count": 10, "relationship_count": 5, "entity_types": {"Person": "2"}}, TypeError),
            ({"entity_count": 10, "relationship_count": 5, "entity_types": {"Person": -2}}, ValueError),
        ],
    )
    def test_extraction_completed_rejects_invalid_inputs(self, logger_with_capture, kwargs, expected_exception):
        """log_extraction_completed should enforce argument contracts."""
        json_logger, _ = logger_with_capture

        with pytest.raises(expected_exception):
            json_logger.log_extraction_completed(**kwargs)
    
    def test_evaluation_logging(self, logger_with_capture):
        """Logger should capture evaluation lifecycle events."""
        json_logger, log_capture = logger_with_capture
        json_logger.start_run("run_123", "test")
        
        json_logger.log_evaluation_started(parallel=True, batch_size=5)
        json_logger.log_evaluation_completed(
            score=0.85,
            dimensions={
                "completeness": 0.8,
                "consistency": 0.9,
            },
            cache_hit=True,
            cache_size=100,
        )
        
        output = log_capture.stream.getvalue()
        lines = output.strip().split('\n')
        
        # Find evaluation_completed log and verify it contains expected fields
        for line in lines:
            if "evaluation.completed" in line:
                log_obj = json.loads(line)
                assert log_obj["event"] == "evaluation.completed"
                assert log_obj["score"] == 0.85
                assert log_obj["cache_hit"] is True
                break
        else:
            pytest.fail("evaluation.completed event not found")

    @pytest.mark.parametrize(
        "kwargs,expected_exception",
        [
            ({"parallel": "yes", "batch_size": 1}, TypeError),
            ({"parallel": False, "batch_size": 0}, ValueError),
            ({"parallel": False, "batch_size": 1.5}, TypeError),
        ],
    )
    def test_evaluation_started_rejects_invalid_inputs(self, logger_with_capture, kwargs, expected_exception):
        """log_evaluation_started should enforce argument contracts."""
        json_logger, _ = logger_with_capture

        with pytest.raises(expected_exception):
            json_logger.log_evaluation_started(**kwargs)

    @pytest.mark.parametrize(
        "kwargs,expected_exception",
        [
            ({"score": "0.9", "cache_hit": False, "cache_size": 0}, TypeError),
            ({"score": 0.9, "dimensions": [], "cache_hit": False, "cache_size": 0}, TypeError),
            ({"score": 0.9, "dimensions": {1: 0.2}, "cache_hit": False, "cache_size": 0}, TypeError),
            ({"score": 0.9, "dimensions": {"clarity": True}, "cache_hit": False, "cache_size": 0}, TypeError),
            ({"score": 0.9, "cache_hit": "yes", "cache_size": 0}, TypeError),
            ({"score": 0.9, "cache_hit": False, "cache_size": -1}, ValueError),
        ],
    )
    def test_evaluation_completed_rejects_invalid_inputs(self, logger_with_capture, kwargs, expected_exception):
        """log_evaluation_completed should enforce argument contracts."""
        json_logger, _ = logger_with_capture

        with pytest.raises(expected_exception):
            json_logger.log_evaluation_completed(**kwargs)
    
    def test_refinement_logging(self, logger_with_capture):
        """Logger should capture refinement lifecycle events."""
        json_logger, log_capture = logger_with_capture
        json_logger.start_run("run_123", "test")
        
        json_logger.log_refinement_started(mode="llm", max_rounds=3, current_score=0.7)
        
        json_logger.log_refinement_round(
            round_num=1,
            max_rounds=3,
            score_before=0.7,
            score_after=0.75,
            actions_applied=["add_entity", "fix_relationship"],
        )
        
        json_logger.log_refinement_completed(
            final_score=0.85,
            initial_score=0.7,
            rounds_completed=2,
            total_actions=5,
        )
        
        output = log_capture.stream.getvalue()
        lines = output.strip().split('\n')
        
        # Verify all refinement events are present
        events = [json.loads(line).get("event") for line in lines if line]
        assert "refinement.started" in events
        assert "refinement.round.completed" in events
        assert "refinement.completed" in events

    @pytest.mark.parametrize(
        "kwargs,expected_exception",
        [
            ({"mode": 1, "max_rounds": 1, "current_score": 0.1}, TypeError),
            ({"mode": " ", "max_rounds": 1, "current_score": 0.1}, ValueError),
            ({"mode": "rule_based", "max_rounds": 0, "current_score": 0.1}, ValueError),
            ({"mode": "rule_based", "max_rounds": 2, "current_score": True}, TypeError),
        ],
    )
    def test_refinement_started_rejects_invalid_inputs(self, logger_with_capture, kwargs, expected_exception):
        """log_refinement_started should enforce argument contracts."""
        json_logger, _ = logger_with_capture

        with pytest.raises(expected_exception):
            json_logger.log_refinement_started(**kwargs)

    @pytest.mark.parametrize(
        "kwargs,expected_exception",
        [
            ({"round_num": "1", "max_rounds": 3, "score_before": 0.1, "score_after": 0.2, "actions_applied": []}, TypeError),
            ({"round_num": 0, "max_rounds": 3, "score_before": 0.1, "score_after": 0.2, "actions_applied": []}, ValueError),
            ({"round_num": 4, "max_rounds": 3, "score_before": 0.1, "score_after": 0.2, "actions_applied": []}, ValueError),
            ({"round_num": 1, "max_rounds": 0, "score_before": 0.1, "score_after": 0.2, "actions_applied": []}, ValueError),
            ({"round_num": 1, "max_rounds": 3, "score_before": "0.1", "score_after": 0.2, "actions_applied": []}, TypeError),
            ({"round_num": 1, "max_rounds": 3, "score_before": 0.1, "score_after": True, "actions_applied": []}, TypeError),
            ({"round_num": 1, "max_rounds": 3, "score_before": 0.1, "score_after": 0.2, "actions_applied": "fix"}, TypeError),
            ({"round_num": 1, "max_rounds": 3, "score_before": 0.1, "score_after": 0.2, "actions_applied": ["fix", 2]}, TypeError),
        ],
    )
    def test_refinement_round_rejects_invalid_inputs(self, logger_with_capture, kwargs, expected_exception):
        """log_refinement_round should enforce argument contracts."""
        json_logger, _ = logger_with_capture

        with pytest.raises(expected_exception):
            json_logger.log_refinement_round(**kwargs)

    @pytest.mark.parametrize(
        "kwargs,expected_exception",
        [
            ({"final_score": "0.9", "initial_score": 0.1, "rounds_completed": 1, "total_actions": 1}, TypeError),
            ({"final_score": 0.9, "initial_score": False, "rounds_completed": 1, "total_actions": 1}, TypeError),
            ({"final_score": 0.9, "initial_score": 0.1, "rounds_completed": -1, "total_actions": 1}, ValueError),
            ({"final_score": 0.9, "initial_score": 0.1, "rounds_completed": 1, "total_actions": -1}, ValueError),
        ],
    )
    def test_refinement_completed_rejects_invalid_inputs(self, logger_with_capture, kwargs, expected_exception):
        """log_refinement_completed should enforce argument contracts."""
        json_logger, _ = logger_with_capture

        with pytest.raises(expected_exception):
            json_logger.log_refinement_completed(**kwargs)
    
    def test_error_logging(self, logger_with_capture):
        """Logger should capture errors with context."""
        json_logger, log_capture = logger_with_capture
        json_logger.start_run("run_123", "test")
        
        json_logger.log_error(
            stage="extraction",
            error_type="ValueError",
            error_message="Invalid entity format",
            traceback="...",
        )
        
        output = log_capture.stream.getvalue()
        lines = output.strip().split('\n')
        
        # Find error log and verify it
        for line in lines:
            if "pipeline.error" in line:
                log_obj = json.loads(line)
                assert log_obj["event"] == "pipeline.error"
                assert log_obj["stage"] == "extraction"
                assert log_obj["error_type"] == "ValueError"
                break
        else:
            pytest.fail("error event not found")
    
    def test_cache_statistics_logging(self, logger_with_capture):
        """Logger should capture cache statistics."""
        json_logger, log_capture = logger_with_capture
        json_logger.start_run("run_123", "test")
        
        json_logger.log_cache_statistics(
            cache_type="shared_eval",
            size=100,
            hit_count=80,
            miss_count=20,
            eviction_count=5,
        )
        
        output = log_capture.stream.getvalue()
        lines = output.strip().split('\n')
        
        # Find cache stats log and verify hit rate calculation
        for line in lines:
            if "cache.statistics" in line:
                log_obj = json.loads(line)
                assert log_obj["cache_type"] == "shared_eval"
                assert log_obj["size"] == 100
                assert log_obj["hit_rate"] == 0.8  # 80 hits out of 100 total
                break
        else:
            pytest.fail("cache.statistics event not found")

    @pytest.mark.parametrize(
        "kwargs,expected_exception",
        [
            ({"cache_type": 1, "size": 1, "hit_count": 1, "miss_count": 0}, TypeError),
            ({"cache_type": " ", "size": 1, "hit_count": 1, "miss_count": 0}, ValueError),
            ({"cache_type": "shared", "size": -1, "hit_count": 1, "miss_count": 0}, ValueError),
            ({"cache_type": "shared", "size": 1.5, "hit_count": 1, "miss_count": 0}, TypeError),
            ({"cache_type": "shared", "size": 1, "hit_count": -1, "miss_count": 0}, ValueError),
            ({"cache_type": "shared", "size": 1, "hit_count": 1, "miss_count": -1}, ValueError),
            ({"cache_type": "shared", "size": 1, "hit_count": 1, "miss_count": 0, "eviction_count": -1}, ValueError),
        ],
    )
    def test_cache_statistics_rejects_invalid_inputs(self, logger_with_capture, kwargs, expected_exception):
        """log_cache_statistics should enforce argument contracts."""
        json_logger, _ = logger_with_capture

        with pytest.raises(expected_exception):
            json_logger.log_cache_statistics(**kwargs)
    
    def test_batch_progress_logging(self, logger_with_capture):
        """Logger should capture batch progress."""
        json_logger, log_capture = logger_with_capture
        json_logger.start_run("run_123", "test")
        
        json_logger.log_batch_progress(
            batch_index=2,
            batch_total=10,
            items_completed=5,
            items_failed=0,
            current_score=0.75,
        )
        
        output = log_capture.stream.getvalue()
        lines = output.strip().split('\n')
        
        # Find batch progress log and verify progress calculation
        for line in lines:
            if "batch.progress" in line:
                log_obj = json.loads(line)
                assert log_obj["batch"] == 2
                assert log_obj["total_batches"] == 10
                assert log_obj["progress_percent"] == 20.0  # 2/10 * 100
                break
        else:
            pytest.fail("batch.progress event not found")

    @pytest.mark.parametrize(
        "kwargs,expected_exception",
        [
            ({"batch_index": -1, "batch_total": 10, "items_completed": 1, "items_failed": 0, "current_score": 0.1}, ValueError),
            ({"batch_index": 11, "batch_total": 10, "items_completed": 1, "items_failed": 0, "current_score": 0.1}, ValueError),
            ({"batch_index": 0, "batch_total": 0, "items_completed": 1, "items_failed": 0, "current_score": 0.1}, ValueError),
            ({"batch_index": "0", "batch_total": 10, "items_completed": 1, "items_failed": 0, "current_score": 0.1}, TypeError),
            ({"batch_index": 0, "batch_total": 10, "items_completed": -1, "items_failed": 0, "current_score": 0.1}, ValueError),
            ({"batch_index": 0, "batch_total": 10, "items_completed": 1, "items_failed": -1, "current_score": 0.1}, ValueError),
            ({"batch_index": 0, "batch_total": 10, "items_completed": 1, "items_failed": 0, "current_score": True}, TypeError),
        ],
    )
    def test_batch_progress_rejects_invalid_inputs(self, logger_with_capture, kwargs, expected_exception):
        """log_batch_progress should enforce argument contracts."""
        json_logger, _ = logger_with_capture

        with pytest.raises(expected_exception):
            json_logger.log_batch_progress(**kwargs)
    
    def test_json_schema_inclusion(self, logger_with_capture):
        """All logs should include schema metadata."""
        json_logger, log_capture = logger_with_capture
        json_logger.start_run("run_123", "test")
        json_logger.log_extraction_started(data_length=1000)
        
        output = log_capture.stream.getvalue()
        lines = output.strip().split('\n')
        
        # Verify all logs have schema metadata
        for line in lines:
            if line:
                log_obj = json.loads(line)
                assert "schema" in log_obj
                assert log_obj["schema"] == "ipfs_datasets_py.optimizer_log"
                assert "schema_version" in log_obj
    
    def test_timestamp_inclusion(self, logger_with_capture):
        """All logs should include timestamp."""
        json_logger, log_capture = logger_with_capture
        json_logger.start_run("run_123", "test")
        json_logger.log_evaluation_started()
        
        output = log_capture.stream.getvalue()
        lines = output.strip().split('\n')
        
        # Verify all logs have timestamps
        for line in lines:
            if line:
                log_obj = json.loads(line)
                assert "timestamp" in log_obj

    def test_emit_log_falls_back_on_typed_logger_error(self):
        """_emit_log should fallback to debug on typed logger failures."""
        py_logger = logging.getLogger("test.pipeline_json_logger.typed_error")
        py_logger.setLevel(logging.DEBUG)
        py_logger.log = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("sink error"))  # type: ignore[assignment]

        debug_calls = []
        py_logger.debug = lambda msg: debug_calls.append(msg)  # type: ignore[assignment]

        json_logger = PipelineJSONLogger("test", logger=py_logger)
        json_logger._emit_log("test.event", {"k": "v"})

        assert len(debug_calls) == 1
        assert "JSON logging failed" in debug_calls[0]

    def test_emit_log_does_not_swallow_base_exception(self):
        """_emit_log should not swallow BaseException subclasses."""
        class AbortSignal(BaseException):
            pass

        py_logger = logging.getLogger("test.pipeline_json_logger.abort")
        py_logger.log = lambda *args, **kwargs: (_ for _ in ()).throw(AbortSignal())  # type: ignore[assignment]

        json_logger = PipelineJSONLogger("test", logger=py_logger)

        with pytest.raises(AbortSignal):
            json_logger._emit_log("test.event", {"k": "v"})

    def test_emit_log_redacts_sensitive_key_fields(self, logger_with_capture):
        """_emit_log should redact sensitive key/value pairs."""
        json_logger, log_capture = logger_with_capture
        json_logger._emit_log("test.event", {"api_key": "sk-live-123"})

        output = log_capture.stream.getvalue().strip().split("\n")
        payload = json.loads(output[-1])
        assert payload["api_key"] == "***REDACTED***"

    def test_emit_log_redacts_bearer_token_substrings(self, logger_with_capture):
        """_emit_log should redact bearer token substrings inside strings."""
        json_logger, log_capture = logger_with_capture
        json_logger._emit_log("test.event", {"message": "Authorization: Bearer token1234567890"})

        output = log_capture.stream.getvalue().strip().split("\n")
        payload = json.loads(output[-1])
        assert "token1234567890" not in payload["message"]
        assert "***REDACTED***" in payload["message"]


class TestContextManager:
    """Test context manager for pipeline runs."""
    
    def test_context_manager_success(self, logger_with_capture):
        """Context manager should handle successful run."""
        json_logger, log_capture = logger_with_capture
        
        with start_pipeline_run(json_logger, "run_123", data_source="test"):
            json_logger.log_extraction_started(1000)
            json_logger.log_extraction_completed(10, 5)
        
        output = log_capture.stream.getvalue()
        lines = output.strip().split('\n')
        
        # Should have pipeline.run.started and pipeline.run.completed
        events = [json.loads(line).get("event") for line in lines if line]
        assert "pipeline.run.started" in events
        assert "pipeline.run.completed" in events
    
    def test_context_manager_error_handling(self, logger_with_capture):
        """Context manager should handle errors."""
        json_logger, log_capture = logger_with_capture
        
        with pytest.raises(ValueError):
            with start_pipeline_run(json_logger, "run_123", data_source="test"):
                raise ValueError("Test error")
        
        output = log_capture.stream.getvalue()
        lines = output.strip().split('\n')
        
        # Should have pipeline.run.failed
        events = [json.loads(line).get("event") for line in lines if line]
        assert "pipeline.run.failed" in events

    def test_context_manager_does_not_swallow_base_exception(self, logger_with_capture):
        """Context manager should not swallow BaseException subclasses."""
        class AbortSignal(BaseException):
            pass

        json_logger, _ = logger_with_capture

        with pytest.raises(AbortSignal):
            with start_pipeline_run(json_logger, "run_123", data_source="test"):
                raise AbortSignal()


class TestJSONLogStructure:
    """Test JSON log structure and format."""
    
    def test_log_is_valid_json(self, logger_with_capture):
        """All logs should be valid JSON."""
        json_logger, log_capture = logger_with_capture
        json_logger.start_run("run_123", "test")
        json_logger.log_extraction_started(1000)
        
        output = log_capture.stream.getvalue()
        lines = output.strip().split('\n')
        
        # All non-empty lines should be valid JSON
        for line in lines:
            if line:
                try:
                    json.loads(line)
                except json.JSONDecodeError:
                    pytest.fail(f"Invalid JSON: {line}")
    
    def test_log_contains_domain(self, logger_with_capture):
        """All logs should include domain."""
        json_logger, log_capture = logger_with_capture
        json_logger.start_run("run_123", "test")
        json_logger.log_extraction_started(1000)
        
        output = log_capture.stream.getvalue()
        lines = output.strip().split('\n')
        
        # All logs should have domain
        for line in lines:
            if line:
                log_obj = json.loads(line)
                assert log_obj["domain"] == "test"
                assert log_obj["optimizer_pipeline"] == "graphrag"
    
    def test_log_contains_event_type(self, logger_with_capture):
        """All logs should include event type."""
        json_logger, log_capture = logger_with_capture
        json_logger.start_run("run_123", "test")
        json_logger.log_extraction_started(1000)
        
        output = log_capture.stream.getvalue()
        lines = output.strip().split('\n')
        
        # All logs should have event type
        for line in lines:
            if line:
                log_obj = json.loads(line)
                assert "event" in log_obj
