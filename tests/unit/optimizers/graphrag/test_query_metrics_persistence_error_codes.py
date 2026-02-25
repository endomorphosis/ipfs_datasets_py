from __future__ import annotations

import json
import time
from unittest.mock import Mock


def test_persist_metrics_fallback_file_contains_structured_error_code(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.graphrag.query_metrics import (
        QUERY_METRICS_PERSIST_SERIALIZATION_ERROR,
        QueryMetricsCollector,
    )

    collector = QueryMetricsCollector(metrics_dir=str(tmp_path), track_resources=False)

    def _raise_serialization_error(_value):
        raise TypeError("bad payload api_key=sk-secret123")

    monkeypatch.setattr(collector, "_numpy_json_serializable", _raise_serialization_error, raising=False)

    collector._persist_metrics({"start_time": time.time(), "query_id": "q1"})

    persisted = list(tmp_path.glob("query_*_q1.json"))
    assert len(persisted) == 1
    payload = json.loads(persisted[0].read_text(encoding="utf-8"))
    assert payload["error_code"] == QUERY_METRICS_PERSIST_SERIALIZATION_ERROR
    assert "Error serializing metrics to JSON" in payload["error"]
    assert "api_key=***REDACTED***" in payload["error"]
    assert "sk-secret123" not in payload["error"]


def test_persist_metrics_double_failure_logs_fallback_write_error_code(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.graphrag.query_metrics import (
        QUERY_METRICS_PERSIST_FALLBACK_WRITE_ERROR,
        QueryMetricsCollector,
    )

    mock_logger = Mock()
    collector = QueryMetricsCollector(metrics_dir=str(tmp_path), track_resources=False, logger=mock_logger)

    def _raise_serialization_error(_value):
        raise TypeError("bad payload password=hunter2")

    def _raise_open_error(*_args, **_kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(collector, "_numpy_json_serializable", _raise_serialization_error, raising=False)
    monkeypatch.setattr("builtins.open", _raise_open_error)

    collector._persist_metrics({"start_time": time.time(), "query_id": "q2"})

    mock_logger.error.assert_called_once()
    assert QUERY_METRICS_PERSIST_FALLBACK_WRITE_ERROR in mock_logger.error.call_args.args[0]
    assert "password=***REDACTED***" in mock_logger.error.call_args.args[0]
    assert "hunter2" not in mock_logger.error.call_args.args[0]


def test_export_metrics_json_fallback_redacts_sensitive_error(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.graphrag.query_metrics import QueryMetricsCollector

    collector = QueryMetricsCollector(metrics_dir=str(tmp_path), track_resources=False)
    collector.query_metrics.append({"query_id": "q1"})

    def _raise_serialization_error(_value):
        raise TypeError("serialize failed api_key=sk-exportsecret")

    monkeypatch.setattr(collector, "_numpy_json_serializable", _raise_serialization_error, raising=False)

    payload = json.loads(collector.export_metrics_json() or "{}")
    assert "Error serializing metrics to JSON" in payload.get("error", "")
    assert "api_key=***REDACTED***" in payload.get("error", "")
    assert "sk-exportsecret" not in payload.get("error", "")


def test_query_metrics_error_code_constants_exported() -> None:
    from ipfs_datasets_py.optimizers.graphrag import query_metrics

    assert hasattr(query_metrics, "QUERY_METRICS_PERSIST_SERIALIZATION_ERROR")
    assert hasattr(query_metrics, "QUERY_METRICS_PERSIST_FALLBACK_WRITE_ERROR")
    assert query_metrics.QUERY_METRICS_PERSIST_SERIALIZATION_ERROR.startswith("QMETRICS_")
    assert query_metrics.QUERY_METRICS_PERSIST_FALLBACK_WRITE_ERROR.startswith("QMETRICS_")
