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
        raise TypeError("bad payload")

    monkeypatch.setattr(collector, "_numpy_json_serializable", _raise_serialization_error, raising=False)

    collector._persist_metrics({"start_time": time.time(), "query_id": "q1"})

    persisted = list(tmp_path.glob("query_*_q1.json"))
    assert len(persisted) == 1
    payload = json.loads(persisted[0].read_text(encoding="utf-8"))
    assert payload["error_code"] == QUERY_METRICS_PERSIST_SERIALIZATION_ERROR
    assert "Error serializing metrics to JSON" in payload["error"]


def test_persist_metrics_double_failure_logs_fallback_write_error_code(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.graphrag.query_metrics import (
        QUERY_METRICS_PERSIST_FALLBACK_WRITE_ERROR,
        QueryMetricsCollector,
    )

    mock_logger = Mock()
    collector = QueryMetricsCollector(metrics_dir=str(tmp_path), track_resources=False, logger=mock_logger)

    def _raise_serialization_error(_value):
        raise TypeError("bad payload")

    def _raise_open_error(*_args, **_kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(collector, "_numpy_json_serializable", _raise_serialization_error, raising=False)
    monkeypatch.setattr("builtins.open", _raise_open_error)

    collector._persist_metrics({"start_time": time.time(), "query_id": "q2"})

    mock_logger.error.assert_called_once()
    assert QUERY_METRICS_PERSIST_FALLBACK_WRITE_ERROR in mock_logger.error.call_args.args[0]
