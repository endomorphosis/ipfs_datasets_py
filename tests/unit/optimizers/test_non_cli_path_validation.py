"""Tests for non-CLI path validation in optimizer modules."""

from __future__ import annotations

import datetime
import json

import pytest

from ipfs_datasets_py.optimizers.common.path_validator import PathValidationError
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.prompt_optimizer import (
    PromptOptimizer,
)
from ipfs_datasets_py.optimizers.optimizer_alert_system import (
    LearningAlertSystem,
    LearningAnomaly,
)


def test_prompt_optimizer_export_import_round_trip(tmp_path):
    optimizer = PromptOptimizer()
    prompt_id = optimizer.add_prompt("Extract logic: {data}")
    optimizer.record_usage(
        prompt_id=prompt_id,
        success=True,
        confidence=0.9,
        critic_score=0.8,
        extraction_time=1.2,
    )

    export_path = tmp_path / "prompt_library.json"
    optimizer.export_library(str(export_path))

    reloaded = PromptOptimizer()
    reloaded.import_library(str(export_path))

    assert prompt_id in reloaded.prompt_library
    assert prompt_id in reloaded.prompt_metrics

    metrics = reloaded.prompt_metrics[prompt_id]
    assert metrics.total_uses == optimizer.prompt_metrics[prompt_id].total_uses
    assert metrics.success_rate == optimizer.prompt_metrics[prompt_id].success_rate
    assert metrics.avg_confidence == optimizer.prompt_metrics[prompt_id].avg_confidence
    assert metrics.avg_critic_score == optimizer.prompt_metrics[prompt_id].avg_critic_score


def test_prompt_optimizer_export_blocks_system_path():
    optimizer = PromptOptimizer()
    optimizer.add_prompt("Extract logic: {data}")

    with pytest.raises(PathValidationError):
        optimizer.export_library("/etc/passwd")


def test_prompt_optimizer_import_blocks_system_path():
    optimizer = PromptOptimizer()

    with pytest.raises(PathValidationError):
        optimizer.import_library("/etc/passwd")


def test_alert_system_saves_anomaly_record(tmp_path):
    alerts_dir = tmp_path / "alerts"
    system = LearningAlertSystem(alerts_dir=str(alerts_dir))

    anomaly = LearningAnomaly(
        anomaly_type="oscillation",
        severity="warning",
        description="Test anomaly",
        affected_parameters=["learning_rate"],
        timestamp=datetime.datetime.now(),
        metric_values={"learning_rate": [0.1, 0.01]},
        id="test123",
    )

    system._save_anomaly_to_file(anomaly)

    record_path = alerts_dir / "anomaly_test123.json"
    assert record_path.exists()

    payload = json.loads(record_path.read_text())
    assert payload["id"] == "test123"
    assert payload["anomaly_type"] == "oscillation"


def test_alert_system_blocks_system_path(caplog):
    system = LearningAlertSystem(alerts_dir="/etc")

    anomaly = LearningAnomaly(
        anomaly_type="decline",
        severity="critical",
        description="Blocked path test",
        affected_parameters=["score"],
        timestamp=datetime.datetime.now(),
        metric_values={"score": [0.9, 0.7]},
        id="blocked",
    )

    system._save_anomaly_to_file(anomaly)

    assert any("Error saving anomaly record" in record.message for record in caplog.records)
