"""Training exploration bounds must not weaken the objective or its guards."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def runner(monkeypatch):
    scripts = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("autoformal_training_under_test", scripts / "run_autoformal_training_cycle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_native_heads_can_be_considered_without_relaxing_losses(runner):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingConfig

    original = {**TrainingConfig().projection_kwargs(), "profile_projection": False,
                "use_sample_memory": False, "metric_disk_cache": 0}
    prepared = runner.training_configuration(original, max_seconds=600,
                                              max_update_families=5, max_line_search_attempts=2)
    editable = {"epochs", "max_seconds", "max_line_search_attempts",
                "projection_max_update_families", "profile_projection"}
    assert {key: value for key, value in prepared.items() if key not in editable} == {
        key: value for key, value in original.items() if key not in editable}
    assert prepared["projection_max_update_families"] == 5
    assert prepared["profile_projection"] is True
    assert original["projection_max_update_families"] == 1
    assert original["profile_projection"] is False
    # The native worker's closed schema still accepts the resulting config.
    checked = TrainingConfig.from_dict(prepared)
    assert checked.max_cross_entropy_regression == original["max_cross_entropy_regression"]
    assert checked.use_sample_memory is False


@pytest.mark.parametrize("families", [1, 2, 3, 4, 5])
def test_operator_can_bound_head_exploration(runner, families):
    result = runner.training_configuration({}, max_seconds=600, max_update_families=families,
                                            max_line_search_attempts=1)
    assert result["projection_max_update_families"] == families


@pytest.mark.parametrize("overrides", [
    {"max_seconds": 0}, {"max_seconds": 601}, {"max_seconds": float("nan")},
    {"max_update_families": 0}, {"max_update_families": 6}, {"max_update_families": True},
    {"max_line_search_attempts": 0}, {"max_line_search_attempts": 7},
])
def test_unbounded_or_invalid_training_is_refused(runner, overrides):
    arguments = {"max_seconds": 600, "max_update_families": 5, "max_line_search_attempts": 1, **overrides}
    with pytest.raises(ValueError):
        runner.training_configuration({}, **arguments)


def test_cycle_schedule_published_todos_uses_pointer(runner, tmp_path):
    huggingface = {
        "pointer": {"pointer_path": str(tmp_path / "pointer.json")},
        "locator": {"dataset_repo_id": "justicedao/uscode-autoformal-todos"},
    }
    (tmp_path / "pointer.json").write_text("{}", encoding="utf-8")
    seen = {}

    def fake_schedule(pointer, **kwargs):
        seen["pointer"] = Path(pointer)
        seen["queue"] = kwargs["queue_path"]
        seen["max_tokens"] = kwargs["max_tokens"]
        return {"scheduled_task_ids": ["AFTD-001"], "jsonl_written": False}

    args = SimpleNamespace(
        pointer=tmp_path / "pointer.json",
        board=tmp_path / "board.md",
        schedule_queue=tmp_path / "queue.json",
        huggingface_package=tmp_path / "pkg",
        max_tokens=12000,
        max_validation_seconds=300,
    )
    receipt = runner.schedule_published_todos(
        huggingface, args, repo_root=tmp_path, schedule=fake_schedule
    )
    assert receipt["jsonl_written"] is False
    assert seen["queue"] == tmp_path / "queue.json"
    assert seen["pointer"] == tmp_path / "pointer.json"
    assert seen["max_tokens"] == 12000


def test_cycle_can_publish_observation_todos_without_jsonl(tmp_path):
    from ipfs_datasets_py.huggingface.autoformal_todo import publish_observation_todos

    observations = [
        {
            "rows": [
                {
                    "id": "train-1",
                    "source_span_id": "train-1",
                    "text": "Each agency shall make records available.",
                    "reason": "no_parser_elements",
                    "agrees": False,
                    "skipped": False,
                    "dropped": [],
                    "decompiled": "",
                }
            ]
        }
    ]
    receipt = publish_observation_todos(
        observations,
        tmp_path / "pkg",
        board_path=tmp_path / "board.md",
        pointer_path=tmp_path / "pointer.json",
        release_id="cycle-1",
    )
    assert receipt["jsonl_written"] is False
    assert receipt["wrote_compiler"] is False
    assert receipt["task_count"] == 1
    assert (tmp_path / "pointer.json").is_file()
