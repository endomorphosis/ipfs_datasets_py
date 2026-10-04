"""Batch 315: unit tests for extracted graphrag.serialization helpers."""

from __future__ import annotations

import json
from unittest.mock import Mock

from ipfs_datasets_py.optimizers.graphrag import (
    build_learning_state,
    load_learning_state_payload,
    resolve_learning_state_filepath,
    save_learning_state_payload,
)


def test_resolve_learning_state_filepath_prefers_explicit_path(tmp_path) -> None:
    explicit = str(tmp_path / "custom.json")
    assert resolve_learning_state_filepath(explicit, None) == explicit


def test_resolve_learning_state_filepath_uses_metrics_dir(tmp_path) -> None:
    resolved = resolve_learning_state_filepath(None, str(tmp_path))
    assert resolved == str(tmp_path / "learning_state.json")


def test_build_learning_state_contains_expected_keys() -> None:
    payload = build_learning_state(
        learning_enabled=True,
        learning_cycle=7,
        learning_parameters={"alpha": 0.1},
        traversal_stats={"paths_explored": []},
        entity_importance_cache={"e1": 0.8},
    )
    assert payload["learning_enabled"] is True
    assert payload["learning_cycle"] == 7
    assert payload["learning_parameters"]["alpha"] == 0.1
    assert "timestamp" in payload


def test_save_learning_state_payload_writes_fallback_on_serialization_error(tmp_path) -> None:
    target = tmp_path / "state.json"

    def _raise(_value):
        raise TypeError("serialization failed")

    saved_path = save_learning_state_payload(
        filepath=str(target),
        state={"learning_enabled": True, "learning_cycle": 10},
        numpy_json_serializable=_raise,
        safe_error_text=lambda e: str(e),
        metrics_collector=None,
    )

    assert saved_path == str(target)
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["partial_state"] is True
    assert payload["learning_cycle"] == 10
    assert payload["learning_cycles_completed"] == 10


def test_load_learning_state_payload_returns_false_and_logs_on_invalid_json(tmp_path) -> None:
    target = tmp_path / "state.json"
    target.write_text("{bad-json", encoding="utf-8")
    logger = Mock()

    loaded, state = load_learning_state_payload(
        filepath=str(target),
        safe_error_text=lambda e: str(e),
        logger=logger,
    )

    assert loaded is False
    assert state == {}
    logger.error.assert_called_once()
