from __future__ import annotations

import json
from unittest.mock import Mock


def test_save_learning_state_serialization_error_writes_partial_state(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.graphrag.query_unified_optimizer import (
        UnifiedGraphRAGQueryOptimizer,
    )

    optimizer = UnifiedGraphRAGQueryOptimizer(metrics_dir=str(tmp_path))
    optimizer._learning_enabled = True
    optimizer._learning_cycle = 10

    def _raise_serialization_error(_value):
        raise TypeError("serialization failed")

    monkeypatch.setattr(
        optimizer, "_numpy_json_serializable", _raise_serialization_error, raising=False
    )

    target = tmp_path / "learning_state.json"
    saved_path = optimizer.save_learning_state(str(target))

    assert saved_path == str(target)
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["partial_state"] is True
    assert "Error serializing learning state to JSON" in payload["error"]


def test_save_learning_state_double_failure_records_metric(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.graphrag.query_unified_optimizer import (
        UnifiedGraphRAGQueryOptimizer,
    )

    class _MetricsCollector:
        def __init__(self):
            self.calls = []

        def record_additional_metric(self, **kwargs):
            self.calls.append(kwargs)

    metrics = _MetricsCollector()
    optimizer = UnifiedGraphRAGQueryOptimizer(metrics_dir=str(tmp_path), metrics_collector=metrics)
    optimizer._learning_enabled = True
    optimizer._learning_cycle = 10

    def _raise_serialization_error(_value):
        raise TypeError("serialization failed")

    def _raise_open_error(*_args, **_kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(
        optimizer, "_numpy_json_serializable", _raise_serialization_error, raising=False
    )
    monkeypatch.setattr("builtins.open", _raise_open_error)

    result = optimizer.save_learning_state(str(tmp_path / "learning_state.json"))

    assert result is None
    assert len(metrics.calls) == 1
    assert metrics.calls[0]["name"] == "serialization_error"
    assert "Failed to save learning state" in metrics.calls[0]["value"]
    assert metrics.calls[0]["category"] == "error"


def test_load_learning_state_invalid_json_logs_and_returns_false(tmp_path):
    from ipfs_datasets_py.optimizers.graphrag.query_unified_optimizer import (
        UnifiedGraphRAGQueryOptimizer,
    )

    target = tmp_path / "learning_state.json"
    target.write_text("{invalid-json", encoding="utf-8")

    optimizer = UnifiedGraphRAGQueryOptimizer(metrics_dir=str(tmp_path))
    optimizer.logger = Mock()

    loaded = optimizer.load_learning_state(str(target))

    assert loaded is False
    optimizer.logger.error.assert_called_once()


def test_load_learning_state_success_restores_fields(tmp_path):
    from ipfs_datasets_py.optimizers.graphrag.query_unified_optimizer import (
        UnifiedGraphRAGQueryOptimizer,
    )

    target = tmp_path / "learning_state.json"
    target.write_text(
        json.dumps(
            {
                "learning_enabled": True,
                "learning_cycle": 33,
                "learning_parameters": {"alpha": 0.2},
                "traversal_stats": {"paths_explored": ["n1...n2(2)"]},
                "entity_importance_cache": {"e1": 0.75},
            }
        ),
        encoding="utf-8",
    )

    optimizer = UnifiedGraphRAGQueryOptimizer(metrics_dir=str(tmp_path))
    optimizer._learning_enabled = False
    optimizer._learning_cycle = 1

    loaded = optimizer.load_learning_state(str(target))

    assert loaded is True
    assert optimizer._learning_enabled is True
    assert optimizer._learning_cycle == 33
    assert optimizer._learning_parameters["alpha"] == 0.2
    assert optimizer._traversal_stats["paths_explored"] == ["n1...n2(2)"]
    assert optimizer._entity_importance_cache["e1"] == 0.75
